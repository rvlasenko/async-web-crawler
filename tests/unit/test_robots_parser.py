import pytest
from aiohttp import web

from crawler.robots_parser import RobotsParser

ROBOTS_TXT = """\
User-agent: *
Disallow: /private/
Disallow: /admin/
Crawl-delay: 2

Sitemap: http://example.com/sitemap.xml
"""

ROBOTS_TXT_NO_DELAY = """\
User-agent: *
Disallow: /private/
"""

ROBOTS_TXT_MULTI_AGENT = """\
User-agent: BadBot
Disallow: /

User-agent: *
Disallow: /private/
"""


async def create_robots_test_server(
    unused_tcp_port: int,
    robots_txt: str = ROBOTS_TXT,
    robots_status: int = 200,
):
    request_count = {"count": 0}

    async def robots_handler(request: web.Request) -> web.Response:
        request_count["count"] += 1
        return web.Response(
            text=robots_txt, content_type="text/plain", status=robots_status
        )

    app = web.Application()
    app.router.add_get("/robots.txt", robots_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, "localhost", unused_tcp_port)
    await site.start()

    return runner, f"http://localhost:{unused_tcp_port}", request_count


# ---------------------------------------------------------------------------
# Structural / init
# ---------------------------------------------------------------------------


def test_default_values() -> None:
    robots = RobotsParser()
    assert robots.user_agent == "*"
    assert robots._parsers == {}
    assert robots._results == {}
    assert robots._session is None


@pytest.mark.asyncio
async def test_context_manager_opens_closes_session() -> None:
    async with RobotsParser() as robots:
        assert robots._session is not None
        assert not robots._session.closed

    assert robots._session.closed


# ---------------------------------------------------------------------------
# fetch_robots
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_robots_success(unused_tcp_port: int) -> None:
    runner, base_url, _ = await create_robots_test_server(unused_tcp_port)

    try:
        async with RobotsParser() as robots:
            result = await robots.fetch_robots(base_url)

        assert result["url"] == f"http://localhost:{unused_tcp_port}/robots.txt"
        assert result["domain"] == f"localhost:{unused_tcp_port}"
        assert result["fetched"] is True
        assert result["status"] == 200
        assert result["crawl_delay"] == 2.0
        assert result["sitemaps"] == ["http://example.com/sitemap.xml"]
        assert result["fetch_error"] is None
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_fetch_robots_caches_result(unused_tcp_port: int) -> None:
    runner, base_url, request_count = await create_robots_test_server(unused_tcp_port)

    try:
        async with RobotsParser() as robots:
            result1 = await robots.fetch_robots(base_url)
            result2 = await robots.fetch_robots(base_url)

        assert result1 is result2
        assert request_count["count"] == 1
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_fetch_robots_404_returns_permissive(unused_tcp_port: int) -> None:
    runner, base_url, _ = await create_robots_test_server(
        unused_tcp_port,
        robots_status=404,
    )

    try:
        async with RobotsParser() as robots:
            result = await robots.fetch_robots(base_url)

        assert result["fetched"] is True
        assert result["status"] == 404
        assert result["crawl_delay"] is None
        assert result["sitemaps"] == []
        assert result["fetch_error"] is None

        domain = f"localhost:{unused_tcp_port}"
        assert domain in robots._parsers
        assert robots._parsers[domain] is None
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_fetch_robots_network_error_is_tolerated(unused_tcp_port: int) -> None:
    async with RobotsParser() as robots:
        result = await robots.fetch_robots(f"http://localhost:{unused_tcp_port}")

    domain = f"localhost:{unused_tcp_port}"
    assert result["fetched"] is False
    assert result["fetch_error"] is not None
    assert result["status"] is None
    assert domain in robots._parsers
    assert robots._parsers[domain] is None


# ---------------------------------------------------------------------------
# can_fetch
# ---------------------------------------------------------------------------


def test_can_fetch_unknown_domain_returns_true() -> None:
    robots = RobotsParser()
    assert robots.can_fetch("https://example.com/anything") is True


