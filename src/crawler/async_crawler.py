import asyncio
import logging
import random
import time
from datetime import datetime, timezone
from typing import Any

import aiohttp

from crawler.crawler_queue import CrawlerQueue
from crawler.errors import CrawlerError, NetworkError, TransientError, classify_status_code
from crawler.html_parser import HTMLParser
from crawler.rate_limiter import RateLimiter
from crawler.retry_strategy import RetryStrategy
from crawler.robots_parser import RobotsParser
from crawler.semaphore_manager import SemaphoreManager
from crawler.storage.base import DataStorage

logger = logging.getLogger(__name__)


class AsyncCrawler:
    """Async breadth-first web crawler with concurrency control, rate limiting, and robots.txt support.

    Must be used as an async context manager so the underlying HTTP session is
    properly initialised and closed::

        async with AsyncCrawler(max_concurrent=10) as crawler:
            results = await crawler.crawl(["https://example.com"])

    Args:
        max_concurrent: Maximum simultaneous HTTP requests across all domains.
        timeout_seconds: Base socket-read timeout per request, in seconds. When
            ``timeout_multiplier > 1.0``, this value is scaled up on each retry.
        max_depth: Maximum link depth to follow from seed URLs. ``None`` means
            unlimited depth.
        requests_per_second: Target request rate. Activates the rate limiter.
            Mutually exclusive with ``min_delay``.
        min_delay: Minimum seconds between requests. Activates the rate limiter.
            Mutually exclusive with ``requests_per_second``.
        jitter: Maximum extra random seconds added to each inter-request delay.
            A non-zero value also activates the rate limiter even without a rate cap.
        rate_limit_per_domain: When ``True``, rate limiting is applied per domain.
            When ``False``, a single global bucket throttles all requests.
        respect_robots_txt: When ``True``, fetches robots.txt before visiting any
            page on a domain and skips URLs disallowed by it. Also applies any
            ``Crawl-delay`` directive from robots.txt.
        user_agent: ``User-Agent`` header sent with every request. Pass a list to
            rotate values randomly per request; the first element is used for
            robots.txt rule matching.
        retry_strategy: Optional ``RetryStrategy`` instance that controls automatic
            retries on failed requests. When ``None``, each URL is attempted exactly
            once with no retries.
        connect_timeout: Maximum seconds allowed to establish a TCP connection.
        total_timeout: Maximum seconds for the entire request lifecycle (connect +
            read). ``None`` means no total limit.
        timeout_multiplier: Multiplier applied to ``timeout_seconds`` on each retry.
            ``1.0`` disables escalation. Must be ``>= 1.0``. Requires
            ``retry_strategy`` to have any effect.
        per_domain_limit: Maximum concurrent requests to a single domain.
            Requests beyond this limit wait until a slot is free. Must be
            positive. For single-domain crawls the effective concurrency is
            ``min(max_concurrent, per_domain_limit)``.
    """

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
        retry_strategy: RetryStrategy | None = None,
        connect_timeout: float = 5.0,
        total_timeout: float | None = None,
        timeout_multiplier: float = 1.0,
        per_domain_limit: int = 2,
        storage: DataStorage | None = None,
    ):
        self.max_concurrent = max_concurrent
        self.per_domain_limit = per_domain_limit
        self.timeout_seconds = timeout_seconds
        self.max_depth = max_depth
        self.retry_strategy = retry_strategy
        self.connect_timeout = connect_timeout
        self.total_timeout = total_timeout
        self.timeout_multiplier = timeout_multiplier
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
            per_domain_limit=per_domain_limit,
        )

        self.session: aiohttp.ClientSession | None = None

        self.parser = HTMLParser()
        self.attempted_urls: set[str] = set()
        self.failed_urls: dict[str, str] = {}
        self.processed_urls: dict[str, dict[str, Any]] = {}
        self._crawl_started_at: float | None = None
        self._crawl_finished_at: float | None = None
        self._queued_count = 0
        self._total_fetch_time: float = 0.0
        self._fetch_count: int = 0
        self._blocked_by_robots_count: int = 0
        self.storage = storage

        self._validate_params()

    async def __aenter__(self):
        timeout = aiohttp.ClientTimeout(
            connect=self.connect_timeout,
            total=self.total_timeout,
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
        """Crawl pages starting from ``start_urls`` and return structured parse results.

        Resets all internal state on each call, so the same crawler instance can
        be reused across multiple crawl runs.

        Args:
            start_urls: Seed URLs to begin crawling from.
            max_pages: Stop after successfully processing this many pages.
            same_domain_only: When ``True``, only follow links whose domain matches
                the page they were discovered on.
            include_patterns: If set, only enqueue URLs that contain at least one
                of these substrings. Applied after ``exclude_patterns``.
            exclude_patterns: If set, skip URLs that contain any of these substrings.
                Applied before ``include_patterns``.
            show_progress: When ``True``, log crawl progress stats (pages, queue
                depth, errors, speed) after each batch via the module logger.

        Returns:
            Mapping of URL → parsed page data for every successfully processed page.
        """
        self.attempted_urls = set()
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
                self.attempted_urls.add(task.url)

            batch_results = await asyncio.gather(
                *[
                    self.fetch_and_parse(task.url, same_domain_only)
                    for task in batch_tasks
                ]
            )

            for task, parsed_data in zip(batch_tasks, batch_results):
                url = task.url

                fetch_error = parsed_data.get("fetch_error")
                parse_error = parsed_data["parse_errors"][0] if parsed_data["parse_errors"] else None
                error = fetch_error or parse_error
                if error:
                    self.failed_urls[url] = error
                    queue.mark_failed(url, error)
                    continue

                self.processed_urls[url] = parsed_data
                queue.mark_processed(url)

                if self.storage is not None:
                    try:
                        await self.storage.save(parsed_data)
                    except Exception:
                        # Storage errors must not stop the crawl — data stays in processed_urls.
                        logger.exception("Storage error for %s — crawl continues", url)

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
                fetch_error=fetch_result["error"] or "Unknown fetch error",
            )

        content = fetch_result["content"]

        if not isinstance(content, str):
            return self.parser.empty_result(
                url=url, fetch_error="Fetch content is not a string"
            )

        # Use the final URL (after any redirects) as base for link resolution.
        # Without this, relative links in redirected content are resolved against
        # the original URL's path, making cross-domain relative links appear to
        # belong to the original domain and bypassing same_domain_only filtering.
        final_url = fetch_result.get("final_url") or url

        parsed_data = self.parser.parse_html(
            html=content,
            url=final_url,
            same_domain_only=same_domain_only,
        )

        # Preserve the original requested URL as the result key so that
        # processed_urls and fetch_and_parse_urls stay consistent with
        # what the caller asked for.
        parsed_data["url"] = url
        parsed_data["status_code"] = fetch_result.get("status")
        parsed_data["content_type"] = fetch_result.get("content_type")
        parsed_data["crawled_at"] = datetime.now(tz=timezone.utc)

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
                    "final_url": None,
                }

            crawl_delay = self.robots_parser.get_crawl_delay(url)
            if crawl_delay > 0:
                if self.rate_limiter is None:
                    raise RuntimeError(
                        "robots.txt specifies Crawl-delay but rate_limiter is None; "
                        "this should not happen because respect_robots_txt=True implies "
                        "needs_rate_limiter=True"
                    )
                self.rate_limiter.update_domain_delay(url, crawl_delay)

        if self.rate_limiter is not None:
            await self.rate_limiter.acquire(url)

        async with self.semaphore_manager.acquire(url):
            try:
                if self.retry_strategy is not None:
                    _attempt = 0

                    async def _fetch() -> tuple[str, int, str, str]:
                        nonlocal _attempt
                        read_timeout = self.timeout_seconds * (
                            self.timeout_multiplier ** _attempt
                        )
                        _attempt += 1
                        return await self._do_http_fetch(url, read_timeout=read_timeout)

                    content, status, final_url, content_type = await self.retry_strategy.execute_with_retry(
                        _fetch, context=url
                    )
                else:
                    content, status, final_url, content_type = await self._do_http_fetch(url)

                return {
                    "url": url,
                    "success": True,
                    "status": status,
                    "content": content,
                    "content_type": content_type,
                    "error": None,
                    "final_url": final_url,
                }

            except CrawlerError as exc:
                logger.warning("Failed: %s | %s", url, exc)
                return {
                    "url": url,
                    "success": False,
                    "status": exc.status,
                    "content": None,
                    "error": str(exc),
                    "final_url": None,
                }

            except Exception as exc:
                logger.exception("Unexpected error fetching: %s", url)
                return {
                    "url": url,
                    "success": False,
                    "status": None,
                    "content": None,
                    "error": f"{type(exc).__name__}: {exc}",
                    "final_url": None,
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

    async def _do_http_fetch(
        self, url: str, read_timeout: float | None = None
    ) -> tuple[str, int, str, str]:
        """Perform a single HTTP GET and return (content, status, final_url, content_type).

        ``final_url`` is the URL of the last response after any redirects and
        may differ from ``url`` when the server issues a 301/302. Callers must
        use ``final_url`` as the base for relative-link resolution so that links
        extracted from redirected pages point to the correct domain and path.

        Raises CrawlerError subclasses on failure so that RetryStrategy can
        intercept and classify them — TransientError for retryable failures,
        PermanentError for terminal ones, NetworkError for connectivity issues.
        """
        assert self.session is not None
        logger.info("Start fetching: %s", url)

        _start = time.perf_counter()
        try:
            headers = {"User-Agent": self._get_user_agent()}
            per_req_timeout = aiohttp.ClientTimeout(
                connect=self.connect_timeout,
                total=self.total_timeout,
                sock_read=read_timeout if read_timeout is not None else self.timeout_seconds,
            )
            async with self.session.get(url, headers=headers, timeout=per_req_timeout) as response:
                if not response.ok:
                    error_class = classify_status_code(response.status)
                    raise error_class(
                        f"HTTP {response.status}: {url}", status=response.status
                    )

                content = await response.text()
                final_url = str(response.url)
                content_type = response.headers.get("Content-Type", "")
                logger.info("Success: %s | status=%s", url, response.status)
                return content, response.status, final_url, content_type

        except CrawlerError:
            raise

        except asyncio.TimeoutError:
            logger.warning("Timeout: %s", url)
            raise TransientError(f"Timeout: {url}")

        except aiohttp.ClientError as exc:
            logger.warning("Network error: %s | %s", url, exc)
            raise NetworkError(str(exc)) from exc

        except Exception:
            logger.exception("Unexpected error while fetching: %s", url)
            raise

        finally:
            self._total_fetch_time += time.perf_counter() - _start
            self._fetch_count += 1

    def _validate_params(self) -> None:
        if self.max_concurrent <= 0:
            raise ValueError(
                f"max_concurrent must be positive, got {self.max_concurrent}"
            )
        if isinstance(self.user_agent, list) and not self.user_agent:
            raise ValueError("user_agent list must not be empty")
        if self.connect_timeout <= 0:
            raise ValueError(f"connect_timeout must be positive, got {self.connect_timeout}")
        if self.total_timeout is not None and self.total_timeout <= 0:
            raise ValueError(f"total_timeout must be positive, got {self.total_timeout}")
        if self.timeout_multiplier < 1.0:
            raise ValueError(
                f"timeout_multiplier must be >= 1.0, got {self.timeout_multiplier}"
            )
        if self.per_domain_limit <= 0:
            raise ValueError(
                f"per_domain_limit must be positive, got {self.per_domain_limit}"
            )

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
