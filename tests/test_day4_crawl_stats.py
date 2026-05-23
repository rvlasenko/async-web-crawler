import pytest
from aiohttp import web

from crawler.async_crawler import AsyncCrawler

ROBOTS_BLOCK_PRIVATE = """\
User-agent: *
Disallow: /private/
"""


async def create_test_server(unused_tcp_port: int, robots_txt: str | None = None):
    async def robots_handler(request: web.Request) -> web.Response:
        return web.Response(text=robots_txt or "", content_type="text/plain")

    async def page_handler(request: web.Request) -> web.Response:
        return web.Response(
            text="<html><body>ok</body></html>", content_type="text/html"
        )

    app = web.Application()
    if robots_txt is not None:
        app.router.add_get("/robots.txt", robots_handler)
    app.router.add_get("/{path:.*}", page_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", unused_tcp_port)
    await site.start()

    return runner, f"http://localhost:{unused_tcp_port}"


# ---------------------------------------------------------------------------
# avg_latency_seconds
# ---------------------------------------------------------------------------


def test_avg_latency_zero_before_fetch() -> None:
    crawler = AsyncCrawler()
    stats = crawler.get_crawl_stats()
    assert stats["avg_latency_seconds"] == 0.0


@pytest.mark.asyncio
async def test_avg_latency_positive_after_fetch(unused_tcp_port: int) -> None:
    runner, base_url = await create_test_server(unused_tcp_port)

    try:
        async with AsyncCrawler() as crawler:
            await crawler.fetch_url(f"{base_url}/page")
            stats = crawler.get_crawl_stats()

        assert stats["avg_latency_seconds"] > 0
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_avg_latency_counted_for_failed_requests(unused_tcp_port: int) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=404, text="not found")

    app = web.Application()
    app.router.add_get("/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", unused_tcp_port)
    await site.start()

    try:
        async with AsyncCrawler() as crawler:
            await crawler.fetch_url(f"http://localhost:{unused_tcp_port}/page")
            stats = crawler.get_crawl_stats()

        assert stats["avg_latency_seconds"] > 0
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# blocked_by_robots
# ---------------------------------------------------------------------------


def test_blocked_by_robots_zero_initially() -> None:
    crawler = AsyncCrawler()
    stats = crawler.get_crawl_stats()
    assert stats["blocked_by_robots"] == 0


@pytest.mark.asyncio
async def test_blocked_by_robots_count(unused_tcp_port: int) -> None:
    runner, base_url = await create_test_server(
        unused_tcp_port, robots_txt=ROBOTS_BLOCK_PRIVATE
    )

    try:
        async with AsyncCrawler(respect_robots_txt=True) as crawler:
            await crawler.fetch_url(f"{base_url}/private/page")
            stats = crawler.get_crawl_stats()

        assert stats["blocked_by_robots"] == 1
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_blocked_by_robots_not_mixed_with_http_errors(
    unused_tcp_port: int,
) -> None:
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=500, text="error")

    app = web.Application()
    app.router.add_get("/{path:.*}", handler)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", unused_tcp_port)
    await site.start()

    try:
        async with AsyncCrawler() as crawler:
            await crawler.fetch_url(f"http://localhost:{unused_tcp_port}/page")
            stats = crawler.get_crawl_stats()

        assert stats["blocked_by_robots"] == 0
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_stats_reset_on_new_crawl(unused_tcp_port: int) -> None:
    robots_txt = ROBOTS_BLOCK_PRIVATE

    async def robots_handler(request: web.Request) -> web.Response:
        return web.Response(text=robots_txt, content_type="text/plain")

    async def index_handler(request: web.Request) -> web.Response:
        return web.Response(
            text='<html><body><a href="/private/page">x</a></body></html>',
            content_type="text/html",
        )

    async def page_handler(request: web.Request) -> web.Response:
        return web.Response(
            text="<html><body>ok</body></html>", content_type="text/html"
        )

    app = web.Application()
    app.router.add_get("/robots.txt", robots_handler)
    app.router.add_get("/", index_handler)
    app.router.add_get("/{path:.*}", page_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", unused_tcp_port)
    await site.start()

    base_url = f"http://localhost:{unused_tcp_port}"

    try:
        async with AsyncCrawler(respect_robots_txt=True) as crawler:
            await crawler.crawl(start_urls=[f"{base_url}/"], max_pages=10)
            assert crawler.get_crawl_stats()["blocked_by_robots"] >= 1

            await crawler.crawl(start_urls=[f"{base_url}/page"], max_pages=1)
            assert crawler.get_crawl_stats()["blocked_by_robots"] == 0
    finally:
        await runner.cleanup()
