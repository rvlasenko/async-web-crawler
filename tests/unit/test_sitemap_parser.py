"""Tests for SitemapParser using local aiohttp test servers."""

import pytest
from aiohttp import web

import aiohttp

from crawler.sitemap_parser import SitemapParser
from tests.fixtures.server import make_server

_NS = "http://www.sitemaps.org/schemas/sitemap/0.9"


def _urlset(*locs: str) -> str:
    locs_xml = "".join(f"<url><loc>{loc}</loc></url>" for loc in locs)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<urlset xmlns="{_NS}">{locs_xml}</urlset>'
    )


def _index(*child_urls: str) -> str:
    children = "".join(f"<sitemap><loc>{u}</loc></sitemap>" for u in child_urls)
    return (
        f'<?xml version="1.0" encoding="UTF-8"?>'
        f'<sitemapindex xmlns="{_NS}">{children}</sitemapindex>'
    )


@pytest.fixture
def unused_tcp_port(unused_tcp_port_factory):
    return unused_tcp_port_factory()


# ---------------------------------------------------------------------------
# Basic urlset
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_regular_sitemap(unused_tcp_port) -> None:
    async def handler(r: web.Request) -> web.Response:
        return web.Response(
            text=_urlset("https://example.com/a", "https://example.com/b"),
            content_type="application/xml",
        )

    app = web.Application()
    app.router.add_get("/sitemap.xml", handler)
    runner, base = await make_server(unused_tcp_port, app)
    try:
        async with aiohttp.ClientSession() as session:
            urls = await SitemapParser(session).fetch_sitemap(f"{base}/sitemap.xml")

        assert urls == ["https://example.com/a", "https://example.com/b"]
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_fetch_sitemap_deduplicates_urls(unused_tcp_port) -> None:
    async def handler(r: web.Request) -> web.Response:
        return web.Response(
            text=_urlset("https://example.com/a", "https://example.com/a"),
            content_type="application/xml",
        )

    app = web.Application()
    app.router.add_get("/sitemap.xml", handler)
    runner, base = await make_server(unused_tcp_port, app)
    try:
        async with aiohttp.ClientSession() as session:
            urls = await SitemapParser(session).fetch_sitemap(f"{base}/sitemap.xml")

        assert urls == ["https://example.com/a"]
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_fetch_sitemap_empty_urlset_returns_empty(unused_tcp_port) -> None:
    async def handler(r: web.Request) -> web.Response:
        return web.Response(
            text=f'<urlset xmlns="{_NS}"/>',
            content_type="application/xml",
        )

    app = web.Application()
    app.router.add_get("/sitemap.xml", handler)
    runner, base = await make_server(unused_tcp_port, app)
    try:
        async with aiohttp.ClientSession() as session:
            urls = await SitemapParser(session).fetch_sitemap(f"{base}/sitemap.xml")

        assert urls == []
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Sitemap index (recursive)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_sitemap_index_fetches_children(unused_tcp_port) -> None:
    async def index_handler(r: web.Request) -> web.Response:
        return web.Response(
            text=_index(
                f"http://localhost:{unused_tcp_port}/a.xml",
                f"http://localhost:{unused_tcp_port}/b.xml",
            ),
            content_type="application/xml",
        )

    async def child_a(r: web.Request) -> web.Response:
        return web.Response(
            text=_urlset("https://example.com/page1"),
            content_type="application/xml",
        )

    async def child_b(r: web.Request) -> web.Response:
        return web.Response(
            text=_urlset("https://example.com/page2"),
            content_type="application/xml",
        )

    app = web.Application()
    app.router.add_get("/index.xml", index_handler)
    app.router.add_get("/a.xml", child_a)
    app.router.add_get("/b.xml", child_b)
    runner, base = await make_server(unused_tcp_port, app)
    try:
        async with aiohttp.ClientSession() as session:
            urls = await SitemapParser(session).fetch_sitemap(f"{base}/index.xml")

        assert set(urls) == {"https://example.com/page1", "https://example.com/page2"}
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_fetch_sitemap_index_deduplicates_across_children(unused_tcp_port) -> None:
    shared = "https://example.com/shared"

    async def index_handler(r: web.Request) -> web.Response:
        return web.Response(
            text=_index(
                f"http://localhost:{unused_tcp_port}/a.xml",
                f"http://localhost:{unused_tcp_port}/b.xml",
            ),
            content_type="application/xml",
        )

    async def child(r: web.Request) -> web.Response:
        return web.Response(text=_urlset(shared), content_type="application/xml")

    app = web.Application()
    app.router.add_get("/index.xml", index_handler)
    app.router.add_get("/a.xml", child)
    app.router.add_get("/b.xml", child)
    runner, base = await make_server(unused_tcp_port, app)
    try:
        async with aiohttp.ClientSession() as session:
            urls = await SitemapParser(session).fetch_sitemap(f"{base}/index.xml")

        assert urls.count(shared) == 1
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Error handling — must return [] and never raise
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_sitemap_http_404_returns_empty(unused_tcp_port) -> None:
    async def handler(r: web.Request) -> web.Response:
        return web.Response(status=404)

    app = web.Application()
    app.router.add_get("/sitemap.xml", handler)
    runner, base = await make_server(unused_tcp_port, app)
    try:
        async with aiohttp.ClientSession() as session:
            urls = await SitemapParser(session).fetch_sitemap(f"{base}/sitemap.xml")

        assert urls == []
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_fetch_sitemap_http_500_returns_empty(unused_tcp_port) -> None:
    async def handler(r: web.Request) -> web.Response:
        return web.Response(status=500)

    app = web.Application()
    app.router.add_get("/sitemap.xml", handler)
    runner, base = await make_server(unused_tcp_port, app)
    try:
        async with aiohttp.ClientSession() as session:
            urls = await SitemapParser(session).fetch_sitemap(f"{base}/sitemap.xml")

        assert urls == []
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_fetch_sitemap_malformed_xml_returns_empty(unused_tcp_port) -> None:
    async def handler(r: web.Request) -> web.Response:
        return web.Response(text="<not valid xml<<")

    app = web.Application()
    app.router.add_get("/sitemap.xml", handler)
    runner, base = await make_server(unused_tcp_port, app)
    try:
        async with aiohttp.ClientSession() as session:
            urls = await SitemapParser(session).fetch_sitemap(f"{base}/sitemap.xml")

        assert urls == []
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_fetch_sitemap_unreachable_url_returns_empty() -> None:
    async with aiohttp.ClientSession() as session:
        urls = await SitemapParser(session).fetch_sitemap(
            "http://127.0.0.1:19999/sitemap.xml"
        )

    assert urls == []


