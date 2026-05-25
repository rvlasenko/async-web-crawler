import asyncio
import time

import pytest
from aiohttp import web

from crawler.async_crawler import AsyncCrawler


async def create_test_server(unused_tcp_port):
    async def ok_handler(request):
        return web.Response(text="Hello from test server", status=200)

    async def not_found_handler(request):
        return web.Response(text="Not found", status=404)

    async def slow_handler(request):
        await asyncio.sleep(1)
        return web.Response(text="Slow response", status=200)

    app = web.Application()

    app.router.add_get("/ok", ok_handler)
    app.router.add_get("/not-found", not_found_handler)
    app.router.add_get("/slow", slow_handler)

    runner = web.AppRunner(app)

    await runner.setup()

    port = unused_tcp_port

    site = web.TCPSite(runner, "localhost", port)

    await site.start()

    return runner, f"http://localhost:{port}"


@pytest.mark.asyncio
async def test_fetch_valid_url(unused_tcp_port):
    runner, base_url = await create_test_server(unused_tcp_port)

    try:
        async with AsyncCrawler() as crawler:
            result = await crawler.fetch_url(f"{base_url}/ok")

        assert result["success"] is True
        assert result["status"] == 200
        assert "Hello from test server" in result["content"]
        assert result["error"] is None

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_fetch_404_url(unused_tcp_port):
    runner, base_url = await create_test_server(unused_tcp_port)

    try:
        async with AsyncCrawler() as crawler:
            result = await crawler.fetch_url(f"{base_url}/not-found")

        assert result["success"] is False
        assert result["status"] == 404
        assert result["content"] is None
        assert result["error"] is not None

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_fetch_timeout(unused_tcp_port):
    runner, base_url = await create_test_server(unused_tcp_port)

    try:
        async with AsyncCrawler(
            timeout_seconds=0.1,
        ) as crawler:
            result = await crawler.fetch_url(f"{base_url}/slow")

        assert result["success"] is False
        assert result["content"] is None
        assert result["error"] is not None

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_parallel_faster_than_sequential(
    unused_tcp_port,
):
    runner, base_url = await create_test_server(unused_tcp_port)

    urls = [
        f"{base_url}/slow",
        f"{base_url}/slow",
        f"{base_url}/slow",
    ]

    try:
        async with AsyncCrawler(
            max_concurrent=3,
            timeout_seconds=5,
        ) as crawler:
            start = time.perf_counter()

            for url in urls:
                await crawler.fetch_url(url)

            sequential_time = time.perf_counter() - start

        async with AsyncCrawler(
            max_concurrent=3,
            timeout_seconds=5,
        ) as crawler:
            start = time.perf_counter()

            await crawler.fetch_urls(urls)

            parallel_time = time.perf_counter() - start

        assert parallel_time < sequential_time

    finally:
        await runner.cleanup()
