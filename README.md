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
└── HTMLParser        — link, metadata, image, and table extraction
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
└── models.py

demos/                   # runnable examples per day
tests/                   # pytest suite, one file per module/day
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

```python
import asyncio
from crawler.async_crawler import AsyncCrawler

async def main():
    async with AsyncCrawler(
        max_concurrent=5,
        min_delay=0.5,
        jitter=0.2,
        respect_robots_txt=True,
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
python demos/run_demo.py day1   # basic async fetch, timing comparison
python demos/run_demo.py day2   # HTML parsing, metadata, JSON export
python demos/run_demo.py day3   # BFS crawl with depth and domain filters
python demos/run_demo.py day4   # robots.txt + rate limiting (hits httpbin.org)
```

## Tests

```bash
pytest                                         # run all
pytest tests/test_day4_rate_limiter.py -v      # specific module
```

Coverage: HTTP errors, timeouts, HTML edge cases, queue deduplication,
depth limits, semaphore enforcement, rate limiter math, robots.txt parsing,
User-Agent rotation, crawl statistics.

## Stack

- **Python 3.11+** — `asyncio`, `dataclasses`, `pathlib`
- **aiohttp** — async HTTP client, connection pooling
- **BeautifulSoup4 + lxml** — HTML parsing
- **pytest + pytest-asyncio** — async test suite
