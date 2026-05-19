import asyncio
import logging
from typing import Any

import aiohttp


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)


class AsyncCrawler:
    def __init__(self, max_concurrent: int = 5, timeout_seconds: float = 10):
        self.max_concurrent = max_concurrent
        self.timeout_seconds = timeout_seconds

        self.semaphore = asyncio.Semaphore(max_concurrent)

        self.session: aiohttp.ClientSession | None = None

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

    async def fetch_url(self, url: str) -> dict[str, Any]:
        if self.session is None:
            raise RuntimeError("Session is not initialized")

        async with self.semaphore:
            logging.info(f"Start fetching: {url}")

            try:
                async with self.session.get(url) as response:
                    response.raise_for_status()

                    content = await response.text()

                    logging.info(f"Success: {url} | status={response.status}")

                    return {
                        "url": url,
                        "success": True,
                        "status": response.status,
                        "content": content,
                        "error": None,
                    }

            except asyncio.TimeoutError as error:
                logging.warning(f"Timeout error: {url}")

                return {
                    "url": url,
                    "success": False,
                    "status": None,
                    "content": None,
                    "error": str(error),
                }

            except aiohttp.ClientResponseError as error:
                logging.warning(f"HTTP error: {url} | status={error.status}")

                return {
                    "url": url,
                    "success": False,
                    "status": error.status,
                    "content": None,
                    "error": str(error),
                }

            except aiohttp.ClientError as error:
                logging.warning(f"Network error: {url} | {error}")

                return {
                    "url": url,
                    "success": False,
                    "status": None,
                    "content": None,
                    "error": str(error),
                }

    async def fetch_urls(
        self,
        urls: list[str],
    ) -> dict[str, dict[str, Any]]:
        tasks = [self.fetch_url(url) for url in urls]

        results = await asyncio.gather(*tasks)

        return {result["url"]: result for result in results}
