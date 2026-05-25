"""Shared test server utilities for integration tests."""

import asyncio

from aiohttp import web


async def make_server(
    port: int,
    app: web.Application,
) -> tuple[web.AppRunner, str]:
    """Start an aiohttp test server on the given port. Caller must call runner.cleanup()."""
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", port)
    await site.start()
    return runner, f"http://localhost:{port}"


def ok_app(text: str = "Hello from test server", status: int = 200) -> web.Application:
    """Return a simple app that always responds with the given text and status."""
    app = web.Application()

    async def handler(request: web.Request) -> web.Response:
        return web.Response(text=text, status=status)

    app.router.add_get("/{path:.*}", handler)
    return app


def slow_app(delay: float, text: str = "Slow response") -> web.Application:
    """Return an app that introduces a delay before responding."""
    app = web.Application()

    async def handler(request: web.Request) -> web.Response:
        await asyncio.sleep(delay)
        return web.Response(text=text, status=200)

    app.router.add_get("/{path:.*}", handler)
    return app
