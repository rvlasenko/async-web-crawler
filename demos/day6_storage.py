import asyncio
import csv
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import asyncpg
from aiohttp import web
from dotenv import load_dotenv

from crawler.async_crawler import AsyncCrawler
from crawler.storage.csv_storage import CSVStorage
from crawler.storage.json_storage import JSONStorage
from crawler.storage.postgres_storage import PostgreSQLStorage

PROJECT_ROOT = Path(__file__).resolve().parents[1]

logging.basicConfig(
    stream=sys.stdout, level=logging.WARNING, format="  [log] %(message)s", force=True
)
logging.getLogger("crawler").setLevel(logging.ERROR)

OUTPUT_DIR = Path("output")
JSON_FILE = OUTPUT_DIR / "day6_results.jsonl"
CSV_FILE = OUTPUT_DIR / "day6_results.csv"
load_dotenv(PROJECT_ROOT / ".env")
POSTGRES_DSN = os.getenv("CRAWLER_POSTGRES_DSN")
PORT = 18766


# ---------------------------------------------------------------------------
# Local test server
# ---------------------------------------------------------------------------

PAGES: dict[str, dict[str, Any]] = {
    "/": {
        "title": "Home",
        "text": "Welcome to the demo site",
        "links": ["/about", "/products", "/blog"],
    },
    "/about": {
        "title": "About",
        "text": "About this demo crawler",
        "links": ["/", "/contact"],
    },
    "/products": {
        "title": "Products",
        "text": "Our product catalogue",
        "links": ["/", "/contact"],
    },
    "/blog": {
        "title": "Blog",
        "text": "Latest articles",
        "links": ["/about"],
    },
    "/contact": {
        "title": "Contact",
        "text": "Get in touch with us",
        "links": ["/"],
    },
}


def _make_html(path: str) -> str:
    page = PAGES[path]
    link_tags = "".join(f'<a href="{href}">{href}</a>' for href in page["links"])
    return (
        f"<html><head><title>{page['title']}</title></head>"
        f"<body><p>{page['text']}</p>{link_tags}</body></html>"
    )


async def _page_handler(request: web.Request) -> web.Response:
    path = request.path
    if path not in PAGES:
        return web.Response(status=404, text="Not Found")
    return web.Response(text=_make_html(path), content_type="text/html")


async def start_server() -> web.AppRunner:
    app = web.Application()
    for path in PAGES:
        app.router.add_get(path, _page_handler)
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "localhost", PORT).start()
    return runner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

BASE = f"http://localhost:{PORT}"
START_URLS = [BASE + "/"]
MAX_PAGES = len(PAGES)


def _print_header(label: str) -> None:
    print()
    print("─" * 64)
    print(f"  {label}")
    print("─" * 64)


def _print_stats(stats: dict[str, Any], elapsed: float, saved: int) -> None:
    print(f"  Pages crawled : {stats['processed_pages']}")
    print(f"  Errors        : {stats['errors']}")
    print(f"  Saved records : {saved}")
    print(f"  Elapsed       : {elapsed:.2f} s")


# ---------------------------------------------------------------------------
# Run A — JSONStorage
# ---------------------------------------------------------------------------


async def run_json() -> int:
    _print_header("Run A — JSONStorage  →  output/day6_results.jsonl")
    print("  Format: one JSON object per line (append mode, no duplicates protection)")
    print()

    OUTPUT_DIR.mkdir(exist_ok=True)
    JSON_FILE.unlink(missing_ok=True)

    async with JSONStorage(JSON_FILE) as storage:
        async with AsyncCrawler(storage=storage) as crawler:
            t0 = time.perf_counter()
            results = await crawler.crawl(
                START_URLS, max_pages=MAX_PAGES, same_domain_only=True
            )
            elapsed = time.perf_counter() - t0
            stats = crawler.get_crawl_stats()

    saved = sum(1 for _ in JSON_FILE.open(encoding="utf-8"))
    _print_stats(stats, elapsed, saved)

    print()
    print("  Saved fields per record:")
    with JSON_FILE.open(encoding="utf-8") as f:
        first = json.loads(f.readline())
    for key, value in first.items():
        preview = repr(value)
        if len(preview) > 50:
            preview = preview[:47] + "..."
        print(f"    {key:<14} : {preview}")

    return len(results)


# ---------------------------------------------------------------------------
# Run B — CSVStorage
# ---------------------------------------------------------------------------


