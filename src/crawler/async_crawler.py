import asyncio
import logging
import time
from typing import Any

import aiohttp

from crawler.crawler_queue import CrawlerQueue
from crawler.html_parser import HTMLParser
from crawler.rate_limiter import RateLimiter
from crawler.semaphore_manager import SemaphoreManager

logger = logging.getLogger(__name__)


class AsyncCrawler:
    def __init__(
        self,
        max_concurrent: int = 5,
        timeout_seconds: float = 10,
        max_depth: int | None = None,
        requests_per_second: float | None = None,
        rate_limit_per_domain: bool = True,
    ):
        self.max_concurrent = max_concurrent
        self.timeout_seconds = timeout_seconds
        self.max_depth = max_depth

        self.rate_limiter = (
            RateLimiter(
                requests_per_second=requests_per_second,
                per_domain=rate_limit_per_domain,
            )
            if requests_per_second is not None
            else None
        )

        self.semaphore_manager = SemaphoreManager(
            global_limit=max_concurrent,
            per_domain_limit=2,
        )

        self.session: aiohttp.ClientSession | None = None

        self.parser = HTMLParser()
        self.visited_urls: set[str] = set()
        self.failed_urls: dict[str, str] = {}
        self.processed_urls: dict[str, dict[str, Any]] = {}
        self._crawl_started_at: float | None = None
        self._crawl_finished_at: float | None = None
        self._queued_count = 0

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

    async def crawl(
        self,
        start_urls: list[str],
        max_pages: int = 100,
        same_domain_only: bool = False,
        include_patterns: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        show_progress: bool = False,
    ) -> dict[str, dict[str, Any]]:
        self.visited_urls = set()
        self.failed_urls = {}
        self.processed_urls = {}
        self._crawl_started_at = time.perf_counter()
        self._crawl_finished_at = None
        self._queued_count = 0

        if max_pages <= 0 or not start_urls:
            self._crawl_finished_at = time.perf_counter()
            return {}

        queue = CrawlerQueue()

        for url in start_urls:
            queue.add_url(url)

        self._update_crawl_stats(queue)
        self._log_crawl_progress(show_progress)

        while len(self.processed_urls) < max_pages:
            remaining_slots = max_pages - len(self.processed_urls)
            batch_size = min(self.max_concurrent, remaining_slots)
            batch_tasks = await self._collect_batch(queue, batch_size)

            self._update_crawl_stats(queue)
            self._log_crawl_progress(show_progress)

            if not batch_tasks:
                break

            for task in batch_tasks:
                self.visited_urls.add(task.url)

            batch_results = await asyncio.gather(
                *[
                    self.fetch_and_parse(task.url, same_domain_only)
                    for task in batch_tasks
                ]
            )

            for task, parsed_data in zip(batch_tasks, batch_results):
                url = task.url

                if parsed_data["parse_errors"]:
                    error = parsed_data["parse_errors"][0] or "Unknown fetch error"
                    self.failed_urls[url] = error
                    queue.mark_failed(url, error)
                    continue

                self.processed_urls[url] = parsed_data
                queue.mark_processed(url)

                for discovered_url in parsed_data["links"]:
                    if exclude_patterns and self._matches_any_pattern(
                        discovered_url,
                        exclude_patterns,
                    ):
                        continue

                    if include_patterns and not self._matches_any_pattern(
                        discovered_url,
                        include_patterns,
                    ):
                        continue

                    next_depth = task.depth + 1

                    if self.max_depth is not None and next_depth > self.max_depth:
                        continue

                    queue.add_url(discovered_url, depth=next_depth)

                self._update_crawl_stats(queue)
                self._log_crawl_progress(show_progress)

        self._update_crawl_stats(queue)
        self._crawl_finished_at = time.perf_counter()
        self._log_crawl_progress(show_progress)

        return self.processed_urls

    async def fetch_and_parse(
        self,
        url: str,
        same_domain_only: bool = False,
    ) -> dict[str, Any]:
        fetch_result = await self.fetch_url(url)

        if not fetch_result["success"]:
            result = self.parser.empty_result(url)

            result["parse_errors"] = [
                f"Fetch failed: {fetch_result['error'] or 'Unknown fetch error'}"
            ]

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

    async def _collect_batch(
        self,
        queue: CrawlerQueue,
        batch_size: int,
    ) -> list[Any]:
        batch_tasks = []

        for _ in range(batch_size):
            task = await queue.get_next()

            if task is None:
                break

            batch_tasks.append(task)

        return batch_tasks

    def get_crawl_stats(self) -> dict[str, float | int]:
        elapsed_seconds = self._get_elapsed_seconds()

        if elapsed_seconds == 0:
            pages_per_second = 0.0
        else:
            pages_per_second = len(self.processed_urls) / elapsed_seconds

        return {
            "processed_pages": len(self.processed_urls),
            "queued": self._queued_count,
            "errors": len(self.failed_urls),
            "active_tasks": self.semaphore_manager.get_active_tasks_count(),
            "pages_per_second": pages_per_second,
        }

    async def fetch_url(self, url: str) -> dict[str, Any]:
        if self.session is None:
            raise RuntimeError("Session is not initialized")

        if self.rate_limiter is not None:
            await self.rate_limiter.acquire(url)

        async with self.semaphore_manager.acquire(url):
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

    def _matches_any_pattern(
        self,
        url: str,
        patterns: list[str],
    ) -> bool:
        return any(pattern in url for pattern in patterns)

    def _get_elapsed_seconds(self) -> float:
        if self._crawl_started_at is None:
            return 0.0

        end_time = self._crawl_finished_at or time.perf_counter()
        return max(end_time - self._crawl_started_at, 0.0)

    def _update_crawl_stats(self, queue: CrawlerQueue) -> None:
        self._queued_count = queue.get_stats()["queued"]

    def _log_crawl_progress(self, show_progress: bool) -> None:
        if not show_progress:
            return

        stats = self.get_crawl_stats()

        logger.info(
            "Crawl progress: processed=%s queued=%s errors=%s active=%s speed=%.2f pages/s",
            stats["processed_pages"],
            stats["queued"],
            stats["errors"],
            stats["active_tasks"],
            stats["pages_per_second"],
        )
