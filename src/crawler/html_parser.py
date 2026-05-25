import logging
from typing import Any
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup
from bs4.element import Tag

logger = logging.getLogger(__name__)


class HTMLParser:
    """Stateless HTML parser that extracts structured data from raw HTML strings.

    All methods are pure — no internal state is mutated between calls.
    """

    def parse_html(
        self,
        html: str,
        url: str,
        same_domain_only: bool = False,
    ) -> dict[str, Any]:
        # BeautifulSoup tolerates broken HTML, but this protects us from
        # invalid input types or parser backend issues.
        try:
            soup = BeautifulSoup(html, "lxml")
        except Exception as error:
            logger.warning(
                "Failed to parse HTML for %s | %s: %s",
                url,
                type(error).__name__,
                error,
            )

            return self.empty_result(
                url=url,
                parse_error=f"{type(error).__name__}: {error}",
            )

        return {
            "url": url,
            "title": self.extract_title(soup),
            "text": self.extract_text(soup),
            "links": self.extract_links(
                soup=soup,
                base_url=url,
                same_domain_only=same_domain_only,
            ),
            "metadata": self.extract_metadata(soup),
            "images": self.extract_images(soup, url),
            "headings": self.extract_headings(soup),
            "tables": self.extract_tables(soup),
            "lists": self.extract_lists(soup),
            "parse_errors": [],
        }

    def empty_result(
        self,
        url: str,
        parse_error: str | None = None,
    ) -> dict[str, Any]:
        return {
            "url": url,
            "title": None,
            "text": "",
            "links": [],
            "metadata": {
                "description": None,
                "keywords": None,
            },
            "images": [],
            "headings": {
                "h1": [],
                "h2": [],
                "h3": [],
            },
            "tables": [],
            "lists": [],
            "parse_errors": [parse_error] if parse_error else [],
        }

    def extract_title(self, soup: BeautifulSoup) -> str | None:
        if soup.title and soup.title.string:
            return self.normalize_text(soup.title.string)

        return None

    def extract_links(
        self,
        soup: BeautifulSoup,
        base_url: str,
        same_domain_only: bool = False,
    ) -> list[str]:
        links: list[str] = []

        for tag in soup.find_all("a", href=True):
            if not isinstance(tag, Tag):
                continue

            href = tag.get("href")

            if not isinstance(href, str):
                continue

            href = href.strip()

            if not href or href.startswith("#"):
                continue

            absolute_url = urljoin(base_url, href)

            if not self.is_valid_url(absolute_url):
                continue

            if same_domain_only and not self.is_same_domain(
                base_url,
                absolute_url,
            ):
                continue

            links.append(absolute_url)

        # Keep order while removing duplicates.
        return list(dict.fromkeys(links))

    def extract_text(
        self,
        soup: BeautifulSoup,
        selector: str | None = None,
    ) -> str:
        if selector:
            target = soup.select_one(selector)
        else:
            # Use body by default to avoid mixing <head>/<title> into page text.
            target = soup.body or soup

        if target is None:
            return ""

        text = target.get_text(separator=" ", strip=True)

        return self.normalize_text(text)

    def extract_metadata(self, soup: BeautifulSoup) -> dict[str, str | None]:
        return {
            "description": self.extract_meta_content(soup, "description"),
            "keywords": self.extract_meta_content(soup, "keywords"),
        }

    def extract_meta_content(
        self,
        soup: BeautifulSoup,
        name: str,
    ) -> str | None:
        tag = soup.find("meta", attrs={"name": name})

        if not isinstance(tag, Tag):
            return None

        content = tag.get("content")

        if not isinstance(content, str):
            return None

        return self.normalize_text(content)

    def extract_images(
        self,
        soup: BeautifulSoup,
        base_url: str,
    ) -> list[dict[str, str | None]]:
        images: list[dict[str, str | None]] = []

        for tag in soup.find_all("img", src=True):
            if not isinstance(tag, Tag):
                continue

            src = tag.get("src")
            alt = tag.get("alt")

            if not isinstance(src, str):
                continue

            absolute_src = urljoin(base_url, src)

            if not self.is_valid_url(absolute_src):
                continue

            images.append(
                {
                    "src": absolute_src,
                    "alt": self.normalize_text(alt) if isinstance(alt, str) else None,
                }
            )

        return images

    def extract_headings(self, soup: BeautifulSoup) -> dict[str, list[str]]:
        headings: dict[str, list[str]] = {}

        for level in ["h1", "h2", "h3"]:
            headings[level] = [
                self.normalize_text(tag.get_text(separator=" ", strip=True))
                for tag in soup.find_all(level)
                if isinstance(tag, Tag)
            ]

        return headings

    def extract_tables(self, soup: BeautifulSoup) -> list[list[list[str]]]:
        tables: list[list[list[str]]] = []

        for table in soup.find_all("table"):
            if not isinstance(table, Tag):
                continue

            rows: list[list[str]] = []

            for row in table.find_all("tr"):
                if not isinstance(row, Tag):
                    continue

                cells: list[str] = []

                for cell in row.find_all(["th", "td"]):
                    if not isinstance(cell, Tag):
                        continue

                    cell_text = cell.get_text(separator=" ", strip=True)
                    normalized_cell = self.normalize_text(cell_text)

                    if normalized_cell:
                        cells.append(normalized_cell)

                if cells:
                    rows.append(cells)

            if rows:
                tables.append(rows)

        return tables

    def extract_lists(self, soup: BeautifulSoup) -> list[dict[str, Any]]:
        lists: list[dict[str, Any]] = []

        for list_tag in soup.find_all(["ul", "ol"]):
            if not isinstance(list_tag, Tag):
                continue

            items: list[str] = []

            # recursive=False avoids aggressively mixing nested list items
            # into the current list level.
            for item in list_tag.find_all("li", recursive=False):
                if not isinstance(item, Tag):
                    continue

                item_text = item.get_text(separator=" ", strip=True)
                normalized_item = self.normalize_text(item_text)

                if normalized_item:
                    items.append(normalized_item)

            if items:
                lists.append(
                    {
                        "type": str(list_tag.name),
                        "items": items,
                    }
                )

        return lists

    def is_valid_url(self, url: str) -> bool:
        parsed_url = urlparse(url)

        return parsed_url.scheme in {"http", "https"} and bool(parsed_url.netloc)

    def is_same_domain(self, base_url: str, target_url: str) -> bool:
        base_domain = urlparse(base_url).netloc.lower()
        target_domain = urlparse(target_url).netloc.lower()

        return base_domain == target_domain

    def normalize_text(self, text: str) -> str:
        # HTML whitespace is noisy: newlines, tabs, repeated spaces.
        return " ".join(text.split())
