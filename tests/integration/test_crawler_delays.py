import asyncio
from unittest.mock import patch

import pytest
from aiohttp import web

from crawler.async_crawler import AsyncCrawler
from crawler.errors import TransientError
from crawler.retry_strategy import RetryStrategy


async def create_test_server(unused_tcp_port: int, handler):
    app = web.Application()
    app.router.add_get("/{path:.*}", handler)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "localhost", unused_tcp_port)
    await site.start()

    return runner, f"http://localhost:{unused_tcp_port}"


# ---------------------------------------------------------------------------
# RateLimiter creation rules
# ---------------------------------------------------------------------------


def test_no_delay_params_no_rate_limiter() -> None:
    crawler = AsyncCrawler()
    assert crawler.rate_limiter is None


def test_requests_per_second_creates_rate_limiter() -> None:
    crawler = AsyncCrawler(requests_per_second=5.0)
    assert crawler.rate_limiter is not None


def test_min_delay_creates_rate_limiter() -> None:
    crawler = AsyncCrawler(min_delay=0.5)
    assert crawler.rate_limiter is not None
    assert crawler.rate_limiter._min_interval == pytest.approx(0.5)


def test_jitter_alone_creates_rate_limiter() -> None:
    crawler = AsyncCrawler(jitter=0.1)
    assert crawler.rate_limiter is not None
    assert crawler.rate_limiter.jitter == pytest.approx(0.1)


# ---------------------------------------------------------------------------
# Exponential backoff — retry on 5xx
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_on_5xx_eventually_succeeds(unused_tcp_port: int) -> None:
    call_count = {"n": 0}

    async def handler(request: web.Request) -> web.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            return web.Response(status=500, text="error")
        return web.Response(
            text="<html><body>ok</body></html>", content_type="text/html"
        )

    runner, base_url = await create_test_server(unused_tcp_port, handler)

    try:
        async with AsyncCrawler(
            retry_strategy=RetryStrategy(max_retries=1, base_delay=0)
        ) as crawler:
            result = await crawler.fetch_url(f"{base_url}/page")

        assert result["success"] is True
        assert call_count["n"] == 2
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_max_retries_exhausted_returns_last_error(unused_tcp_port: int) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=500, text="error")

    runner, base_url = await create_test_server(unused_tcp_port, handler)

    try:
        async with AsyncCrawler(
            retry_strategy=RetryStrategy(max_retries=2, base_delay=0)
        ) as crawler:
            result = await crawler.fetch_url(f"{base_url}/page")

        assert result["success"] is False
        assert result["status"] == 500
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_no_retry_on_4xx(unused_tcp_port: int) -> None:
    call_count = {"n": 0}

    async def handler(request: web.Request) -> web.Response:
        call_count["n"] += 1
        return web.Response(status=404, text="not found")

    runner, base_url = await create_test_server(unused_tcp_port, handler)

    try:
        async with AsyncCrawler(
            retry_strategy=RetryStrategy(max_retries=3, base_delay=0)
        ) as crawler:
            result = await crawler.fetch_url(f"{base_url}/page")

        assert result["success"] is False
        assert result["status"] == 404
        assert call_count["n"] == 1
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_backoff_sleep_called_with_increasing_delays(
    unused_tcp_port: int,
) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=500, text="error")

    runner, base_url = await create_test_server(unused_tcp_port, handler)

    try:
        with patch("crawler.retry_strategy.asyncio.sleep") as mock_sleep:
            async with AsyncCrawler(
                retry_strategy=RetryStrategy(
                    max_retries=3, base_delay=1.0, backoff_factor=2.0
                )
            ) as crawler:
                result = await crawler.fetch_url(f"{base_url}/page")

        assert result["success"] is False
        sleep_args = [c.args[0] for c in mock_sleep.call_args_list]
        assert sleep_args == [1.0, 2.0, 4.0]
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_retry_on_timeout_eventually_succeeds(unused_tcp_port: int) -> None:
    call_count = {"n": 0}

    async def handler(request: web.Request) -> web.Response:
        call_count["n"] += 1
        if call_count["n"] == 1:
            await asyncio.sleep(0.5)
        return web.Response(
            text="<html><body>ok</body></html>", content_type="text/html"
        )

    runner, base_url = await create_test_server(unused_tcp_port, handler)

    try:
        async with AsyncCrawler(
            timeout_seconds=0.05,
            retry_strategy=RetryStrategy(max_retries=1, base_delay=0),
        ) as crawler:
            result = await crawler.fetch_url(f"{base_url}/page")

        assert result["success"] is True
        assert call_count["n"] == 2
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_no_retry_when_no_retry_strategy(unused_tcp_port: int) -> None:
    call_count = {"n": 0}

    async def handler(request: web.Request) -> web.Response:
        call_count["n"] += 1
        return web.Response(status=500, text="error")

    runner, base_url = await create_test_server(unused_tcp_port, handler)

    try:
        async with AsyncCrawler() as crawler:
            result = await crawler.fetch_url(f"{base_url}/page")

        assert result["success"] is False
        assert call_count["n"] == 1
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Timeout params — validation
# ---------------------------------------------------------------------------


