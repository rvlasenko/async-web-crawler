import time
from unittest.mock import AsyncMock

import pytest
from aiohttp import web

from crawler.async_crawler import AsyncCrawler

FAST_RPS = 10.0
FAST_INTERVAL = 1.0 / FAST_RPS
TOLERANCE = 0.01  # 10ms


async def create_test_server(unused_tcp_port: int):
    async def handler(request: web.Request) -> web.Response:
        return web.Response(
            text="<html><body>ok</body></html>", content_type="text/html"
        )

    app = web.Application()
    app.router.add_get("/{path:.*}", handler)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "localhost", unused_tcp_port)
    await site.start()

    return runner, f"http://localhost:{unused_tcp_port}"


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawler_without_rate_limiter(unused_tcp_port: int) -> None:
    runner, base_url = await create_test_server(unused_tcp_port)
    try:
        async with AsyncCrawler() as crawler:
            result = await crawler.fetch_url(f"{base_url}/page")

        assert result["success"] is True
        assert crawler.rate_limiter is None
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Rate limiting is applied
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_global_rate_limiter_slows_requests(unused_tcp_port: int) -> None:
    runner, base_url = await create_test_server(unused_tcp_port)
    urls = [f"{base_url}/a", f"{base_url}/b", f"{base_url}/c"]

    try:
        async with AsyncCrawler(
            requests_per_second=FAST_RPS,
            rate_limit_per_domain=False,
        ) as crawler:
            start = time.monotonic()
            await crawler.fetch_urls(urls)
            elapsed = time.monotonic() - start

        # First call is free, 2nd and 3rd each wait ~100ms → total ≥ 180ms
        assert elapsed >= 2 * FAST_INTERVAL - TOLERANCE
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_per_domain_rate_limiter_slows_same_domain(unused_tcp_port: int) -> None:
    runner, base_url = await create_test_server(unused_tcp_port)
    urls = [f"{base_url}/x", f"{base_url}/y", f"{base_url}/z"]

    try:
        async with AsyncCrawler(
            requests_per_second=FAST_RPS,
            rate_limit_per_domain=True,
        ) as crawler:
            start = time.monotonic()
            await crawler.fetch_urls(urls)
            elapsed = time.monotonic() - start

        # All URLs resolve to the same localhost domain → same bucket → same delays
        assert elapsed >= 2 * FAST_INTERVAL - TOLERANCE
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Per-domain isolation: different domains do not block each other
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_per_domain_different_domains_do_not_block_each_other(
    unused_tcp_port: int,
    unused_tcp_port_factory,
) -> None:
    port_b = unused_tcp_port_factory()
    runner_a, base_url_a = await create_test_server(unused_tcp_port)
    runner_b, base_url_b = await create_test_server(port_b)

    # base_url_a → "localhost:PORT_A", base_url_b → "localhost:PORT_B" — different keys

    try:
        async with AsyncCrawler(
            requests_per_second=FAST_RPS,
            rate_limit_per_domain=True,
        ) as crawler:
            # Fill the bucket for domain A
            await crawler.fetch_url(f"{base_url_a}/first")

            # Request to domain B must not wait for domain A's cooldown
            start = time.monotonic()
            await crawler.fetch_url(f"{base_url_b}/first")
            elapsed = time.monotonic() - start

        assert elapsed < 0.05
    finally:
        await runner_a.cleanup()
        await runner_b.cleanup()


# ---------------------------------------------------------------------------
# acquire is called for every request
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rate_limiter_acquire_called_per_request(unused_tcp_port: int) -> None:
    runner, base_url = await create_test_server(unused_tcp_port)
    urls = [f"{base_url}/p1", f"{base_url}/p2", f"{base_url}/p3"]

    try:
        async with AsyncCrawler(requests_per_second=100.0) as crawler:
            assert crawler.rate_limiter is not None
            crawler.rate_limiter.acquire = AsyncMock()
            await crawler.fetch_urls(urls)

        assert crawler.rate_limiter.acquire.call_count == 3
        called_urls = {
            call.args[0] for call in crawler.rate_limiter.acquire.call_args_list
        }
        assert called_urls == set(urls)
    finally:
        await runner.cleanup()
