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
└── RetryStrategy     — exponential backoff, per-type config, retry statistics
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
└── models.py

demos/                   # runnable examples per day
tests/
├── unit/                # pure logic: queue, parser, rate limiter, retry math
└── integration/         # live aiohttp server: HTTP errors, timeouts, crawl flows
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

async def main():
    async with AsyncCrawler(
        max_concurrent=5,
        min_delay=0.5,
        jitter=0.2,
        respect_robots_txt=True,
        retry_strategy=RetryStrategy(max_retries=3, base_delay=1.0, backoff_factor=2.0),
    ) as crawler:
        results = await crawler.crawl(
            start_urls=["https://example.com"],
            max_pages=20,
            same_domain_only=True,
        )
    print(crawler.get_crawl_stats())
    if crawler.retry_strategy:
        print(crawler.retry_strategy.stats)

asyncio.run(main())
```

## Demos

```bash
python demos/run_demo.py day1   # basic async fetch, timing comparison
python demos/run_demo.py day2   # HTML parsing, metadata, JSON export
python demos/run_demo.py day3   # BFS crawl with depth and domain filters
python demos/run_demo.py day4   # robots.txt + rate limiting (hits httpbin.org)
python demos/run_demo.py day5   # error handling + retry strategies (local server)
```

## Tests

```bash
pytest                                    # run all
pytest tests/unit/ -v                     # unit tests only
pytest tests/integration/ -v              # integration tests only
pytest tests/unit/test_rate_limiter.py    # specific module
```

Unit tests cover: queue deduplication, HTML parsing edge cases, rate limiter
math, robots.txt parsing, semaphore enforcement, error classification,
retry backoff math, per-type retry config, retry statistics.

Integration tests cover: HTTP errors, timeouts, retry on 5xx/timeout,
no retry on 4xx, exponential backoff delays, timeout escalation per retry,
crawl depth limits, rate limiting, robots.txt enforcement, User-Agent
rotation, crawl statistics.

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
- **pytest + pytest-asyncio** — async test suite