def test_connect_timeout_zero_raises() -> None:
    with pytest.raises(ValueError, match="connect_timeout"):
        AsyncCrawler(connect_timeout=0.0)


def test_connect_timeout_negative_raises() -> None:
    with pytest.raises(ValueError, match="connect_timeout"):
        AsyncCrawler(connect_timeout=-1.0)


def test_total_timeout_zero_raises() -> None:
    with pytest.raises(ValueError, match="total_timeout"):
        AsyncCrawler(total_timeout=0.0)


def test_total_timeout_none_is_valid() -> None:
    crawler = AsyncCrawler(total_timeout=None)
    assert crawler.total_timeout is None


def test_timeout_multiplier_below_one_raises() -> None:
    with pytest.raises(ValueError, match="timeout_multiplier"):
        AsyncCrawler(timeout_multiplier=0.9)


def test_timeout_multiplier_exactly_one_is_valid() -> None:
    crawler = AsyncCrawler(timeout_multiplier=1.0)
    assert crawler.timeout_multiplier == 1.0


# ---------------------------------------------------------------------------
# Timeout escalation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timeout_escalates_on_retry() -> None:
    captured: list[float | None] = []

    async def mock_fetch(
        self, url: str, read_timeout: float | None = None
    ) -> tuple[str, int, str]:
        captured.append(read_timeout)
        raise TransientError("always fail")

    with patch.object(AsyncCrawler, "_do_http_fetch", mock_fetch):
        async with AsyncCrawler(
            timeout_seconds=1.0,
            timeout_multiplier=2.0,
            retry_strategy=RetryStrategy(max_retries=2, base_delay=0),
        ) as crawler:
            result = await crawler.fetch_url("http://example.com/page")

    assert result["success"] is False
    assert captured == pytest.approx([1.0, 2.0, 4.0])


@pytest.mark.asyncio
async def test_timeout_multiplier_one_no_escalation() -> None:
    captured: list[float | None] = []
    call_n = 0

    async def mock_fetch(
        self, url: str, read_timeout: float | None = None
    ) -> tuple[str, int, str, str]:
        nonlocal call_n
        captured.append(read_timeout)
        call_n += 1
        if call_n < 3:
            raise TransientError("fail")
        return "content", 200, "http://example.com/page", "text/html"

    with patch.object(AsyncCrawler, "_do_http_fetch", mock_fetch):
        async with AsyncCrawler(
            timeout_seconds=5.0,
            timeout_multiplier=1.0,
            retry_strategy=RetryStrategy(max_retries=2, base_delay=0),
        ) as crawler:
            result = await crawler.fetch_url("http://example.com/page")

    assert result["success"] is True
    assert captured == pytest.approx([5.0, 5.0, 5.0])
