"""Integration tests for AsyncCrawler + DataStorage integration.

Uses a real aiohttp test server and in-memory FakeStorage — no database required.
"""

from datetime import datetime, timezone
from typing import Any

import pytest
from aiohttp import web

from crawler.async_crawler import AsyncCrawler
from crawler.storage.base import DataStorage


class FakeStorage(DataStorage):
    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []

    async def save(self, data: dict[str, Any]) -> None:
        self.saved.append(data)

    async def close(self) -> None:
        pass


class BrokenOnSecondSave(DataStorage):
    def __init__(self) -> None:
        self._calls = 0

    async def save(self, data: dict[str, Any]) -> None:
        self._calls += 1
        if self._calls == 2:
            raise RuntimeError("disk full")

    async def close(self) -> None:
        pass


async def _start_server(port: int) -> tuple[web.AppRunner, str]:
    async def page_handler(request: web.Request) -> web.Response:
        slug = request.match_info.get("slug", "index")
        return web.Response(
            text=f"<html><head><title>{slug}</title></head><body>{slug}</body></html>",
            content_type="text/html",
        )

    app = web.Application()
    app.router.add_get("/{slug}", page_handler)
    app.router.add_get("/", page_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", port)
    await site.start()
    return runner, f"http://localhost:{port}"


@pytest.mark.asyncio
async def test_save_called_per_page(unused_tcp_port: int) -> None:
    runner, base_url = await _start_server(unused_tcp_port)
    storage = FakeStorage()
    try:
        async with AsyncCrawler(storage=storage) as crawler:
            await crawler.crawl([f"{base_url}/a", f"{base_url}/b", f"{base_url}/c"], max_pages=3)
    finally:
        await runner.cleanup()

    assert len(storage.saved) == 3
    saved_urls = {r["url"] for r in storage.saved}
    assert saved_urls == {f"{base_url}/a", f"{base_url}/b", f"{base_url}/c"}


@pytest.mark.asyncio
async def test_save_receives_status_code(unused_tcp_port: int) -> None:
    runner, base_url = await _start_server(unused_tcp_port)
    storage = FakeStorage()
    try:
        async with AsyncCrawler(storage=storage) as crawler:
            await crawler.crawl([f"{base_url}/page"], max_pages=1)
    finally:
        await runner.cleanup()

    assert len(storage.saved) == 1
    assert storage.saved[0]["status_code"] == 200


@pytest.mark.asyncio
async def test_save_receives_content_type(unused_tcp_port: int) -> None:
    runner, base_url = await _start_server(unused_tcp_port)
    storage = FakeStorage()
    try:
        async with AsyncCrawler(storage=storage) as crawler:
            await crawler.crawl([f"{base_url}/page"], max_pages=1)
    finally:
        await runner.cleanup()

    assert len(storage.saved) == 1
    assert "text/html" in storage.saved[0]["content_type"]


@pytest.mark.asyncio
async def test_save_receives_crawled_at(unused_tcp_port: int) -> None:
    runner, base_url = await _start_server(unused_tcp_port)
    storage = FakeStorage()
    before = datetime.now(tz=timezone.utc)
    try:
        async with AsyncCrawler(storage=storage) as crawler:
            await crawler.crawl([f"{base_url}/page"], max_pages=1)
    finally:
        await runner.cleanup()
    after = datetime.now(tz=timezone.utc)

    assert len(storage.saved) == 1
    crawled_at = storage.saved[0]["crawled_at"]
    assert isinstance(crawled_at, datetime)
    assert crawled_at.tzinfo is not None
    assert before <= crawled_at <= after


@pytest.mark.asyncio
async def test_storage_error_does_not_stop_crawl(unused_tcp_port: int) -> None:
    runner, base_url = await _start_server(unused_tcp_port)
    storage = BrokenOnSecondSave()
    try:
        async with AsyncCrawler(storage=storage) as crawler:
            results = await crawler.crawl(
                [f"{base_url}/a", f"{base_url}/b", f"{base_url}/c"],
                max_pages=3,
            )
    finally:
        await runner.cleanup()

    # All 3 pages should still be in processed_urls despite the storage error on page 2.
    assert len(results) == 3


@pytest.mark.asyncio
async def test_no_storage_works_unchanged(unused_tcp_port: int) -> None:
    runner, base_url = await _start_server(unused_tcp_port)
    try:
        async with AsyncCrawler() as crawler:
            results = await crawler.crawl([f"{base_url}/page"], max_pages=1)
    finally:
        await runner.cleanup()

    assert len(results) == 1
