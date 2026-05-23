import asyncio
import logging
import random
import time
from typing import Any

import aiohttp

from crawler.crawler_queue import CrawlerQueue
from crawler.html_parser import HTMLParser
from crawler.rate_limiter import RateLimiter
from crawler.robots_parser import RobotsParser
from crawler.semaphore_manager import SemaphoreManager

logger = logging.getLogger(__name__)


class AsyncCrawler:
    def __init__(
        self,
        max_concurrent: int = 5,
        timeout_seconds: float = 10,
        max_depth: int | None = None,
        requests_per_second: float | None = None,
        min_delay: float | None = None,
        jitter: float = 0.0,
        rate_limit_per_domain: bool = True,
        respect_robots_txt: bool = False,
        user_agent: str | list[str] = "AsyncCrawler/1.0",
        max_retries: int = 0,
        backoff_base: float = 1.0,
    ):
        self.max_concurrent = max_concurrent
        self.timeout_seconds = timeout_seconds
        self.max_depth = max_depth
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.user_agent = user_agent
        if isinstance(user_agent, list):
            self._primary_user_agent = user_agent[0] if user_agent else ""
        else:
            self._primary_user_agent = user_agent

        needs_rate_limiter = (
            requests_per_second is not None
            or min_delay is not None
            or jitter > 0
            or respect_robots_txt
        )
        self.rate_limiter = (
            RateLimiter(
                requests_per_second=requests_per_second,
                min_delay=min_delay,
                jitter=jitter,
                per_domain=rate_limit_per_domain,
            )
            if needs_rate_limiter
            else None
        )

        self.robots_parser = (
            RobotsParser(user_agent=self._primary_user_agent)
            if respect_robots_txt
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
        self._total_fetch_time: float = 0.0
        self._fetch_count: int = 0
        self._blocked_by_robots_count: int = 0

        self._validate_params()

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(
            connect=5,
            sock_read=self.timeout_seconds,
        )

        self.session = aiohttp.ClientSession(timeout=timeout)

        if self.robots_parser is not None:
            self.robots_parser.set_session(self.session)

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
        self._total_fetch_time = 0.0
        self._fetch_count = 0
        self._blocked_by_robots_count = 0

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
            return self.parser.empty_result(
                url=url,
                parse_error=f"Fetch failed: {fetch_result['error'] or 'Unknown fetch error'}",
            )

        content = fetch_result["content"]

        if not isinstance(content, str):
            return self.parser.empty_result(
                url=url, parse_error="Fetch content is not a string"
            )

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

        avg_latency = (
            self._total_fetch_time / self._fetch_count if self._fetch_count > 0 else 0.0
        )

        return {
            "processed_pages": len(self.processed_urls),
            "queued": self._queued_count,
            "errors": len(self.failed_urls),
            "active_tasks": self.semaphore_manager.get_active_tasks_count(),
            "pages_per_second": pages_per_second,
            "avg_latency_seconds": avg_latency,
            "blocked_by_robots": self._blocked_by_robots_count,
        }

    async def fetch_url(self, url: str) -> dict[str, Any]:
        if self.session is None:
            raise RuntimeError("Session is not initialized")

        if self.robots_parser is not None:
            await self.robots_parser.fetch_robots(url)

            if not self.robots_parser.can_fetch(url):
                logger.info("Blocked by robots.txt: %s", url)
                self._blocked_by_robots_count += 1
                return {
                    "url": url,
                    "success": False,
                    "status": None,
                    "content": None,
                    "error": "Blocked by robots.txt",
                }

            crawl_delay = self.robots_parser.get_crawl_delay(url)
            if crawl_delay > 0:
                assert self.rate_limiter is not None  # guaranteed by needs_rate_limiter
                self.rate_limiter.update_domain_delay(url, crawl_delay)

        if self.rate_limiter is not None:
            await self.rate_limiter.acquire(url)

        async with self.semaphore_manager.acquire(url):
            result: dict[str, Any] = {}

            for attempt in range(self.max_retries + 1):
                result = await self._do_http_fetch(url)

                if result["success"]:
                    return result

                if not self._is_retryable(result) or attempt == self.max_retries:
                    return result

                delay = self.backoff_base * (2**attempt)
                logger.warning(
                    "Retry %d/%d for %s in %.1fs",
                    attempt + 1,
                    self.max_retries,
                    url,
                    delay,
                )
                await asyncio.sleep(delay)

            return result

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

    async def _do_http_fetch(self, url: str) -> dict[str, Any]:
        assert self.session is not None
        logger.info("Start fetching: %s", url)

        _start = time.perf_counter()
        try:
            headers = {"User-Agent": self._get_user_agent()}
            async with self.session.get(url, headers=headers) as response:
                response.raise_for_status()

                content = await response.text()

                logger.info("Success: %s | status=%s", url, response.status)

                return {
                    "url": url,
                    "success": True,
                    "status": response.status,
                    "content": content,
                    "error": None,
                }

        except asyncio.TimeoutError as error:
            logger.warning("Timeout error: %s", url)

            return {
                "url": url,
                "success": False,
                "status": None,
                "content": None,
                "error": str(error),
            }

        except aiohttp.ClientResponseError as error:
            logger.warning("HTTP error: %s | status=%s", url, error.status)

            return {
                "url": url,
                "success": False,
                "status": error.status,
                "content": None,
                "error": str(error),
            }

        except aiohttp.ClientError as error:
            logger.warning("Network error: %s | %s", url, error)

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

        finally:
            self._total_fetch_time += time.perf_counter() - _start
            self._fetch_count += 1

    def _is_retryable(self, result: dict[str, Any]) -> bool:
        status = result.get("status")
        if status is not None:
            return status >= 500
        return True

    def _validate_params(self) -> None:
        if self.max_concurrent <= 0:
            raise ValueError(
                f"max_concurrent must be positive, got {self.max_concurrent}"
            )
        if self.max_retries < 0:
            raise ValueError(
                f"max_retries must be non-negative, got {self.max_retries}"
            )
        if self.backoff_base <= 0:
            raise ValueError(f"backoff_base must be positive, got {self.backoff_base}")
        if isinstance(self.user_agent, list) and not self.user_agent:
            raise ValueError("user_agent list must not be empty")

    def _get_user_agent(self) -> str:
        if isinstance(self.user_agent, list):
            return random.choice(self.user_agent)
        return self.user_agent

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
