# Async Web Crawler

A learning project for building an asynchronous web crawler with Python and `asyncio`.

## Features

- Asynchronous HTTP requests with `aiohttp`
- Concurrent page fetching
- Queue-based crawl orchestration
- Global and per-domain concurrency control
- Connection pooling with `ClientSession`
- Request timeout handling
- Error handling for network and HTTP errors
- Basic logging
- Crawl progress logging and statistics snapshots
- Sequential vs parallel performance comparison
- Async tests with `pytest`
- HTML parsing with BeautifulSoup
- Metadata extraction
- Relative URL normalization
- Crawl depth limiting
- Duplicate URL filtering
- Same-domain filtering
- Include and exclude URL patterns
- Image, heading, table and list extraction
- JSON result exporting

## Installation

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install the project in editable mode with development dependencies:

```bash
pip install -e ".[dev]"
```

## Run Demos

```bash
python demos/run_demo.py day1
python demos/run_demo.py day2
python demos/run_demo.py day3
```

## Run Tests

```bash
pytest
```

Tests cover:
- async HTTP fetching
- timeout handling
- invalid URLs
- HTML parsing
- broken HTML handling
- relative URL conversion
- link filtering
- queue behavior and deduplication
- crawl depth limits and crawl progress stats
- semaphore-based concurrency limits

## Technologies

- Python 3.11+
- asyncio
- aiohttp
- pytest
- pytest-asyncio
- BeautifulSoup4
- lxml
