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

## Project Structure

```text
async-web-crawler/
├── demos/
├── src/
│   └── crawler/
├── tests/
├── pyproject.toml
└── requirements.txt
```

## Installation

Create and activate a virtual environment:

```bash
python -m venv .venv
source .venv/bin/activate
```

Install dependencies:

```bash
pip install -e .
```

## Run Demo

```bash
python demos/day1_basic_client.py
```

The demo will:

- fetch multiple URLs
- handle errors
- print request statuses
- compare sequential vs parallel execution time

## Run Tests

```bash
pytest
```

## Technologies

- Python 3.11+
- asyncio
- aiohttp
- pytest
- pytest-asyncio