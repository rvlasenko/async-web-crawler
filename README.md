# Async Web Crawler

A step-by-step project building a polite async web crawler with Python 3.11+,
`asyncio`, and `aiohttp`. Each day adds one layer on the previous one.

## Features

- Parallel crawling with configurable concurrency (global + per-domain)
- Rate limiting: requests per second, minimum delay, random jitter
- Respects `robots.txt` including `Crawl-delay` directives
- Sitemap support — regular sitemaps and recursive sitemap index files
- Automatic retries with exponential backoff and per-exception-type config
- Saves crawled pages: JSON Lines, CSV, or PostgreSQL
- Real-time progress bar with speed and ETA
- HTML statistics report: status codes, top domains, latency
- Configuration via YAML/JSON file or CLI flags

## Installation

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## Quick Start

```python
import asyncio
from crawler.advanced_crawler import AdvancedCrawler
from crawler.config import CrawlerConfig

async def main():
    config = CrawlerConfig(
        start_urls=["https://example.com"],
        max_pages=50,
        same_domain_only=True,
        storage_type="json",
        storage_path="output/pages.jsonl",
    )
    async with AdvancedCrawler(config) as crawler:
        await crawler.crawl()
        crawler.export_to_html_report("output/report.html")

asyncio.run(main())
```

Load from a config file:

```python
async with AdvancedCrawler.from_config("config.yaml") as crawler:
    await crawler.crawl()
    crawler.export_to_html_report("output/report.html")
```

## CLI

```bash
# Crawl a site and save pages to JSON Lines
python -m crawler --urls https://example.com --max-pages 100 --output pages.jsonl

# Config file with HTML statistics report
python -m crawler --config config.yaml --report report.html
```

See [docs/api_reference.md](docs/api_reference.md) for all CLI flags and examples.

## Documentation

| Document | Contents |
|---|---|
| [docs/api_reference.md](docs/api_reference.md) | AdvancedCrawler, CrawlerConfig, SitemapParser, CLI flags |
| [docs/configuration.md](docs/configuration.md) | All config fields, storage backends, PostgreSQL setup |
| [docs/architecture.md](docs/architecture.md) | Component diagram, data flow, design decisions |

## Running Tests

```bash
pytest tests/unit/ -v
pytest tests/integration/ -v
pytest -m postgres   # requires CRAWLER_TEST_POSTGRES_DSN in .env.testing
```

See [docs/configuration.md](docs/configuration.md#postgresql) for PostgreSQL test setup.

## Running Demos

```bash
python demos/day1_basic_client.py        # async vs sync fetch timing
python demos/day2_html_parser.py         # HTML parsing and metadata
python demos/day3_crawler_queue.py       # BFS with depth and domain filters
python demos/day4_polite_crawler.py      # robots.txt + rate limiting
python demos/day5_error_handling.py      # retries and error classification
python demos/day6_storage.py             # JSON Lines / CSV / PostgreSQL
python demos/day7_advanced_crawler.py    # full AdvancedCrawler integration
python demos/day7_performance_test.py    # async vs sequential benchmark
```

## Stack

- **Python 3.11+** — `asyncio`, `dataclasses`, `pathlib`, `xml.etree`
- **aiohttp** — async HTTP client, connection pooling
- **BeautifulSoup4 + lxml** — HTML parsing
- **aiofiles** — non-blocking file I/O for JSON Lines and CSV
- **asyncpg** — PostgreSQL driver with batch upserts
- **PyYAML** — YAML config file parsing
- **pytest + pytest-asyncio** — async test suite
