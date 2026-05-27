# API Reference

## AdvancedCrawler

High-level integration layer. Composes `AsyncCrawler` with config, sitemap discovery,
progress monitoring, and statistics.

```python
from crawler.advanced_crawler import AdvancedCrawler
from crawler.config import CrawlerConfig
```

### Constructor

```python
AdvancedCrawler(config: CrawlerConfig, storage: DataStorage | None = None)
```

`config.validate()` is called immediately — raises `ValueError` for invalid config.

Optional `storage` overrides `config.storage_type`/`config.storage_path`.

### Class methods

| Method | Returns | Description |
|---|---|---|
| `from_config(path)` | `AdvancedCrawler` | Load from YAML or JSON file |

### Instance methods

| Method | Returns | Description |
|---|---|---|
| `crawl(show_progress=True)` | `dict[url, page_data]` | Run the full crawl |
| `get_stats()` | `dict` | Crawl statistics — call after `crawl()` |
| `export_to_json(filename)` | `None` | Save **statistics** to JSON |
| `export_to_html_report(filename)` | `None` | Save **statistics** HTML report |
| `close()` | `None` | Close session and storage (idempotent) |

> **Note:** `export_to_json()` and `export_to_html_report()` export *statistics*
> (counts, speed, domains), not page content. To save page data use `storage_type`
> in config or `--output` in CLI.

### Typical usage

```python
async with AdvancedCrawler(config) as crawler:
    results = await crawler.crawl()
    stats = crawler.get_stats()
    crawler.export_to_html_report("report.html")
    crawler.export_to_json("stats.json")
```

---

## CrawlerConfig

Configuration dataclass for `AdvancedCrawler`. All fields have defaults —
at least one of `start_urls` or `sitemap_urls` must be non-empty.

```python
from crawler.config import CrawlerConfig
```

### Fields

| Field | Type | Example | Description |
|---|---|---|---|
| `start_urls` | `list[str]` | `["https://example.com"]` | Seed URLs |
| `sitemap_urls` | `list[str]` | `["https://example.com/sitemap.xml"]` | Fetch additional URLs from sitemaps |
| `max_pages` | `int` | `200` | Stop after N pages |
| `max_depth` | `int \| None` | `3` | Max link depth; `None` = unlimited |
| `max_concurrent` | `int` | `10` | Global parallel request limit |
| `requests_per_second` | `float \| None` | `2.0` | Rate cap; `None` = no limit |
| `rate_limit_per_domain` | `bool` | `true` | Per-domain or global rate bucket |
| `respect_robots` | `bool` | `true` | Obey `robots.txt` + `Crawl-delay` |
| `user_agent` | `str` | `"MyBot/1.0"` | `User-Agent` header |
| `same_domain_only` | `bool` | `true` | Only follow same-domain links |
| `include_patterns` | `list[str]` | `["/blog", "/docs"]` | Whitelist URLs by substring |
| `exclude_patterns` | `list[str]` | `["/login", ".pdf"]` | Blacklist URLs by substring |
| `storage_type` | `str` | `"json"` | `none` / `json` / `csv` / `postgres` |
| `storage_path` | `str \| None` | `"output/pages.jsonl"` | File path for `json`/`csv` |
| `postgres_dsn` | `str \| None` | `"postgresql://localhost/crawler_db"` | Connection string for `postgres` |
| `log_file` | `str \| None` | `"output/crawl.log"` | Rotating log file path |
| `log_level` | `str` | `"INFO"` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

### Class methods

```python
CrawlerConfig.load(path)        # load from YAML or JSON file; calls validate()
CrawlerConfig.from_dict(data)   # build from a plain dict
```

### Instance methods

```python
config.validate()   # raises ValueError on invalid state
```

`validate()` checks:
- `start_urls` or `sitemap_urls` must be non-empty
- `storage_type in ("json", "csv")` → `storage_path` is required
- `storage_type == "postgres"` → `postgres_dsn` is required
- `max_pages > 0`, `max_concurrent > 0`
- `log_level` must be a valid Python logging level name

---

## SitemapParser

Fetches and parses `sitemap.xml`, including recursive sitemap index files.

```python
from crawler.sitemap_parser import SitemapParser

parser = SitemapParser(session, max_recursion_depth=3)
urls: list[str] = await parser.fetch_sitemap("https://example.com/sitemap.xml")
```

