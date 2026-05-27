# Configuration Guide

## Config file

Copy `config.yaml.example` to `config.yaml` and adjust:

```bash
cp config.yaml.example config.yaml
```

Supported formats: YAML (`.yaml`, `.yml`) and JSON (`.json`).

Load via Python API or CLI:

```python
CrawlerConfig.load("config.yaml")
AdvancedCrawler.from_config("config.yaml")
```

```bash
python -m crawler --config config.yaml
```

---

## All fields

| Field | Example | Description |
|---|---|---|
| `start_urls` | `["https://example.com"]` | Seed URLs. Required if no `sitemap_urls`. |
| `sitemap_urls` | `["https://example.com/sitemap.xml"]` | Fetch additional URLs from these sitemaps. |
| `max_pages` | `200` | Stop after N pages. |
| `max_depth` | `3` | Max link depth. `null` = unlimited. |
| `max_concurrent` | `10` | Global parallel request limit. |
| `requests_per_second` | `2.0` | Rate cap. `null` = no limit. |
| `rate_limit_per_domain` | `true` | Per-domain or global rate bucket. |
| `respect_robots` | `true` | Obey `robots.txt` + `Crawl-delay`. |
| `user_agent` | `"MyBot/1.0"` | `User-Agent` header. |
| `same_domain_only` | `true` | Only follow same-domain links. |
| `include_patterns` | `["/blog", "/docs"]` | Whitelist URLs by substring. |
| `exclude_patterns` | `["/login", ".pdf"]` | Blacklist URLs by substring. |
| `storage_type` | `"json"` | `none` / `json` / `csv` / `postgres` |
| `storage_path` | `"output/pages.jsonl"` | File path for `json` or `csv`. |
| `postgres_dsn` | `"postgresql://localhost/crawler_db"` | Connection string for `postgres`. |
| `log_file` | `"output/crawl.log"` | Rotating log file path. |
| `log_level` | `"INFO"` | `DEBUG` / `INFO` / `WARNING` / `ERROR` |

---

## Storage backends

### JSON Lines (`storage_type: json`)

```yaml
storage_type: json
storage_path: output/pages.jsonl
```

Each crawled page is appended as one JSON object per line. The file is created
if it does not exist; parent directories must exist.

### CSV (`storage_type: csv`)

```yaml
storage_type: csv
storage_path: output/pages.csv
```

First row is the CSV header. Each crawled page adds one row.

### PostgreSQL (`storage_type: postgres`) {#postgresql}

```yaml
storage_type: postgres
postgres_dsn: postgresql://user:password@localhost:5432/crawler_db
```

DSN format: `postgresql://[user[:password]@][host][:port]/database`

#### Database setup

Create the database before running the crawler:

```bash
createdb crawler_db
```

The `crawled_pages` table and its index are **created automatically** on the first
`crawl()` call — no manual schema setup is needed.

Re-crawling the same URL updates the existing row (`ON CONFLICT DO UPDATE`),
so repeated runs against the same database are safe.

#### Verifying connectivity

Before running the crawler, confirm PostgreSQL is accepting connections:

```bash
pg_isready -d crawler_db
# crawler_db:5432 - accepting connections
```

If the database is unavailable when `crawl()` starts, `asyncpg.connect()` raises
`asyncpg.exceptions.ConnectionDoesNotExistError` (or an OS-level connection refused
error). The exception propagates out of `crawl()` — no pages are saved, no partial
state is left in the database.

#### Environment files

The project uses two separate env files for PostgreSQL credentials:

| File | Variable |
|---|---|
| `.env` | `CRAWLER_POSTGRES_DSN` |
| `.env.testing` | `CRAWLER_TEST_POSTGRES_DSN` |

Setup for development and demos:

```bash
cp .env.example .env
# Edit .env:
#   CRAWLER_POSTGRES_DSN=postgresql://localhost/crawler_db
```

> **Note:** `CrawlerConfig` does **not** read env vars automatically.
> Set `postgres_dsn` directly in `config.yaml` or in Python code.
> The env var is only consumed by demo scripts that call `os.getenv()` explicitly.

#### PostgreSQL integration tests

The integration tests need a dedicated test database — do not point them at a
development or production database.

```bash
# 1. Create a test-only database
createdb crawler_test

# 2. Copy and fill in the DSN
cp .env.testing.example .env.testing
# Edit .env.testing:
#   CRAWLER_TEST_POSTGRES_DSN=postgresql://localhost/crawler_test

# 3. Run PostgreSQL tests only
pytest -m postgres -v

# 4. Exclude PostgreSQL tests
pytest -m "not postgres"
```

The test fixture drops and recreates `crawled_pages` before each test —
tests are fully isolated and non-destructive to other tables.

### No storage (`storage_type: none`)

Pages are crawled and returned from `crawl()` as an in-memory dict but not
persisted anywhere. Useful when you only need the result dict.

---

## Minimal working config

```yaml
start_urls:
  - https://example.com
max_pages: 50
same_domain_only: true
storage_type: json
storage_path: output/pages.jsonl
```

---

## Full annotated example

```yaml
# Seed URLs — at least one of start_urls or sitemap_urls is required
start_urls:
  - https://example.com

# Optional: fetch extra URLs from sitemap before crawling
sitemap_urls:
  - https://example.com/sitemap.xml

# Crawl limits
max_pages: 200          # stop after 200 pages
max_depth: 3            # follow links up to depth 3 (null = unlimited)

# Concurrency and rate limiting
max_concurrent: 10               # up to 10 simultaneous requests
requests_per_second: 5.0         # max 5 req/s (null = no limit)
rate_limit_per_domain: true      # bucket per domain (false = global bucket)

# Politeness
respect_robots: true             # obey robots.txt and Crawl-delay
user_agent: "MyBot/1.0"

# Scope
same_domain_only: true
include_patterns: []             # empty = no whitelist
exclude_patterns:
  - /login
  - /logout
  - .pdf

# Storage
storage_type: json               # none | json | csv | postgres
storage_path: output/pages.jsonl

# Logging
log_file: output/crawl.log       # null = no file logging
log_level: INFO                  # DEBUG | INFO | WARNING | ERROR
```

---

## CLI override rule

When `--output FILE` is passed on the command line it always overrides
`storage_type` and `storage_path` from the config file, even if the config
specifies `postgres`:

```bash
python -m crawler --config config.yaml --output pages.jsonl --output-format json
```

`--output` supports only `json` (JSON Lines) and `csv`.
For PostgreSQL use the config file or the Python API directly.

---

## Output files

| File | Content |
|---|---|
| `pages.jsonl` | Crawled pages: url, title, text, links, status_code, crawled_at |
| `pages.csv` | Same content in CSV format |
| `report.html` | Crawl statistics: speed, status codes, top domains |
| `crawl.log` | Structured log with timestamps and module names |

The rotating log file is capped at 10 MB per file with 5 backups.
