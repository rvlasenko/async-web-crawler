import asyncio
import logging
import xml.etree.ElementTree as ET

import aiohttp

logger = logging.getLogger(__name__)

_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


class SitemapParser:
    """Fetches and parses XML sitemaps, including sitemap index files.

    Uses a shared aiohttp.ClientSession (typically from AsyncCrawler) to avoid
    opening an extra connection pool. Recursive sitemap index fetching is
    bounded by max_recursion_depth to prevent runaway loops on malformed files.

    All errors (network, HTTP non-2xx, malformed XML, depth exceeded) are
    logged and silently swallowed — fetch_sitemap always returns a list,
    never raises.

    Args:
        session: Open aiohttp.ClientSession to use for all requests.
        max_recursion_depth: Maximum depth when recursively following sitemap
            index files. Default 3.
        timeout_seconds: Per-request timeout for sitemap fetches.
    """

    def __init__(
        self,
        session: aiohttp.ClientSession,
        max_recursion_depth: int = 3,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._session = session
        self._max_depth = max_recursion_depth
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)

    async def fetch_sitemap(
        self,
        sitemap_url: str,
        _current_depth: int = 0,
    ) -> list[str]:
        """Fetch a sitemap URL and return all page URLs found.

        Handles both regular sitemaps (<url><loc>) and sitemap index files
        (<sitemapindex><sitemap><loc>). Deduplicates returned URLs while
        preserving the order they appear in the document.

        Returns an empty list on any error.
        """
        if _current_depth > self._max_depth:
            logger.info(
                "Sitemap recursion limit (%d) reached for %s — stopping",
                self._max_depth,
                sitemap_url,
            )
            return []

        xml_text = await self._fetch_xml(sitemap_url)
        if xml_text is None:
            return []

        try:
            root = ET.fromstring(xml_text)
        except ET.ParseError as exc:
            logger.warning("Failed to parse sitemap XML from %s: %s", sitemap_url, exc)
            return []

        if root.tag == f"{{{_NS}}}sitemapindex":
            return await self._parse_index(root, _current_depth)

        return self._parse_urlset(root)

    async def _fetch_xml(self, url: str) -> str | None:
        try:
            async with self._session.get(url, timeout=self._timeout) as resp:
                if resp.status == 404:
                    logger.info("Sitemap not found (404): %s", url)
                    return None
                if resp.status != 200:
                    logger.warning(
                        "Sitemap fetch returned HTTP %d for %s", resp.status, url
                    )
                    return None
                return await resp.text()
        except asyncio.TimeoutError:
            logger.warning("Timeout fetching sitemap: %s", url)
            return None
        except aiohttp.ClientError as exc:
            logger.warning("Network error fetching sitemap %s: %s", url, exc)
            return None

    async def _parse_index(self, root: ET.Element, current_depth: int) -> list[str]:
        child_urls = [
            loc.text.strip()
            for sitemap in root.findall(f"{{{_NS}}}sitemap")
            for loc in sitemap.findall(f"{{{_NS}}}loc")
            if loc.text and loc.text.strip()
        ]

        if not child_urls:
            return []

        results: list[list[str]] = await asyncio.gather(
            *[
                self.fetch_sitemap(u, _current_depth=current_depth + 1)
                for u in child_urls
            ]
        )

        seen: set[str] = set()
        urls: list[str] = []
        for batch in results:
            for url in batch:
                if url not in seen:
                    seen.add(url)
                    urls.append(url)
        return urls

    def _parse_urlset(self, root: ET.Element) -> list[str]:
        seen: set[str] = set()
        urls: list[str] = []
        for url_el in root.findall(f"{{{_NS}}}url"):
            for loc in url_el.findall(f"{{{_NS}}}loc"):
                if loc.text and loc.text.strip():
                    url = loc.text.strip()
                    if url not in seen:
                        seen.add(url)
                        urls.append(url)
        return urls
