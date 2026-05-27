import json
from datetime import datetime, timezone
from unittest.mock import AsyncMock, patch

import pytest

from crawler.storage.postgres_storage import PostgreSQLStorage


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


@pytest.fixture
def mock_conn() -> AsyncMock:
    return AsyncMock()


@pytest.fixture(autouse=False)
def patch_connect(mock_conn: AsyncMock):
    """Patch asyncpg.connect so tests never open a real DB connection."""
    with patch(
        "crawler.storage.postgres_storage.asyncpg.connect",
        new_callable=AsyncMock,
        return_value=mock_conn,
    ):
        yield


# --- buffering ---


@pytest.mark.asyncio
async def test_save_buffers_without_flush(mock_conn: AsyncMock, patch_connect) -> None:
    storage = PostgreSQLStorage("postgresql://localhost/test", batch_size=10)
    for _ in range(3):
        await storage.save(make_page())
    mock_conn.executemany.assert_not_called()


@pytest.mark.asyncio
async def test_flush_at_batch_size(mock_conn: AsyncMock, patch_connect) -> None:
    storage = PostgreSQLStorage("postgresql://localhost/test", batch_size=3)
    for _ in range(3):
        await storage.save(make_page())
    mock_conn.executemany.assert_called_once()
    sql_arg, records_arg = mock_conn.executemany.call_args[0]
    assert len(records_arg) == 3


@pytest.mark.asyncio
async def test_buffer_clears_after_flush(mock_conn: AsyncMock, patch_connect) -> None:
    storage = PostgreSQLStorage("postgresql://localhost/test", batch_size=2)
    for _ in range(4):
        await storage.save(make_page())
    assert mock_conn.executemany.call_count == 2
    assert len(storage._buffer) == 0


# --- close ---


@pytest.mark.asyncio
async def test_close_flushes_remaining(mock_conn: AsyncMock, patch_connect) -> None:
    storage = PostgreSQLStorage("postgresql://localhost/test", batch_size=10)
    for _ in range(3):
        await storage.save(make_page())
    await storage.close()
    mock_conn.executemany.assert_called_once()
    _, records_arg = mock_conn.executemany.call_args[0]
    assert len(records_arg) == 3


@pytest.mark.asyncio
async def test_close_empty_buffer_no_flush(mock_conn: AsyncMock, patch_connect) -> None:
    storage = PostgreSQLStorage("postgresql://localhost/test", batch_size=10)
    await storage.close()
    mock_conn.executemany.assert_not_called()


@pytest.mark.asyncio
async def test_close_closes_connection(mock_conn: AsyncMock, patch_connect) -> None:
    storage = PostgreSQLStorage("postgresql://localhost/test", batch_size=10)
    await storage.save(make_page())
    await storage.close()
    mock_conn.close.assert_called_once()


@pytest.mark.asyncio
async def test_close_without_connection_no_error(patch_connect) -> None:
    # close() before any save() — _conn is None, should not raise
    storage = PostgreSQLStorage("postgresql://localhost/test", batch_size=10)
    await storage.close()  # should not raise


@pytest.mark.asyncio
async def test_close_is_idempotent(mock_conn: AsyncMock, patch_connect) -> None:
    storage = PostgreSQLStorage("postgresql://localhost/test", batch_size=10)
    await storage.save(make_page())
    await storage.close()
    await storage.close()  # second call — should not raise or double-close


# --- init_db ---


@pytest.mark.asyncio
async def test_init_db_creates_table(mock_conn: AsyncMock, patch_connect) -> None:
    storage = PostgreSQLStorage("postgresql://localhost/test")
    await storage.init_db()
    executed = [c.args[0] for c in mock_conn.execute.call_args_list]
    assert any("CREATE TABLE IF NOT EXISTS" in sql for sql in executed)


@pytest.mark.asyncio
async def test_init_db_creates_index(mock_conn: AsyncMock, patch_connect) -> None:
    storage = PostgreSQLStorage("postgresql://localhost/test")
    await storage.init_db()
    executed = [c.args[0] for c in mock_conn.execute.call_args_list]
    assert any("CREATE INDEX IF NOT EXISTS" in sql for sql in executed)


@pytest.mark.asyncio
async def test_initialize_creates_table_and_index(mock_conn: AsyncMock, patch_connect) -> None:
    storage = PostgreSQLStorage("postgresql://localhost/test")
    await storage.initialize()
    executed = [c.args[0] for c in mock_conn.execute.call_args_list]
    assert any("CREATE TABLE IF NOT EXISTS" in sql for sql in executed)
    assert any("CREATE INDEX IF NOT EXISTS" in sql for sql in executed)


# --- SQL correctness ---


def test_sql_contains_on_conflict() -> None:
    assert "ON CONFLICT (url) DO UPDATE" in PostgreSQLStorage._UPSERT


def test_upsert_uses_positional_params() -> None:
    # asyncpg uses $1, $2 placeholders — not %s or ?
    assert "$1" in PostgreSQLStorage._UPSERT


# --- None fields ---


@pytest.mark.asyncio
async def test_none_fields_no_error(mock_conn: AsyncMock, patch_connect) -> None:
    storage = PostgreSQLStorage("postgresql://localhost/test", batch_size=10)
    page = make_page(title=None, content_type=None, status_code=None)
    await storage.save(page)
    assert len(storage._buffer) == 1


@pytest.mark.asyncio
async def test_none_fields_flush_no_error(mock_conn: AsyncMock, patch_connect) -> None:
    storage = PostgreSQLStorage("postgresql://localhost/test", batch_size=10)
    await storage.save(make_page(title=None, content_type=None))
    await storage.close()
    mock_conn.executemany.assert_called_once()


# --- context manager ---


@pytest.mark.asyncio
async def test_context_manager_flushes_and_closes(mock_conn: AsyncMock, patch_connect) -> None:
    async with PostgreSQLStorage("postgresql://localhost/test", batch_size=10) as storage:
        await storage.save(make_page())
    mock_conn.executemany.assert_called_once()
    mock_conn.close.assert_called_once()


# --- serialisation ---


@pytest.mark.asyncio
async def test_links_serialized_as_json(mock_conn: AsyncMock, patch_connect) -> None:
    storage = PostgreSQLStorage("postgresql://localhost/test", batch_size=1)
    await storage.save(make_page(links=["https://a.com", "https://b.com"]))
    _, records_arg = mock_conn.executemany.call_args[0]
    links_val = records_arg[0][3]  # 4th column: links
    assert json.loads(links_val) == ["https://a.com", "https://b.com"]


@pytest.mark.asyncio
async def test_metadata_serialized_as_json(mock_conn: AsyncMock, patch_connect) -> None:
    meta = {"description": "A page", "keywords": "test"}
    storage = PostgreSQLStorage("postgresql://localhost/test", batch_size=1)
    await storage.save(make_page(metadata=meta))
    _, records_arg = mock_conn.executemany.call_args[0]
    meta_val = records_arg[0][4]  # 5th column: metadata
    assert json.loads(meta_val) == meta
