import asyncio

import pytest
from aiohttp import web

from crawler.async_crawler import AsyncCrawler


async def create_crawl_test_server(
    unused_tcp_port,
    include_about_link: bool = False,
):
    async def index_handler(request):
        about_link = '<a href="/about">About</a>' if include_about_link else ""

        return web.Response(
            text=f"""
            <html>
              <head>
                <title>Home Page</title>
              </head>
              <body>
                <h1>Welcome</h1>
                <p>Hello from crawl test</p>
                {about_link}
              </body>
            </html>
            """,
            content_type="text/html",
        )

    async def about_handler(request):
        return web.Response(
            text="""
            <html>
              <head>
                <title>About Page</title>
              </head>
              <body>
                <h1>About</h1>
                <p>About crawl test page</p>
              </body>
            </html>
            """,
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/about", about_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    port = unused_tcp_port
    site = web.TCPSite(runner, "localhost", port)
    await site.start()

    return runner, f"http://localhost:{port}"


async def create_duplicate_link_test_server(unused_tcp_port):
    request_counts = {
        "about": 0,
    }

    async def index_handler(request):
        return web.Response(
            text="""
                        <html>
                            <head>
                                <title>Home Page</title>
                            </head>
                            <body>
                                <a href="/about">About</a>
                                <a href="/contact">Contact</a>
                            </body>
                        </html>
                        """,
            content_type="text/html",
        )

    async def contact_handler(request):
        return web.Response(
            text="""
                        <html>
                            <head>
                                <title>Contact Page</title>
                            </head>
                            <body>
                                <a href="/about">About Again</a>
                            </body>
                        </html>
                        """,
            content_type="text/html",
        )

    async def about_handler(request):
        request_counts["about"] += 1

        return web.Response(
            text="""
                        <html>
                            <head>
                                <title>About Page</title>
                            </head>
                            <body>
                                <p>About content</p>
                            </body>
                        </html>
                        """,
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/contact", contact_handler)
    app.router.add_get("/about", about_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    port = unused_tcp_port
    site = web.TCPSite(runner, "localhost", port)
    await site.start()

    return runner, f"http://localhost:{port}", request_counts


async def create_same_domain_test_server(unused_tcp_port):
    async def index_handler(request):
        return web.Response(
            text="""
                        <html>
                            <head>
                                <title>Home Page</title>
                            </head>
                            <body>
                                <a href="/about">Internal About</a>
                                <a href="https://external.example/page">External Page</a>
                            </body>
                        </html>
                        """,
            content_type="text/html",
        )

    async def about_handler(request):
        return web.Response(
            text="""
                        <html>
                            <head>
                                <title>About Page</title>
                            </head>
                            <body>
                                <p>Internal about content</p>
                            </body>
                        </html>
                        """,
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/about", about_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    port = unused_tcp_port
    site = web.TCPSite(runner, "localhost", port)
    await site.start()

    return runner, f"http://localhost:{port}"


async def create_include_patterns_test_server(unused_tcp_port):
    async def index_handler(request):
        return web.Response(
            text="""
                        <html>
                            <head>
                                <title>Home Page</title>
                            </head>
                            <body>
                                <a href="/docs/page">Docs Page</a>
                                <a href="/blog/post">Blog Post</a>
                            </body>
                        </html>
                        """,
            content_type="text/html",
        )

    async def docs_handler(request):
        return web.Response(
            text="""
                        <html>
                            <head>
                                <title>Docs Page</title>
                            </head>
                            <body>
                                <p>Documentation content</p>
                            </body>
                        </html>
                        """,
            content_type="text/html",
        )

    async def blog_handler(request):
        return web.Response(
            text="""
                        <html>
                            <head>
                                <title>Blog Post</title>
                            </head>
                            <body>
                                <p>Blog content</p>
                            </body>
                        </html>
                        """,
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/docs/page", docs_handler)
    app.router.add_get("/blog/post", blog_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    port = unused_tcp_port
    site = web.TCPSite(runner, "localhost", port)
    await site.start()

    return runner, f"http://localhost:{port}"


async def create_failure_state_test_server(unused_tcp_port):
    async def index_handler(request):
        return web.Response(
            text="""
                        <html>
                            <head>
                                <title>Home Page</title>
                            </head>
                            <body>
                                <a href="/ok">OK Page</a>
                                <a href="/missing">Missing Page</a>
                            </body>
                        </html>
                        """,
            content_type="text/html",
        )

    async def ok_handler(request):
        return web.Response(
            text="""
                        <html>
                            <head>
                                <title>OK Page</title>
                            </head>
                            <body>
                                <p>Successful page</p>
                            </body>
                        </html>
                        """,
            content_type="text/html",
        )

    async def missing_handler(request):
        return web.Response(text="Not found", status=404)

    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/ok", ok_handler)
    app.router.add_get("/missing", missing_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    port = unused_tcp_port
    site = web.TCPSite(runner, "localhost", port)
    await site.start()

    return runner, f"http://localhost:{port}"


async def create_concurrent_crawl_test_server(unused_tcp_port):
    request_state = {
        "active": 0,
        "max_active": 0,
    }

    async def index_handler(request):
        return web.Response(
            text="""
                        <html>
                            <head>
                                <title>Home Page</title>
                            </head>
                            <body>
                                <a href="/slow-1">Slow One</a>
                                <a href="/slow-2">Slow Two</a>
                                <a href="/slow-3">Slow Three</a>
                            </body>
                        </html>
                        """,
            content_type="text/html",
        )

    async def slow_handler(request):
        request_state["active"] += 1
        request_state["max_active"] = max(
            request_state["max_active"],
            request_state["active"],
        )

        try:
            await asyncio.sleep(0.1)

            return web.Response(
                text="""
                                <html>
                                    <head>
                                        <title>Slow Page</title>
                                    </head>
                                    <body>
                                        <p>Slow content</p>
                                    </body>
                                </html>
                                """,
                content_type="text/html",
            )
        finally:
            request_state["active"] -= 1

    app = web.Application()
    app.router.add_get("/", index_handler)
    app.router.add_get("/slow-1", slow_handler)
    app.router.add_get("/slow-2", slow_handler)
    app.router.add_get("/slow-3", slow_handler)

    runner = web.AppRunner(app)
    await runner.setup()

    port = unused_tcp_port
    site = web.TCPSite(runner, "localhost", port)
    await site.start()

    return runner, f"http://localhost:{port}", request_state


@pytest.mark.asyncio
async def test_crawl_processes_single_start_url(unused_tcp_port) -> None:
    runner, base_url = await create_crawl_test_server(unused_tcp_port)
    start_url = f"{base_url}/"

    try:
        async with AsyncCrawler() as crawler:
            results = await crawler.crawl(
                start_urls=[start_url],
                max_pages=10,
            )

        assert len(results) == 1
        assert start_url in results
        assert results[start_url]["url"] == start_url
        assert results[start_url]["title"] == "Home Page"
        assert "Welcome" in results[start_url]["text"]

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_crawl_processes_discovered_link(unused_tcp_port) -> None:
    runner, base_url = await create_crawl_test_server(
        unused_tcp_port,
        include_about_link=True,
    )
    start_url = f"{base_url}/"
    discovered_url = f"{base_url}/about"

    try:
        async with AsyncCrawler() as crawler:
            results = await crawler.crawl(
                start_urls=[start_url],
                max_pages=10,
            )

        assert len(results) == 2
        assert start_url in results
        assert discovered_url in results
        assert results[discovered_url]["title"] == "About Page"
        assert "About crawl test page" in results[discovered_url]["text"]

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_crawl_respects_max_depth(unused_tcp_port) -> None:
    runner, base_url = await create_crawl_test_server(
        unused_tcp_port,
        include_about_link=True,
    )
    start_url = f"{base_url}/"
    discovered_url = f"{base_url}/about"

    try:
        async with AsyncCrawler(max_depth=0) as crawler:
            results = await crawler.crawl(
                start_urls=[start_url],
                max_pages=10,
            )

        assert len(results) == 1
        assert start_url in results
        assert discovered_url not in results

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_crawl_does_not_revisit_duplicate_links(unused_tcp_port) -> None:
    runner, base_url, request_counts = await create_duplicate_link_test_server(
        unused_tcp_port,
    )
    start_url = f"{base_url}/"
    about_url = f"{base_url}/about"
    contact_url = f"{base_url}/contact"

    try:
        async with AsyncCrawler() as crawler:
            results = await crawler.crawl(
                start_urls=[start_url],
                max_pages=10,
            )

        assert len(results) == 3
        assert start_url in results
        assert about_url in results
        assert contact_url in results
        assert request_counts["about"] == 1

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_crawl_respects_same_domain_only(unused_tcp_port) -> None:
    runner, base_url = await create_same_domain_test_server(unused_tcp_port)
    start_url = f"{base_url}/"
    internal_url = f"{base_url}/about"
    external_url = "https://external.example/page"

    try:
        async with AsyncCrawler() as crawler:
            results = await crawler.crawl(
                start_urls=[start_url],
                max_pages=10,
                same_domain_only=True,
            )

        assert len(results) == 2
        assert start_url in results
        assert internal_url in results
        assert external_url not in results
        assert external_url not in crawler.visited_urls
        assert crawler.failed_urls == {}

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_crawl_respects_include_patterns(unused_tcp_port) -> None:
    runner, base_url = await create_include_patterns_test_server(unused_tcp_port)
    start_url = f"{base_url}/"
    docs_url = f"{base_url}/docs/page"
    blog_url = f"{base_url}/blog/post"

    try:
        async with AsyncCrawler() as crawler:
            results = await crawler.crawl(
                start_urls=[start_url],
                max_pages=10,
                include_patterns=["/docs/"],
            )

        assert len(results) == 2
        assert start_url in results
        assert docs_url in results
        assert blog_url not in results
        assert blog_url not in crawler.visited_urls

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_crawl_respects_exclude_patterns(unused_tcp_port) -> None:
    runner, base_url = await create_include_patterns_test_server(unused_tcp_port)
    start_url = f"{base_url}/"
    docs_url = f"{base_url}/docs/page"
    blog_url = f"{base_url}/blog/post"

    try:
        async with AsyncCrawler() as crawler:
            results = await crawler.crawl(
                start_urls=[start_url],
                max_pages=10,
                exclude_patterns=["/blog/"],
            )

        assert len(results) == 2
        assert start_url in results
        assert docs_url in results
        assert blog_url not in results
        assert blog_url not in crawler.visited_urls

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_crawl_tracks_processed_and_failed_urls(unused_tcp_port) -> None:
    runner, base_url = await create_failure_state_test_server(unused_tcp_port)
    start_url = f"{base_url}/"
    ok_url = f"{base_url}/ok"
    missing_url = f"{base_url}/missing"

    try:
        async with AsyncCrawler() as crawler:
            results = await crawler.crawl(
                start_urls=[start_url],
                max_pages=10,
            )

        assert start_url in results
        assert ok_url in results
        assert missing_url not in results

        assert start_url in crawler.processed_urls
        assert ok_url in crawler.processed_urls
        assert missing_url not in crawler.processed_urls

        assert missing_url in crawler.failed_urls
        assert crawler.failed_urls[missing_url] is not None

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_crawl_exposes_progress_stats(unused_tcp_port) -> None:
    runner, base_url = await create_failure_state_test_server(unused_tcp_port)
    start_url = f"{base_url}/"

    try:
        async with AsyncCrawler() as crawler:
            await crawler.crawl(
                start_urls=[start_url],
                max_pages=10,
            )

            stats = crawler.get_crawl_stats()

        assert stats["processed_pages"] == 2
        assert stats["queued"] == 0
        assert stats["errors"] == 1
        assert stats["active_tasks"] == 0
        assert stats["pages_per_second"] >= 0.0

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_crawl_logs_progress_when_enabled(caplog, unused_tcp_port) -> None:
    runner, base_url = await create_failure_state_test_server(unused_tcp_port)
    start_url = f"{base_url}/"

    try:
        caplog.set_level("INFO", logger="crawler.async_crawler")

        async with AsyncCrawler() as crawler:
            await crawler.crawl(
                start_urls=[start_url],
                max_pages=10,
                show_progress=True,
            )

        progress_messages = [
            record.message
            for record in caplog.records
            if record.message.startswith("Crawl progress:")
        ]

        assert progress_messages
        assert any("processed=2" in message for message in progress_messages)
        assert any("errors=1" in message for message in progress_messages)

    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_crawl_fetches_discovered_pages_concurrently(unused_tcp_port) -> None:
    runner, base_url, request_state = await create_concurrent_crawl_test_server(
        unused_tcp_port,
    )
    start_url = f"{base_url}/"

    try:
        async with AsyncCrawler(max_concurrent=3) as crawler:
            results = await crawler.crawl(
                start_urls=[start_url],
                max_pages=10,
            )

        assert len(results) == 4
        assert request_state["max_active"] == 2

    finally:
        await runner.cleanup()
