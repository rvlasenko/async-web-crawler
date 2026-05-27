import json
from typing import Any

import asyncpg

from crawler.storage.base import DataStorage


class PostgreSQLStorage(DataStorage):
    """Stores crawled pages in PostgreSQL using buffered batch upserts.

    Records accumulate in _buffer until batch_size is reached, then written with
    a single executemany() call. close() flushes whatever remains in the buffer.

    Re-crawling the same URL updates the existing row (ON CONFLICT DO UPDATE) rather
    than creating duplicates — safe for repeated runs against the same database.

    Requires init_db() before the first save() to create the table and index.

    links and metadata are stored as JSONB — pass json.dumps() output; asyncpg
    accepts JSON strings for JSONB columns without an explicit cast.

    Connection is lazy: opened on the first _get_conn() call, which happens when
    _flush() or init_db() are first invoked. If close() is called before any flush
    (empty buffer, no init_db), no connection is opened.
    """

    _CREATE_TABLE = """
        CREATE TABLE IF NOT EXISTS crawled_pages (
            url          TEXT PRIMARY KEY,
            title        TEXT,
            text         TEXT,
            links        JSONB,
            metadata     JSONB,
            crawled_at   TIMESTAMPTZ,
            status_code  INTEGER,
            content_type TEXT
        )
    """

    _CREATE_INDEX = """
        CREATE INDEX IF NOT EXISTS crawled_pages_crawled_at_idx
        ON crawled_pages (crawled_at DESC)
    """

    _UPSERT = """
        INSERT INTO crawled_pages
            (url, title, text, links, metadata, crawled_at, status_code, content_type)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        ON CONFLICT (url) DO UPDATE SET
            title        = EXCLUDED.title,
            text         = EXCLUDED.text,
            links        = EXCLUDED.links,
            metadata     = EXCLUDED.metadata,
            crawled_at   = EXCLUDED.crawled_at,
            status_code  = EXCLUDED.status_code,
            content_type = EXCLUDED.content_type
    """

    def __init__(self, dsn: str, batch_size: int = 50) -> None:
        self._dsn = dsn
        self._batch_size = batch_size
        self._buffer: list[tuple[Any, ...]] = []
        self._conn: asyncpg.Connection | None = None

    async def _get_conn(self) -> asyncpg.Connection:
        # Assign to a local variable first so Pylance can narrow the type —
        # it cannot narrow mutable instance attributes after an `if is None` check.
        conn = self._conn
        if conn is None:
            conn = await asyncpg.connect(self._dsn)
            self._conn = conn
        return conn

    async def initialize(self) -> None:
        """Create the crawled_pages table and index if they do not exist.

        Called automatically by AdvancedCrawler before starting a crawl.
        Idempotent — safe to call multiple times.
        """
        await self.init_db()

    async def init_db(self) -> None:
        """Create the crawled_pages table and index if they do not exist."""
        conn = await self._get_conn()
        await conn.execute(self._CREATE_TABLE)
        await conn.execute(self._CREATE_INDEX)

    async def save(self, data: dict[str, Any]) -> None:
        # asyncpg JSONB codec requires a Python str (pre-encoded JSON).
        # Passing a Python list/dict directly raises TypeError inside the codec.
        # If links or metadata is None (outside the CrawledPage contract), json.dumps
        # produces "null" — stored as JSONB null rather than [] or {}.
        row: tuple[Any, ...] = (
            data["url"],
            data.get("title"),
            data.get("text"),
            json.dumps(data.get("links", []), ensure_ascii=False),
            json.dumps(data.get("metadata", {}), ensure_ascii=False),
            data.get("crawled_at"),
            data.get("status_code"),
            data.get("content_type"),
        )
        self._buffer.append(row)
        if len(self._buffer) >= self._batch_size:
            await self._flush()

    async def _flush(self) -> None:
        if not self._buffer:
            return
        conn = await self._get_conn()
        batch = list(self._buffer)  # snapshot — buffer cleared only after successful write
        await conn.executemany(self._UPSERT, batch)
        self._buffer.clear()

    async def close(self) -> None:
        await self._flush()
        if self._conn is not None:
            await self._conn.close()
            self._conn = None
