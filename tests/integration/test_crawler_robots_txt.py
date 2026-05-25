from unittest.mock import AsyncMock, patch

import pytest
from aiohttp import web

from crawler.async_crawler import AsyncCrawler
from crawler.robots_parser import RobotsParser

ROBOTS_WITH_DISALLOW = """\
User-agent: *
Disallow: /private/
"""

ROBOTS_WITH_DELAY = """\
User-agent: *
Crawl-delay: 2
"""

ROBOTS_EMPTY = """\
User-agent: *
"""


async def create_test_server(unused_tcp_port: int, robots_txt: str) -> tuple:
    async def robots_handler(request: web.Request) -> web.Response:
        return web.Response(text=robots_txt, content_type="text/plain")

    async def page_handler(request: web.Request) -> web.Response:
        return web.Response(
            text="<html><body>ok</body></html>",
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/robots.txt", robots_handler)
    app.router.add_get("/{path:.*}", page_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "localhost", unused_tcp_port)
    await site.start()

    return runner, f"http://localhost:{unused_tcp_port}"


# ---------------------------------------------------------------------------
# Backward compatibility
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawler_without_robots_check(unused_tcp_port: int) -> None:
    runner, base_url = await create_test_server(unused_tcp_port, ROBOTS_WITH_DISALLOW)

    try:
        async with AsyncCrawler() as crawler:
            assert crawler.robots_parser is None
            result = await crawler.fetch_url(f"{base_url}/private/page")

        assert result["success"] is True
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Blocked URLs
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_disallowed_url_returns_blocked(unused_tcp_port: int) -> None:
    runner, base_url = await create_test_server(unused_tcp_port, ROBOTS_WITH_DISALLOW)

    try:
        async with AsyncCrawler(respect_robots_txt=True) as crawler:
            result = await crawler.fetch_url(f"{base_url}/private/page")

        assert result["success"] is False
        assert result["error"] == "Blocked by robots.txt"
        assert result["status"] is None
        assert result["content"] is None
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_allowed_url_fetched_normally(unused_tcp_port: int) -> None:
    runner, base_url = await create_test_server(unused_tcp_port, ROBOTS_WITH_DISALLOW)

    try:
        async with AsyncCrawler(respect_robots_txt=True) as crawler:
            result = await crawler.fetch_url(f"{base_url}/public/page")

        assert result["success"] is True
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_blocked_url_is_logged(caplog, unused_tcp_port: int) -> None:
    runner, base_url = await create_test_server(unused_tcp_port, ROBOTS_WITH_DISALLOW)
    blocked_url = f"{base_url}/private/page"

    try:
        caplog.set_level("INFO", logger="crawler.async_crawler")

        async with AsyncCrawler(respect_robots_txt=True) as crawler:
            await crawler.fetch_url(blocked_url)

        assert any(
            "Blocked by robots.txt" in record.message and blocked_url in record.message
            for record in caplog.records
        )
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Crawl-delay
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_delay_applied(unused_tcp_port: int) -> None:
    """crawl_delay from robots.txt is registered in the rate_limiter for that domain.

    The delay is enforced as a minimum interval between requests (not a
    fixed sleep before every request), so on the *second* call to the same
    domain asyncio.sleep is called with approximately crawl_delay seconds.
    """
    runner, base_url = await create_test_server(unused_tcp_port, ROBOTS_WITH_DELAY)

    try:
        async with AsyncCrawler(respect_robots_txt=True) as crawler:
            await crawler.fetch_url(f"{base_url}/page1")

            assert crawler.rate_limiter is not None
            assert any(
                v == pytest.approx(2.0)
                for v in crawler.rate_limiter._domain_delays.values()
            )

            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await crawler.fetch_url(f"{base_url}/page2")

        sleep_args = [call.args[0] for call in mock_sleep.await_args_list]
        assert any(arg >= 1.8 for arg in sleep_args)
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_no_crawl_delay_when_not_in_robots_txt(unused_tcp_port: int) -> None:
    runner, base_url = await create_test_server(unused_tcp_port, ROBOTS_EMPTY)

    try:
        async with AsyncCrawler(respect_robots_txt=True) as crawler:
            with patch("asyncio.sleep", new_callable=AsyncMock) as mock_sleep:
                await crawler.fetch_url(f"{base_url}/page")

        mock_sleep.assert_not_awaited()
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Integration with crawl()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_session_used_instead_of_direct_attribute_access(
    unused_tcp_port: int,
) -> None:
    """AsyncCrawler must call robots_parser.set_session() rather than assigning
    _session directly — this preserves encapsulation of RobotsParser internals."""
    runner, base_url = await create_test_server(unused_tcp_port, ROBOTS_EMPTY)

    try:
        async with AsyncCrawler(respect_robots_txt=True) as crawler:
            assert crawler.robots_parser is not None
            assert crawler.robots_parser._session is crawler.session
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_crawl_delay_not_doubled_with_explicit_rate_limiter(
    unused_tcp_port: int,
) -> None:
    """When both min_delay and robots Crawl-delay are set, the effective per-domain
    delay must be max(min_delay, crawl_delay) — not the sum of the two."""
    runner, base_url = await create_test_server(unused_tcp_port, ROBOTS_WITH_DELAY)

    try:
        # min_delay=1.0, Crawl-delay: 2 → effective must be 2.0, not 3.0
        async with AsyncCrawler(respect_robots_txt=True, min_delay=1.0) as crawler:
            await crawler.fetch_url(f"{base_url}/page")

            domain_delays = list(crawler.rate_limiter._domain_delays.values())
            assert domain_delays == [pytest.approx(2.0)]
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_crawl_skips_robots_blocked_urls(unused_tcp_port: int) -> None:
    robots_txt = """\
User-agent: *
Disallow: /private/
"""

    async def robots_handler(request: web.Request) -> web.Response:
        return web.Response(text=robots_txt, content_type="text/plain")

    async def index_handler(request: web.Request) -> web.Response:
        return web.Response(
            text="""
            <html><body>
                <a href="/public/page">Public</a>
                <a href="/private/page">Private</a>
            </body></html>
            """,
            content_type="text/html",
        )

    async def page_handler(request: web.Request) -> web.Response:
        return web.Response(
            text="<html><body>ok</body></html>",
            content_type="text/html",
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
            results = await crawler.crawl(
                start_urls=[f"{base_url}/"],
                max_pages=10,
            )

        assert f"{base_url}/" in results
        assert f"{base_url}/public/page" in results
        assert f"{base_url}/private/page" not in results
        assert f"{base_url}/private/page" in crawler.failed_urls
    finally:
        await runner.cleanup()
