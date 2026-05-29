"""Integration tests that verify the four fixes applied in the day-7 review.

All tests use an in-process aiohttp server; no real network traffic.

Fix 1 — RetryStrategy wired into AdvancedCrawler via CrawlerConfig.
Fix 2 — HTTP status code preserved in failed_url_statuses / CrawlerStats.
Fix 3 — rate_limiter.acquire called once per HTTP attempt (including retries).
Fix 4 — parse_html offloaded to executor so it does not block the event loop.
"""

import asyncio
import threading
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web

from crawler.async_crawler import AsyncCrawler
from crawler.html_parser import HTMLParser
from crawler.retry_strategy import RetryStrategy


# ---------------------------------------------------------------------------
# Shared test-server helpers
# ---------------------------------------------------------------------------


def _flaky_app(fail_statuses: list[int]) -> web.Application:
    """Return an app that emits fail_statuses in order, then 200 with HTML."""
    responses: list[int] = list(fail_statuses)

    async def handler(request: web.Request) -> web.Response:
        if responses:
            status = responses.pop(0)
            return web.Response(status=status, text=f"error {status}")
        return web.Response(
            status=200,
            text="<html><body>ok</body></html>",
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/{path:.*}", handler)
    return app


async def _start(port: int, app: web.Application) -> web.AppRunner:
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "localhost", port).start()
    return runner


# ---------------------------------------------------------------------------
# Fix 1: AsyncCrawler retries on transient errors (503, 500)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_strategy_recovers_after_transient_503(
    unused_tcp_port: int,
) -> None:
    """URL that returns 503 twice then 200 must end up in processed_urls, not failed."""
    runner = await _start(unused_tcp_port, _flaky_app([503, 503]))
    base = f"http://localhost:{unused_tcp_port}"
    try:
        async with AsyncCrawler(
            retry_strategy=RetryStrategy(
                max_retries=3, backoff_factor=1.0, base_delay=0.01
            )
        ) as crawler:
            result = await crawler.fetch_and_parse(f"{base}/page")

        assert result["fetch_error"] is None
        assert result["status_code"] == 200
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_retry_exhausted_records_failure(unused_tcp_port: int) -> None:
    """URL that keeps returning 503 must be recorded as failed after retries exhausted."""
    runner = await _start(unused_tcp_port, _flaky_app([503, 503, 503, 503]))
    base = f"http://localhost:{unused_tcp_port}"
    try:
        async with AsyncCrawler(
            retry_strategy=RetryStrategy(
                max_retries=2, backoff_factor=1.0, base_delay=0.01
            )
        ) as crawler:
            results = await crawler.crawl(
                start_urls=[f"{base}/page"], max_pages=10
            )

        assert f"{base}/page" not in results
        assert f"{base}/page" in crawler.failed_urls
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Fix 2: HTTP status code preserved in failed_url_statuses and crawl stats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_url_statuses_records_http_status(unused_tcp_port: int) -> None:
    """A 404 response must appear in failed_url_statuses with status 404."""
    app = web.Application()
    app.router.add_get("/{path:.*}", lambda r: web.Response(status=404, text="nope"))
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "localhost", unused_tcp_port).start()

    url = f"http://localhost:{unused_tcp_port}/page"
    try:
        async with AsyncCrawler() as crawler:
            await crawler.crawl(start_urls=[url], max_pages=5)

        assert url in crawler.failed_urls
        assert crawler.failed_url_statuses.get(url) == 404
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_fetch_and_parse_preserves_status_on_http_error(
    unused_tcp_port: int,
) -> None:
    """fetch_and_parse must include status_code in result even when the request fails."""
    app = web.Application()
    app.router.add_get(
        "/{path:.*}", lambda r: web.Response(status=503, text="down")
    )
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "localhost", unused_tcp_port).start()

    try:
        async with AsyncCrawler() as crawler:
            result = await crawler.fetch_and_parse(
                f"http://localhost:{unused_tcp_port}/page"
            )

        assert result["fetch_error"] is not None
        assert result["status_code"] == 503
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Fix 3: rate_limiter.acquire called once per HTTP attempt (including retries)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limiter_acquire_called_per_retry_attempt(
    unused_tcp_port: int,
) -> None:
    """acquire must be called for every HTTP attempt, not just the first."""
    runner = await _start(unused_tcp_port, _flaky_app([503, 503]))
    base = f"http://localhost:{unused_tcp_port}"

    try:
        async with AsyncCrawler(
            requests_per_second=1000.0,
            retry_strategy=RetryStrategy(
                max_retries=3, backoff_factor=1.0, base_delay=0.01
            ),
        ) as crawler:
            assert crawler.rate_limiter is not None
            crawler.rate_limiter.acquire = AsyncMock()

            await crawler.fetch_url(f"{base}/page")

        # 2 failures + 1 success = 3 HTTP attempts → 3 acquire calls
        assert crawler.rate_limiter.acquire.call_count == 3
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_rate_limiter_acquire_called_once_when_no_retry(
    unused_tcp_port: int,
) -> None:
    """Without a retry_strategy, acquire is called exactly once per URL."""
    runner = await _start(unused_tcp_port, _flaky_app([]))
    base = f"http://localhost:{unused_tcp_port}"

    try:
        async with AsyncCrawler(requests_per_second=1000.0) as crawler:
            assert crawler.rate_limiter is not None
            crawler.rate_limiter.acquire = AsyncMock()

            await crawler.fetch_url(f"{base}/page")

        assert crawler.rate_limiter.acquire.call_count == 1
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Fix 4: parse_html offloaded to thread executor
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_parse_html_runs_in_worker_thread(unused_tcp_port: int) -> None:
    """parse_html must execute in a non-event-loop thread via run_in_executor."""
    app = web.Application()
    app.router.add_get(
        "/{path:.*}",
        lambda r: web.Response(
            status=200,
            text="<html><body>hello</body></html>",
            content_type="text/html",
        ),
    )
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "localhost", unused_tcp_port).start()

    main_thread = threading.current_thread()
    parse_threads: list[threading.Thread] = []
    original_parse = HTMLParser.parse_html

    def tracking_parse(self, html: str, url: str, same_domain_only: bool = False):
        parse_threads.append(threading.current_thread())
        return original_parse(self, html, url, same_domain_only)

    try:
        with patch.object(HTMLParser, "parse_html", tracking_parse):
            async with AsyncCrawler() as crawler:
                await crawler.fetch_and_parse(
                    f"http://localhost:{unused_tcp_port}/page"
                )

        assert len(parse_threads) == 1
        assert parse_threads[0] is not main_thread, (
            "parse_html must run in a worker thread, not the event-loop thread"
        )
    finally:
        await runner.cleanup()
