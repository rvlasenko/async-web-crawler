from unittest.mock import patch

import pytest
from aiohttp import web

from crawler.async_crawler import AsyncCrawler

ROBOTS_BLOCK_BOTA = """\
User-agent: BotA
Disallow: /private/
"""


async def create_test_server(unused_tcp_port: int):
    received_agents: list[str] = []

    async def handler(request: web.Request) -> web.Response:
        received_agents.append(request.headers.get("User-Agent", ""))
        return web.Response(
            text="<html><body>ok</body></html>", content_type="text/html"
        )

    app = web.Application()
    app.router.add_get("/{path:.*}", handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", unused_tcp_port)
    await site.start()

    return runner, f"http://localhost:{unused_tcp_port}", received_agents


# ---------------------------------------------------------------------------
# Настраиваемый User-Agent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_default_user_agent(unused_tcp_port: int) -> None:
    runner, base_url, received_agents = await create_test_server(unused_tcp_port)

    try:
        async with AsyncCrawler() as crawler:
            await crawler.fetch_url(f"{base_url}/page")

        assert received_agents[0] == "AsyncCrawler/1.0"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_custom_string_user_agent(unused_tcp_port: int) -> None:
    runner, base_url, received_agents = await create_test_server(unused_tcp_port)

    try:
        async with AsyncCrawler(user_agent="MyBot/2.0") as crawler:
            await crawler.fetch_url(f"{base_url}/page")

        assert received_agents[0] == "MyBot/2.0"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_user_agent_header_is_sent(unused_tcp_port: int) -> None:
    runner, base_url, received_agents = await create_test_server(unused_tcp_port)

    try:
        async with AsyncCrawler(user_agent="TestAgent/1.0") as crawler:
            await crawler.fetch_url(f"{base_url}/page")

        assert "TestAgent/1.0" in received_agents
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# Ротация User-Agent
# ---------------------------------------------------------------------------


def test_empty_list_raises() -> None:
    with pytest.raises(ValueError, match="user_agent list must not be empty"):
        AsyncCrawler(user_agent=[])


@pytest.mark.asyncio
async def test_rotation_picks_from_list(unused_tcp_port: int) -> None:
    agents = ["AgentA/1.0", "AgentB/1.0"]
    runner, base_url, received_agents = await create_test_server(unused_tcp_port)

    try:
        with patch("crawler.async_crawler.random.choice", return_value="AgentA/1.0") as mock_choice:
            async with AsyncCrawler(user_agent=agents) as crawler:
                await crawler.fetch_url(f"{base_url}/page")

        mock_choice.assert_called_once_with(agents)
        assert received_agents[0] == "AgentA/1.0"
    finally:
        await runner.cleanup()


@pytest.mark.asyncio
async def test_rotation_sends_different_agents(unused_tcp_port: int) -> None:
    agents = ["AgentA/1.0", "AgentB/1.0"]
    runner, base_url, received_agents = await create_test_server(unused_tcp_port)

    try:
        with patch(
            "crawler.async_crawler.random.choice",
            side_effect=["AgentA/1.0", "AgentB/1.0"],
        ):
            async with AsyncCrawler(user_agent=agents) as crawler:
                await crawler.fetch_url(f"{base_url}/first")
                await crawler.fetch_url(f"{base_url}/second")

        assert received_agents == ["AgentA/1.0", "AgentB/1.0"]
    finally:
        await runner.cleanup()


# ---------------------------------------------------------------------------
# robots.txt использует основной агент
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_robots_uses_primary_agent(unused_tcp_port: int) -> None:
    async def robots_handler(request: web.Request) -> web.Response:
        return web.Response(text=ROBOTS_BLOCK_BOTA, content_type="text/plain")

    async def page_handler(request: web.Request) -> web.Response:
        return web.Response(
            text="<html><body>ok</body></html>", content_type="text/html"
        )

    app = web.Application()
    app.router.add_get("/robots.txt", robots_handler)
    app.router.add_get("/{path:.*}", page_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", unused_tcp_port)
    await site.start()

    base_url = f"http://localhost:{unused_tcp_port}"

    try:
        async with AsyncCrawler(
            user_agent=["BotA", "BotB"],
            respect_robots_txt=True,
        ) as crawler:
            result = await crawler.fetch_url(f"{base_url}/private/page")

        assert result["success"] is False
        assert result["error"] == "Blocked by robots.txt"
    finally:
        await runner.cleanup()
