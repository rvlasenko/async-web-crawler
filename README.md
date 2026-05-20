# Async Web Crawler

A learning project for building an asynchronous web crawler with Python and `asyncio`.

## Features

- Asynchronous HTTP requests with `aiohttp`
- Concurrent page fetching
- Connection pooling with `ClientSession`
- Request timeout handling
- Error handling for network and HTTP errors
- Basic logging
- Sequential vs parallel performance comparison
- Async tests with `pytest`
- HTML parsing with BeautifulSoup
- Metadata extraction
- Relative URL normalization
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
python -m demos.run_demo day1
python -m demos.run_demo day2
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

## Technologies

- Python 3.11+
- asyncio
- aiohttp
- pytest
- pytest-asyncio
- BeautifulSoup4
- lxml
