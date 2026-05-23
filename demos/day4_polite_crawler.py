import asyncio
import json
import logging
import sys
import time
from pathlib import Path
from typing import Any

from crawler.async_crawler import AsyncCrawler

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

START_URLS = [
    "https://httpbin.org/links/5/0",
    "https://httpbin.org/deny",
]
MAX_PAGES = 10
MIN_DELAY = 0.5
USER_AGENT = "AsyncCrawler/1.0"
OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "day4_results.json"

SEP = "-" * 60


def print_header() -> None:
    print("=" * 60)
    print("  DAY 4: POLITE CRAWLER — robots.txt + rate limiting")
    print("=" * 60, flush=True)


def print_config() -> None:
    print("\nConfiguration")
    print(f"  Start URLs  : {START_URLS[0]}")
    print(f"              + {START_URLS[1]}  ← blocked by robots.txt")
    print(f"  Max pages   : {MAX_PAGES}")
    print(f"  Rate limit  : {1 / MIN_DELAY:.0f} req/s  (min_delay={MIN_DELAY}s)")
    print("  Robots.txt  : respected")
    print(f"  User-Agent  : {USER_AGENT}")
    print(f"\n{SEP}")
    print("Crawling... (this may take a few seconds)")
    print(SEP, flush=True)


def print_results(
    processed: dict[str, dict[str, Any]],
    failed: dict[str, str],
) -> None:
    print(f"\n{SEP}")
    print("Crawl Results")
    print(SEP)

    all_urls = sorted(set(processed) | set(failed))

    for url in all_urls:
        if url in processed:
            print(f"  ✓  {url}")
        else:
            error = failed[url]
            print(f"  ✗  {url}")
            print(f"       [{error}]")

    if not all_urls:
        print("  (no URLs processed)")


def print_stats(stats: dict[str, Any], total_time: float) -> None:
    print(f"\n{SEP}")
    print("Statistics")
    print(SEP)
    print(f"  Pages processed   : {stats['processed_pages']}")
    print(f"  Errors (HTTP/net) : {stats['errors']}")
    print(f"  Blocked by robots : {stats['blocked_by_robots']}")
    print()
    print(f"  Speed             : {stats['pages_per_second']:.2f} pages/s")
    print(f"  Avg latency       : {stats['avg_latency_seconds']:.3f} s")
    print(f"  Total time        : {total_time:.2f} s")
    print(SEP)


async def main() -> None:
    print_header()
    print_config()

    async with AsyncCrawler(
        max_concurrent=3,
        timeout_seconds=10,
        min_delay=MIN_DELAY,
        respect_robots_txt=True,
        user_agent=USER_AGENT,
    ) as crawler:
        start = time.perf_counter()

        results = await crawler.crawl(
            start_urls=START_URLS,
            max_pages=MAX_PAGES,
            same_domain_only=True,
            show_progress=False,
        )

        total_time = time.perf_counter() - start
        stats = crawler.get_crawl_stats()
        failed = dict(crawler.failed_urls)

    print_results(results, failed)
    print_stats(stats, total_time)

    OUTPUT_DIR.mkdir(exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as f:
        json.dump(
            {
                "config": {
                    "start_urls": START_URLS,
                    "max_pages": MAX_PAGES,
                    "min_delay": MIN_DELAY,
                    "respect_robots_txt": True,
                    "user_agent": USER_AGENT,
                },
                "stats": stats,
                "processed": list(results.keys()),
                "failed": failed,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    print(f"\nSaved to: {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
