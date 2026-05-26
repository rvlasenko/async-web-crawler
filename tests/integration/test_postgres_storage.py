"""Integration tests for PostgreSQLStorage against a real PostgreSQL database.

Requires CRAWLER_TEST_POSTGRES_DSN to be set in .env.testing:
    CRAWLER_TEST_POSTGRES_DSN=postgresql://localhost/crawler_test

The variable is loaded automatically by tests/conftest.py via python-dotenv.
All tests are skipped when the variable is not set. Never point this at a
development or production database — the fixture drops and recreates the table
before each test.

Run only these tests:
    pytest -m postgres

Skip these tests:
    pytest -m "not postgres"
"""

import os
from collections.abc import AsyncGenerator
from datetime import datetime, timezone

import asyncpg
import pytest
import pytest_asyncio

from crawler.storage.postgres_storage import PostgreSQLStorage

POSTGRES_DSN = os.getenv("CRAWLER_TEST_POSTGRES_DSN")

pytestmark = [
    pytest.mark.postgres,
    pytest.mark.skipif(
        not POSTGRES_DSN,
        reason="Set CRAWLER_TEST_POSTGRES_DSN to run PostgreSQL integration tests",
    ),
]


def make_page(**overrides) -> dict:
    base = {
        "url": "https://example.com",
        "title": "Example Page",
        "text": "Hello world",
        "links": ["https://example.com/about"],
        "metadata": {"description": "A test page"},
        "crawled_at": datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc),
        "status_code": 200,
        "content_type": "text/html; charset=utf-8",
    }
    base.update(overrides)
    return base


@pytest_asyncio.fixture
async def storage() -> AsyncGenerator[PostgreSQLStorage, None]:
    s = PostgreSQLStorage(POSTGRES_DSN, batch_size=50)  # type: ignore[arg-type]
    yield s
    await s.close()


@pytest_asyncio.fixture(autouse=True)
async def clean_db(storage: PostgreSQLStorage) -> AsyncGenerator[None, None]:
    """Drop and recreate crawled_pages before every test for a clean slate."""
    conn = await asyncpg.connect(POSTGRES_DSN)
    await conn.execute("DROP TABLE IF EXISTS crawled_pages CASCADE")
    await conn.close()
    await storage.init_db()
    yield


# --- schema ---


@pytest.mark.asyncio
async def test_init_db_creates_table_in_real_db(storage: PostgreSQLStorage) -> None:
    conn = await asyncpg.connect(POSTGRES_DSN)
    try:
        row = await conn.fetchrow(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = 'public' AND table_name = 'crawled_pages'"
        )
        assert row is not None
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_init_db_creates_index_in_real_db(storage: PostgreSQLStorage) -> None:
    conn = await asyncpg.connect(POSTGRES_DSN)
    try:
        row = await conn.fetchrow(
            "SELECT indexname FROM pg_indexes "
            "WHERE tablename = 'crawled_pages' AND indexname = 'crawled_pages_crawled_at_idx'"
        )
        assert row is not None
    finally:
        await conn.close()


# --- save and read back ---


@pytest.mark.asyncio
async def test_save_single_record(storage: PostgreSQLStorage) -> None:
    await storage.save(make_page(url="https://example.com/a"))
    await storage.close()

    conn = await asyncpg.connect(POSTGRES_DSN)
    try:
        row = await conn.fetchrow("SELECT * FROM crawled_pages WHERE url = $1", "https://example.com/a")
        assert row is not None
        assert row["title"] == "Example Page"
        assert row["status_code"] == 200
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_save_multiple_records(storage: PostgreSQLStorage) -> None:
    for i in range(3):
        await storage.save(make_page(url=f"https://example.com/{i}"))
    await storage.close()

    conn = await asyncpg.connect(POSTGRES_DSN)
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM crawled_pages")
        assert count == 3
    finally:
        await conn.close()


@pytest.mark.asyncio
async def test_datetime_stored_correctly(storage: PostgreSQLStorage) -> None:
    dt = datetime(2024, 6, 15, 10, 30, 0, tzinfo=timezone.utc)
    await storage.save(make_page(crawled_at=dt))
    await storage.close()

    conn = await asyncpg.connect(POSTGRES_DSN)
    try:
        row = await conn.fetchrow("SELECT crawled_at FROM crawled_pages WHERE url = $1", "https://example.com")
        assert row["crawled_at"].replace(tzinfo=timezone.utc) == dt
    finally:
        await conn.close()


# --- upsert ---


@pytest.mark.asyncio
async def test_upsert_updates_existing_url(storage: PostgreSQLStorage) -> None:
    await storage.save(make_page(url="https://example.com", title="First"))
    await storage.close()

    storage2 = PostgreSQLStorage(POSTGRES_DSN, batch_size=50)  # type: ignore[arg-type]
    await storage2.init_db()
    await storage2.save(make_page(url="https://example.com", title="Updated"))
    await storage2.close()

    conn = await asyncpg.connect(POSTGRES_DSN)
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM crawled_pages")
        assert count == 1
        title = await conn.fetchval("SELECT title FROM crawled_pages WHERE url = $1", "https://example.com")
        assert title == "Updated"
    finally:
        await conn.close()


# --- batch flush ---


@pytest.mark.asyncio
async def test_batch_flush_on_close(storage: PostgreSQLStorage) -> None:
    s = PostgreSQLStorage(POSTGRES_DSN, batch_size=10)  # type: ignore[arg-type]
    await s.init_db()
    for i in range(7):
        await s.save(make_page(url=f"https://example.com/{i}"))
    # buffer holds 7 records, batch_size=10 → no automatic flush yet
    await s.close()

    conn = await asyncpg.connect(POSTGRES_DSN)
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM crawled_pages")
        assert count == 7
    finally:
        await conn.close()


# --- None fields ---


@pytest.mark.asyncio
async def test_none_fields_stored_as_null(storage: PostgreSQLStorage) -> None:
    await storage.save(make_page(title=None, content_type=None, status_code=None))
    await storage.close()

    conn = await asyncpg.connect(POSTGRES_DSN)
    try:
        row = await conn.fetchrow("SELECT title, content_type, status_code FROM crawled_pages")
        assert row["title"] is None
        assert row["content_type"] is None
        assert row["status_code"] is None
    finally:
        await conn.close()


# --- context manager ---


@pytest.mark.asyncio
async def test_context_manager_saves_and_closes(storage: PostgreSQLStorage) -> None:
    # init_db() is called before the context manager so the variable retains
    # its PostgreSQLStorage type inside the `async with` block.
    # (__aenter__ returns DataStorage, which has no init_db.)
    s = PostgreSQLStorage(POSTGRES_DSN, batch_size=50)  # type: ignore[arg-type]
    await s.init_db()
    async with s:
        await s.save(make_page(url="https://ctx.example.com"))

    conn = await asyncpg.connect(POSTGRES_DSN)
    try:
        row = await conn.fetchrow("SELECT url FROM crawled_pages WHERE url = $1", "https://ctx.example.com")
        assert row is not None
    finally:
        await conn.close()
