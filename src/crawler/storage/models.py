from datetime import datetime
from typing import Any, TypedDict


class CrawledPage(TypedDict):
    """Standardised record for one crawled page.

    Fields split by origin:

    From HTMLParser (page content):
        url          — original requested URL (not the post-redirect final_url)
        title        — <title> tag content, None if absent
        text         — visible body text, whitespace-normalised
        links        — absolute URLs found on the page
        metadata     — <meta> tags: description, keywords

    Added by AsyncCrawler (request metadata):
        status_code  — HTTP status of the response (200, 301, etc.)
        content_type — Content-Type response header, e.g. "text/html; charset=utf-8"
        crawled_at   — timezone-aware UTC datetime of when the page was fetched
    """

    url: str
    title: str | None
    text: str
    links: list[str]
    metadata: dict[str, Any]
    crawled_at: datetime
    status_code: int | None
    content_type: str | None
