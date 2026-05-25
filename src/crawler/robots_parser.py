import logging
from typing import Any
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import aiohttp

logger = logging.getLogger(__name__)


class RobotsParser:
    """Fetches and caches robots.txt per domain, then answers can_fetch queries.

    The first call to `fetch_robots` for a domain makes an HTTP request and caches
    the result. Subsequent calls for the same domain skip the network entirely.

    Must be used either as an async context manager (owns its own session) or with
    `set_session` to share the caller's existing session.

    Args:
        user_agent: User-Agent string matched against robots.txt Allow/Disallow rules.
            Should match the value sent in HTTP request headers so the rules apply
            to the actual requests being made.
        timeout_seconds: HTTP timeout for fetching robots.txt files, in seconds.
    """

    def __init__(
        self,
        user_agent: str = "*",
        timeout_seconds: float = 10.0,
    ) -> None:
        self.user_agent = user_agent
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds)
        self._parsers: dict[str, RobotFileParser | None] = {}
        self._results: dict[str, dict[str, Any]] = {}
        self._session: aiohttp.ClientSession | None = None

    def set_session(self, session: aiohttp.ClientSession) -> None:
        self._session = session

    async def __aenter__(self) -> "RobotsParser":
        self._session = aiohttp.ClientSession(timeout=self._timeout)
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def fetch_robots(self, base_url: str) -> dict[str, Any]:
        if self._session is None:
            raise RuntimeError("Session is not initialized")

        domain = self._extract_domain(base_url)

        if domain in self._results:
            return self._results[domain]

        robots_url = self._build_robots_url(base_url)

        try:
            async with self._session.get(robots_url) as response:
                if response.status == 200:
                    content = await response.text()
                    parser = RobotFileParser()
                    parser.set_url(robots_url)
                    parser.parse(content.splitlines())
                    self._parsers[domain] = parser

                    delay = parser.crawl_delay(self.user_agent)
                    result: dict[str, Any] = {
                        "url": robots_url,
                        "domain": domain,
                        "fetched": True,
                        "status": 200,
                        "crawl_delay": float(delay) if delay is not None else None,
                        "sitemaps": list(parser.site_maps() or []),
                        "fetch_error": None,
                    }
                else:
                    self._parsers[domain] = None
                    result = {
                        "url": robots_url,
                        "domain": domain,
                        "fetched": True,
                        "status": response.status,
                        "crawl_delay": None,
                        "sitemaps": [],
                        "fetch_error": None,
                    }

        except Exception as error:
            logger.warning("Failed to fetch robots.txt for %s: %s", domain, error)
            self._parsers[domain] = None
            result = {
                "url": robots_url,
                "domain": domain,
                "fetched": False,
                "status": None,
                "crawl_delay": None,
                "sitemaps": [],
                "fetch_error": f"{type(error).__name__}: {error}",
            }

        self._results[domain] = result
        return result

    def can_fetch(self, url: str, user_agent: str | None = None) -> bool:
        agent = user_agent if user_agent is not None else self.user_agent
        domain = self._extract_domain(url)

        if domain not in self._parsers:
            return True

        parser = self._parsers[domain]
        if parser is None:
            return True

        return parser.can_fetch(agent, url)

    def get_crawl_delay(self, url: str, user_agent: str | None = None) -> float:
        agent = user_agent if user_agent is not None else self.user_agent
        domain = self._extract_domain(url)

        if domain not in self._parsers:
            return 0.0

        parser = self._parsers[domain]
        if parser is None:
            return 0.0

        delay = parser.crawl_delay(agent)
        return float(delay) if delay is not None else 0.0

    def _extract_domain(self, url: str) -> str:
        parsed = urlparse(url)
        netloc = parsed.netloc or parsed.path
        return netloc.lower().strip()

    def _build_robots_url(self, base_url: str) -> str:
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}/robots.txt"
