# Async Web Crawler

A step-by-step learning project for building a polite async web crawler
with Python 3.11+, `asyncio`, and `aiohttp`. Each day adds one layer of
functionality on top of the previous one.

## Architecture

```
AsyncCrawler
├── CrawlerQueue      — URL queue with deduplication and depth limiting
├── SemaphoreManager  — global and per-domain concurrency control
├── RateLimiter       — request delays (rps / min_delay / jitter)
├── RobotsParser      — robots.txt fetch, cache, and Crawl-delay support
├── HTMLParser        — link, metadata, image, and table extraction
├── RetryStrategy     — exponential backoff, per-type config, retry statistics
└── DataStorage       — pluggable storage: JSON Lines / CSV / PostgreSQL
```

## Project structure

```
src/crawler/
├── async_crawler.py     # orchestrates all modules, public API
├── crawler_queue.py     # BFS queue with deduplication
├── semaphore_manager.py
├── rate_limiter.py
├── robots_parser.py
├── html_parser.py
├── retry_strategy.py    # RetryStrategy, RetryTypeConfig, RetryStats
├── errors.py            # exception hierarchy + HTTP status classification
├── models.py
└── storage/
    ├── base.py          # DataStorage abstract class
    ├── models.py        # CrawledPage TypedDict
    ├── json_storage.py  # JSON Lines, one record per line
    ├── csv_storage.py   # CSV with auto header
    └── postgres_storage.py  # asyncpg, buffered batch upserts

demos/                   # runnable examples per day
tests/
├── unit/                # pure logic: queue, parser, rate limiter, retry math
└── integration/         # live aiohttp server + storage backends
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

```python
import asyncio
from crawler.async_crawler import AsyncCrawler
from crawler.retry_strategy import RetryStrategy
from crawler.storage.json_storage import JSONStorage

async def main():
    async with JSONStorage("results.jsonl") as storage:
        async with AsyncCrawler(
            max_concurrent=5,
            min_delay=0.5,
            jitter=0.2,
            respect_robots_txt=True,
            retry_strategy=RetryStrategy(max_retries=3, base_delay=1.0, backoff_factor=2.0),
            storage=storage,
        ) as crawler:
            results = await crawler.crawl(
                start_urls=["https://example.com"],
                max_pages=20,
                same_domain_only=True,
            )
    print(crawler.get_crawl_stats())

asyncio.run(main())
```

## Demos

```bash
python -m demos.run_demo day1   # basic async fetch, timing comparison
python -m demos.run_demo day2   # HTML parsing, metadata, JSON export
python -m demos.run_demo day3   # BFS crawl with depth and domain filters
python -m demos.run_demo day4   # robots.txt + rate limiting (hits httpbin.org)
python -m demos.run_demo day5   # error handling + retry strategies (local server)
python -m demos.run_demo day6   # storage backends: JSON Lines, CSV, PostgreSQL
```

Day 6 uses a local test server and requires no external services by default.
PostgreSQL section activates automatically when `CRAWLER_POSTGRES_DSN` is set in `.env`:

```bash
# .env
CRAWLER_POSTGRES_DSN=postgresql://localhost/crawler_dev
```

## Tests

```bash
pytest                                    # run all (postgres tests skipped if no DSN)
pytest tests/unit/ -v                     # unit tests only
pytest tests/integration/ -v              # integration tests only
pytest tests/unit/test_rate_limiter.py    # specific module
pytest -m postgres                        # PostgreSQL integration tests only
```

PostgreSQL integration tests require a separate test database:

```bash
createdb crawler_test
cp .env.testing.example .env.testing   # fill in CRAWLER_TEST_POSTGRES_DSN
pytest -m postgres                     # .env.testing is loaded automatically
```

Unit tests cover: queue deduplication, HTML parsing edge cases, rate limiter
math, robots.txt parsing, semaphore enforcement, error classification,
retry backoff math, per-type retry config, retry statistics, storage
buffering and SQL generation.

Integration tests cover: HTTP errors, timeouts, retry on 5xx/timeout,
no retry on 4xx, exponential backoff delays, timeout escalation per retry,
crawl depth limits, rate limiting, robots.txt enforcement, User-Agent
rotation, crawl statistics, storage backends (JSON/CSV/PostgreSQL),
storage errors do not stop the crawl.

## Storage

Pass any `DataStorage` instance to `AsyncCrawler` — pages are saved automatically after each successful crawl:

```python
from crawler.storage.json_storage import JSONStorage
from crawler.storage.csv_storage import CSVStorage
from crawler.storage.postgres_storage import PostgreSQLStorage

# JSON Lines — one record per line, append mode
async with JSONStorage("results.jsonl") as storage:
    crawler = AsyncCrawler(storage=storage)

# CSV — header auto-detected from first record
async with CSVStorage("results.csv") as storage:
    crawler = AsyncCrawler(storage=storage)

# PostgreSQL — buffered batch upserts, ON CONFLICT (url) DO UPDATE
storage = PostgreSQLStorage("postgresql://localhost/crawler_dev", batch_size=50)
await storage.init_db()
async with storage:
    crawler = AsyncCrawler(storage=storage)
```

Storage errors are logged but do not stop the crawl. The caller is responsible
for closing the storage — the crawler does not call `close()` on it.

## Error handling

HTTP responses are classified automatically:

| Status | Exception | Retried |
|---|---|---|
| 429, 5xx | `TransientError` | yes |
| 4xx (not 429) | `PermanentError` | no |
| connection error | `NetworkError` | yes |
| timeout | `TransientError` | yes |

```python
from crawler.retry_strategy import RetryStrategy, RetryTypeConfig
from crawler.errors import TransientError, NetworkError

strategy = RetryStrategy(
    max_retries=3,
    base_delay=1.0,
    backoff_factor=2.0,
    per_type_config={
        TransientError: RetryTypeConfig(max_retries=2, base_delay=0.5),
        NetworkError:   RetryTypeConfig(max_retries=5, base_delay=0.1),
    },
)
# After use: strategy.stats has total_retries, errors_by_type, avg_delay_per_retry, …
```

## Stack

- **Python 3.11+** — `asyncio`, `dataclasses`, `pathlib`
- **aiohttp** — async HTTP client, connection pooling
- **BeautifulSoup4 + lxml** — HTML parsing
- **aiofiles** — non-blocking file writes for JSON Lines and CSV
- **asyncpg** — PostgreSQL driver with batch upserts
- **pytest + pytest-asyncio** — async test suite