# ---------------------------------------------------------------------------
# Recursion depth limit
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_sitemap_respects_max_recursion_depth(unused_tcp_port) -> None:
    """Chain: index → index → urlset. With depth=1 we should not reach the urlset."""

    async def level0(r: web.Request) -> web.Response:
        return web.Response(
            text=_index(f"http://localhost:{unused_tcp_port}/level1.xml"),
            content_type="application/xml",
        )

    async def level1(r: web.Request) -> web.Response:
        return web.Response(
            text=_index(f"http://localhost:{unused_tcp_port}/level2.xml"),
            content_type="application/xml",
        )

    async def level2(r: web.Request) -> web.Response:
        return web.Response(
            text=_urlset("https://example.com/deep"),
            content_type="application/xml",
        )

    app = web.Application()
    app.router.add_get("/level0.xml", level0)
    app.router.add_get("/level1.xml", level1)
    app.router.add_get("/level2.xml", level2)
    runner, base = await make_server(unused_tcp_port, app)
    try:
        async with aiohttp.ClientSession() as session:
            # depth=1: level0 (0) → level1 (1) → level2 would be depth 2, exceeds limit
            parser = SitemapParser(session, max_recursion_depth=1)
            urls = await parser.fetch_sitemap(f"{base}/level0.xml")

        assert "https://example.com/deep" not in urls
    finally:
        await runner.cleanup()
