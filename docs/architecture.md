# Architecture

## Component diagram

```
AdvancedCrawler              ← high-level integration layer
├── CrawlerConfig            ← YAML/JSON configuration
├── SitemapParser            ← sitemap.xml discovery
├── ProgressMonitor          ← real-time stderr progress bar
├── CrawlerStats             ← post-crawl statistics container
├── JsonStatsExporter        ← stats → JSON file
├── HtmlReportExporter       ← stats → self-contained HTML report
└── AsyncCrawler             ← core crawl engine
    ├── CrawlerQueue         ← BFS queue with deduplication
    ├── SemaphoreManager     ← global + per-domain concurrency limits
    ├── RateLimiter          ← rps / min_delay / jitter
    ├── RobotsParser         ← robots.txt cache + Crawl-delay
    ├── HTMLParser           ← link, metadata, image extraction
    ├── RetryStrategy        ← exponential backoff per exception type
    └── DataStorage          ← JSON Lines / CSV / PostgreSQL backends
```

## Module layout

```
src/crawler/
├── advanced_crawler.py   ← AdvancedCrawler (integration layer)
├── async_crawler.py      ← AsyncCrawler (core engine)
├── config.py             ← CrawlerConfig
├── exporters.py          ← JsonStatsExporter, HtmlReportExporter
├── logging_config.py     ← setup_logging()
├── monitoring.py         ← ProgressMonitor
├── sitemap_parser.py     ← SitemapParser
├── stats.py              ← CrawlerStats
├── __main__.py           ← CLI entry point
├── crawler_queue.py
├── html_parser.py
├── rate_limiter.py
├── retry_strategy.py
├── robots_parser.py
├── semaphore_manager.py
└── storage/
    ├── base.py           ← DataStorage (ABC)
    ├── json_storage.py
    ├── csv_storage.py
    └── postgres_storage.py
```

## Data flow in `crawl()`

```
CrawlerConfig
    │
    ├─ setup_logging(level, log_file)
    │
    ├─ _build_storage() ──► DataStorage.initialize()
    │       └── json / csv / postgres / None
    │
    └─ AsyncCrawler(inner)
           │
           └─ async with inner:          ← opens aiohttp.ClientSession
                  │
                  ├─ SitemapParser(inner.session)
                  │       └─ fetch_sitemap() × N  ──► extra seed URLs
                  │
                  └─ ProgressMonitor (background asyncio.Task)
                         │
                         └─ inner.crawl(all_start_urls)
                                │
                                ├─ page fetched ──► DataStorage.save()
                                └─ results dict
           │
           └─ CrawlerStats.record_page() × N
                  └─ finalize(avg_latency)
                         │
                         ├─ export_to_html_report()
                         └─ export_to_json()
```

## Design decisions

**Composition over inheritance.** `AdvancedCrawler` holds an `AsyncCrawler` instance
rather than subclassing it. This keeps the public API small and avoids leaking
low-level methods like `get_crawl_stats()` that return raw dicts with internal keys.

**Session reuse.** `SitemapParser` receives `inner.session` — the
`aiohttp.ClientSession` already open inside `async with inner:`. No second
connection pool is created for sitemap fetching.

**Export separated from stats.** `CrawlerStats` is a pure data container with
`to_dict()`. `JsonStatsExporter` and `HtmlReportExporter` own the format-specific
logic. Adding a new export format requires only a new exporter class, not changes
to `CrawlerStats`.

**Mutable config.** `CrawlerConfig` is not frozen so the CLI can directly mutate
fields after loading (e.g. `config.storage_path = args.output`). The alternative —
building a new config object with overrides — would require re-running `validate()`
and is more verbose for the CLI use case.

**ProgressMonitor as async context manager.** The background `asyncio.Task` is
created in `__aenter__` and cancelled in `__aexit__`. This guarantees the task is
cleaned up even if `crawl()` raises an exception partway through.

**Storage initialization hook.** `DataStorage.initialize()` is a no-op by default.
`PostgreSQLStorage` overrides it to run `CREATE TABLE IF NOT EXISTS`. `AdvancedCrawler`
calls `await storage.initialize()` before starting the crawl, so PostgreSQL users
never need to call `init_db()` manually when using the high-level API.