async def run_csv() -> int:
    _print_header("Run B — CSVStorage  →  output/day6_results.csv")
    print(
        "  Format: header row auto-detected from first record, links/metadata as JSON strings"
    )
    print()

    OUTPUT_DIR.mkdir(exist_ok=True)
    CSV_FILE.unlink(missing_ok=True)

    async with CSVStorage(CSV_FILE) as storage:
        async with AsyncCrawler(storage=storage) as crawler:
            t0 = time.perf_counter()
            results = await crawler.crawl(
                START_URLS, max_pages=MAX_PAGES, same_domain_only=True
            )
            elapsed = time.perf_counter() - t0
            stats = crawler.get_crawl_stats()

    with CSV_FILE.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        header = next(reader)
        data_rows = list(reader)

    saved = len(data_rows)
    _print_stats(stats, elapsed, saved)

    print()
    print(f"  Columns ({len(header)}): {', '.join(header)}")
    print()
    print("  Sample row (Home page):")
    home_row = next((r for r in data_rows if BASE + "/" in r[0]), data_rows[0])
    for col, val in zip(header, home_row):
        preview = val if len(val) <= 50 else val[:47] + "..."
        print(f"    {col:<14} : {preview}")

    return len(results)


# ---------------------------------------------------------------------------
# Run C — PostgreSQLStorage
# ---------------------------------------------------------------------------


async def run_postgres() -> int:
    if not POSTGRES_DSN:
        _print_header("Run C — PostgreSQLStorage  [SKIPPED]")
        print("  Set CRAWLER_POSTGRES_DSN in .env to enable this section.")
        print("  Example:  CRAWLER_POSTGRES_DSN=postgresql://localhost/crawler_dev")
        return 0

    _print_header("Run C — PostgreSQLStorage")
    print(f"  DSN    : {POSTGRES_DSN}")
    print("  Upsert : ON CONFLICT (url) DO UPDATE — re-crawling updates existing rows")
    print("  Buffer : batch_size=10 — flushes every 10 records or on close()")
    print()

    storage = PostgreSQLStorage(POSTGRES_DSN, batch_size=10)
    await storage.init_db()

    async with storage:
        async with AsyncCrawler(storage=storage) as crawler:
            t0 = time.perf_counter()
            results = await crawler.crawl(
                START_URLS, max_pages=MAX_PAGES, same_domain_only=True
            )
            elapsed = time.perf_counter() - t0
            stats = crawler.get_crawl_stats()

    # Verify upsert: crawl again — row count must stay the same.
    storage2 = PostgreSQLStorage(POSTGRES_DSN, batch_size=10)
    await storage2.init_db()
    async with storage2:
        async with AsyncCrawler(storage=storage2) as crawler2:
            await crawler2.crawl(START_URLS, max_pages=MAX_PAGES, same_domain_only=True)

    conn = await asyncpg.connect(POSTGRES_DSN)
    try:
        count = await conn.fetchval("SELECT COUNT(*) FROM crawled_pages")
        sample = await conn.fetchrow(
            "SELECT url, title, status_code, content_type, crawled_at FROM crawled_pages LIMIT 1"
        )
    finally:
        await conn.close()

    _print_stats(stats, elapsed, int(count))
    print()
    print(f"  Rows after 2 crawls : {count}  (upsert keeps unique URLs only)")
    if sample:
        print()
        print("  Sample row from DB:")
        for col in ("url", "title", "status_code", "content_type", "crawled_at"):
            print(f"    {col:<14} : {sample[col]}")

    return len(results)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    print("=" * 64)
    print("  DAY 6: DATA STORAGE — JSON Lines / CSV / PostgreSQL")
    print("=" * 64)
    print()
    print("  Test server pages:")
    for path, meta in PAGES.items():
        links_to = ", ".join(meta["links"])
        print(f"    {path:<10}  '{meta['title']}'  →  {links_to}")
    sys.stdout.flush()

    runner = await start_server()
    try:
        pages_json = await run_json()
        pages_csv = await run_csv()
        pages_pg = await run_postgres()

        print()
        print("=" * 64)
        print("  Summary")
        print("=" * 64)
        print(f"  {'Backend':<20}  {'Pages saved':<14}  Output")
        print(f"  {'-------':<20}  {'----------':<14}  ------")
        print(f"  {'JSONStorage':<20}  {pages_json:<14}  {JSON_FILE}")
        print(f"  {'CSVStorage':<20}  {pages_csv:<14}  {CSV_FILE}")
        if POSTGRES_DSN:
            print(f"  {'PostgreSQLStorage':<20}  {pages_pg:<14}  {POSTGRES_DSN}")
        else:
            print(
                f"  {'PostgreSQLStorage':<20}  {'(skipped)':<14}  set CRAWLER_POSTGRES_DSN"
            )
        print()

    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
