import asyncio
import logging
from typing import Any

import aiohttp

from crawler.html_parser import HTMLParser

logger = logging.getLogger(__name__)


class AsyncCrawler:
    def __init__(self, max_concurrent: int = 5, timeout_seconds: float = 10):
        self.max_concurrent = max_concurrent
        self.timeout_seconds = timeout_seconds

        self.semaphore = asyncio.Semaphore(max_concurrent)

        self.session: aiohttp.ClientSession | None = None

        self.parser = HTMLParser()

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(
            connect=5,
            sock_read=self.timeout_seconds,
        )

        self.session = aiohttp.ClientSession(timeout=timeout)

        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.close()

    async def close(self) -> None:
        if self.session and not self.session.closed:
            await self.session.close()

    async def fetch_and_parse(
        self,
        url: str,
        same_domain_only: bool = False,
    ) -> dict[str, Any]:
        fetch_result = await self.fetch_url(url)

        if not fetch_result["success"]:
            result = self.parser.empty_result(url)

            return result

        content = fetch_result["content"]

        if not isinstance(content, str):
            result = self.parser.empty_result(url)

            result["parse_errors"] = ["Fetch content is not a string"]

            return result

        parsed_data = self.parser.parse_html(
            html=content,
            url=url,
            same_domain_only=same_domain_only,
        )

        return parsed_data

    async def fetch_and_parse_urls(
        self,
        urls: list[str],
        same_domain_only: bool = False,
    ) -> dict[str, dict[str, Any]]:
        tasks = [
            self.fetch_and_parse(
                url=url,
                same_domain_only=same_domain_only,
            )
            for url in urls
        ]

        results = await asyncio.gather(*tasks)

        return {result["url"]: result for result in results}

    async def fetch_url(self, url: str) -> dict[str, Any]:
        if self.session is None:
            raise RuntimeError("Session is not initialized")

        async with self.semaphore:
            logger.info(f"Start fetching: {url}")

            try:
                async with self.session.get(url) as response:
                    response.raise_for_status()

                    content = await response.text()

                    logger.info(f"Success: {url} | status={response.status}")

                    return {
                        "url": url,
                        "success": True,
                        "status": response.status,
                        "content": content,
                        "error": None,
                    }

            except asyncio.TimeoutError as error:
                logger.warning(f"Timeout error: {url}")

                return {
                    "url": url,
                    "success": False,
                    "status": None,
                    "content": None,
                    "error": str(error),
                }

            except aiohttp.ClientResponseError as error:
                logger.warning(f"HTTP error: {url} | status={error.status}")

                return {
                    "url": url,
                    "success": False,
                    "status": error.status,
                    "content": None,
                    "error": str(error),
                }

            except aiohttp.ClientError as error:
                logger.warning(f"Network error: {url} | {error}")

                return {
                    "url": url,
                    "success": False,
                    "status": None,
                    "content": None,
                    "error": str(error),
                }

            except Exception as error:
                logger.exception("Unexpected error while fetching: %s", url)

                return {
                    "url": url,
                    "success": False,
                    "status": None,
                    "content": None,
                    "error": f"{type(error).__name__}: {error}",
                }

    async def fetch_urls(
        self,
        urls: list[str],
    ) -> dict[str, dict[str, Any]]:
        tasks = [self.fetch_url(url) for url in urls]

        # TODO:
        # Consider using asyncio.gather(..., return_exceptions=True)
        # for large-scale crawling robustness.
        results = await asyncio.gather(*tasks)

        return {result["url"]: result for result in results}
