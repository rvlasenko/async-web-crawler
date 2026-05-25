import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web

from crawler.async_crawler import AsyncCrawler


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
        with patch("asyncio.sleep", new_callable=AsyncMock):
            async with AsyncCrawler(max_retries=1, backoff_base=0.001) as crawler:
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
        with patch("asyncio.sleep", new_callable=AsyncMock):
            async with AsyncCrawler(max_retries=2, backoff_base=0.001) as crawler:
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
        async with AsyncCrawler(max_retries=3) as crawler:
            result = await crawler.fetch_url(f"{base_url}/page")

        assert result["success"] is False
        assert result["status"] == 404
        assert call_count["n"] == 1
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_backoff_sleep_called_with_increasing_delays(unused_tcp_port: int) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=500, text="error")

    runner, base_url = await create_test_server(unused_tcp_port, handler)

    try:
        with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
            async with AsyncCrawler(max_retries=3, backoff_base=1.0) as crawler:
                result = await crawler.fetch_url(f"{base_url}/page")

        assert result["success"] is False
        sleep_args = [call.args[0] for call in mock_sleep.await_args_list]
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
            max_retries=1,
            backoff_base=0.001,
        ) as crawler:
            result = await crawler.fetch_url(f"{base_url}/page")

        assert result["success"] is True
        assert call_count["n"] == 2
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_no_retry_when_max_retries_zero(unused_tcp_port: int) -> None:
    call_count = {"n": 0}

    async def handler(request: web.Request) -> web.Response:
        call_count["n"] += 1
        return web.Response(status=500, text="error")

    runner, base_url = await create_test_server(unused_tcp_port, handler)

    try:
        async with AsyncCrawler(max_retries=0) as crawler:
            result = await crawler.fetch_url(f"{base_url}/page")

        assert result["success"] is False
        assert call_count["n"] == 1
    finally:
        await runner.cleanup()