@pytest.mark.asyncio
async def test_can_fetch_no_robots_txt_returns_true(unused_tcp_port: int) -> None:
    runner, base_url, _ = await create_robots_test_server(
        unused_tcp_port,
        robots_status=404,
    )

    try:
        async with RobotsParser() as robots:
            await robots.fetch_robots(base_url)
            assert robots.can_fetch(f"{base_url}/private/anything") is True
            assert robots.can_fetch(f"{base_url}/admin/secret") is True
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_can_fetch_disallowed_path_returns_false(unused_tcp_port: int) -> None:
    runner, base_url, _ = await create_robots_test_server(unused_tcp_port)

    try:
        async with RobotsParser() as robots:
            await robots.fetch_robots(base_url)
            assert robots.can_fetch(f"{base_url}/private/page") is False
            assert robots.can_fetch(f"{base_url}/admin/panel") is False
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_can_fetch_allowed_path_returns_true(unused_tcp_port: int) -> None:
    runner, base_url, _ = await create_robots_test_server(unused_tcp_port)

    try:
        async with RobotsParser() as robots:
            await robots.fetch_robots(base_url)
            assert robots.can_fetch(f"{base_url}/public/page") is True
            assert robots.can_fetch(f"{base_url}/") is True
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_can_fetch_respects_user_agent(unused_tcp_port: int) -> None:
    runner, base_url, _ = await create_robots_test_server(
        unused_tcp_port,
        robots_txt=ROBOTS_TXT_MULTI_AGENT,
    )

    try:
        async with RobotsParser() as robots:
            await robots.fetch_robots(base_url)

            # BadBot is blocked from everything
            assert (
                robots.can_fetch(f"{base_url}/public/page", user_agent="BadBot")
                is False
            )

            # GoodBot falls back to * rules — only /private/ blocked
            assert (
                robots.can_fetch(f"{base_url}/public/page", user_agent="GoodBot")
                is True
            )
            assert (
                robots.can_fetch(f"{base_url}/private/page", user_agent="GoodBot")
                is False
            )
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# get_crawl_delay
# ---------------------------------------------------------------------------


def test_get_crawl_delay_unknown_domain_returns_zero() -> None:
    robots = RobotsParser()
    assert robots.get_crawl_delay("https://example.com/") == 0.0


@pytest.mark.asyncio
async def test_get_crawl_delay_no_robots_txt_returns_zero(unused_tcp_port: int) -> None:
    runner, base_url, _ = await create_robots_test_server(
        unused_tcp_port,
        robots_status=404,
    )

    try:
        async with RobotsParser() as robots:
            await robots.fetch_robots(base_url)
            assert robots.get_crawl_delay(base_url) == 0.0
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_get_crawl_delay_returns_configured_delay(unused_tcp_port: int) -> None:
    runner, base_url, _ = await create_robots_test_server(unused_tcp_port)

    try:
        async with RobotsParser() as robots:
            await robots.fetch_robots(base_url)
            assert robots.get_crawl_delay(base_url) == 2.0
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_get_crawl_delay_no_directive_returns_zero(unused_tcp_port: int) -> None:
    runner, base_url, _ = await create_robots_test_server(
        unused_tcp_port,
        robots_txt=ROBOTS_TXT_NO_DELAY,
    )

    try:
        async with RobotsParser() as robots:
            await robots.fetch_robots(base_url)
            assert robots.get_crawl_delay(base_url) == 0.0
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Caching — two domains are independent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_two_domains_cached_independently(
    unused_tcp_port: int,
    unused_tcp_port_factory,
) -> None:
    port_b = unused_tcp_port_factory()

    robots_a = """\
User-agent: *
Disallow: /a-private/
"""
    robots_b = """\
User-agent: *
Disallow: /b-private/
"""

    runner_a, base_url_a, _ = await create_robots_test_server(
        unused_tcp_port, robots_txt=robots_a
    )
    runner_b, base_url_b, _ = await create_robots_test_server(
        port_b, robots_txt=robots_b
    )

    try:
        async with RobotsParser() as robots:
            await robots.fetch_robots(base_url_a)
            await robots.fetch_robots(base_url_b)

            assert robots.can_fetch(f"{base_url_a}/a-private/page") is False
            assert robots.can_fetch(f"{base_url_a}/b-private/page") is True

            assert robots.can_fetch(f"{base_url_b}/b-private/page") is False
            assert robots.can_fetch(f"{base_url_b}/a-private/page") is True
    finally:
        await runner_a.cleanup()
        await runner_b.cleanup()