Pass an already-open `aiohttp.ClientSession` — no extra connection pool is created.

On any error (network failure, HTTP non-2xx, malformed XML, depth exceeded) `fetch_sitemap`
returns `[]` and logs a warning. It never raises.

---

## CrawlerStats

Post-crawl statistics container. Populated by `AdvancedCrawler` after `crawl()`;
you normally access it via `crawler.get_stats()`.

```python
from crawler.stats import CrawlerStats
from datetime import datetime, timezone

stats = CrawlerStats(start_time=datetime.now(tz=timezone.utc))
stats.record_page(url, status_code=200, success=True)
stats.finalize(avg_latency=0.5)
d = stats.to_dict()   # JSON-serialisable dict
```

Counter keys:
- `status_codes` — HTTP status code (int) or `"unknown"` for network failures
- `domain_frequencies` — netloc extracted from URL (e.g. `"example.com"`)

---

## Exporters

Export logic is separated from `CrawlerStats` so that `CrawlerStats` stays
format-agnostic.

```python
from crawler.exporters import JsonStatsExporter, HtmlReportExporter

JsonStatsExporter().export(stats, "stats.json")
HtmlReportExporter().export(stats, "report.html")
```

`HtmlReportExporter` produces a self-contained file — inline CSS and SVG charts,
no CDN or external scripts.

---

## Page data shape

`crawl()` returns `dict[url, page_data]`. Each entry:

```python
{
    "url": str,
    "title": str | None,
    "text": str,
    "links": list[str],
    "metadata": {"description": str, "keywords": str, ...},
    "status_code": int | None,
    "content_type": str | None,
    "crawled_at": datetime,
}
```

---

## CLI

```bash
python -m crawler [OPTIONS]
```

At least one source of URLs is required: `--urls` or `--config` containing
`start_urls`/`sitemap_urls`.

### Flags

| Flag | Description |
|---|---|
| `--urls URL [URL ...]` | Seed URLs (merged with `start_urls` from config) |
| `--config FILE` | YAML or JSON config file |
| `--max-pages N` | Stop after N pages (default: 100) |
| `--max-depth N` | Max link depth from seed URLs |
| `--output FILE` | Save crawled **page data** (JSON Lines or CSV) |
| `--output-format {json,csv}` | Format for `--output` (default: `json`) |
| `--report FILE` | Write HTML **statistics** report |
| `--respect-robots` | Obey `robots.txt` |
| `--rate-limit RPS` | Max requests per second |
| `--log-file FILE` | Append logs to file (rotating, 10 MB) |
| `--log-level LEVEL` | `DEBUG` / `INFO` / `WARNING` / `ERROR` (default: `INFO`) |
| `--no-progress` | Disable the real-time progress bar |

### Output types

| Flag | Saves | Format |
|---|---|---|
| `--output FILE` | Page content (url, title, text, links, …) | JSON Lines or CSV |
| `--report FILE` | Crawl statistics (speed, status codes, domains) | HTML |

`--output` overrides `storage_type`/`storage_path` from the config file.
`--output` supports only `json` and `csv` — for PostgreSQL use the config file or Python API.

### Examples

```bash
# Save pages + HTML stats report
python -m crawler --urls https://example.com \
  --max-pages 200 --max-depth 3 \
  --output pages.jsonl \
  --report report.html \
  --respect-robots --rate-limit 2.0 \
  --log-file crawl.log --log-level INFO

# Config file with CLI overrides
python -m crawler --config config.yaml --max-pages 50 --report report.html
```

---

## AsyncCrawler — low-level API

For direct use without config files or when you need fine-grained control:

> **PostgreSQL:** When using `PostgreSQLStorage` directly with `AsyncCrawler`,
> call `await storage.init_db()` before starting the crawl to create the schema.
> `AdvancedCrawler` handles this automatically via `storage.initialize()`.

```python
from crawler.async_crawler import AsyncCrawler
from crawler.retry_strategy import RetryStrategy
from crawler.storage.json_storage import JSONStorage

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
```

---

## Error classification

HTTP responses are classified automatically and handled by `RetryStrategy`:

| Status | Exception | Retried |
|---|---|---|
| 429, 5xx | `TransientError` | yes |
| 4xx (not 429) | `PermanentError` | no |
| Connection error | `NetworkError` | yes |
| Timeout | `TransientError` | yes |
