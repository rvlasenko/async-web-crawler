import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any

from crawler.async_crawler import AsyncCrawler

PROJECT_ROOT = Path(__file__).resolve().parents[1]

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

START_URLS = [
    "https://httpbin.org/links/5/0",
]
OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "day3_results.json"


def build_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": result["url"],
        "title": result["title"],
        "text_length": len(result["text"]),
        "links_count": len(result["links"]),
        "links": result["links"][:10],
        "parse_errors": result["parse_errors"],
    }


def print_summary(crawler: AsyncCrawler) -> None:
    stats = crawler.get_crawl_stats()

    print("\nCRAWL SUMMARY")
    print(f"Processed pages: {stats['processed_pages']}")
    print(f"Errors: {stats['errors']}")
    print(f"Queued pages: {stats['queued']}")
    print(f"Active tasks: {stats['active_tasks']}")
    print(f"Speed: {stats['pages_per_second']:.2f} pages/s")


async def main() -> None:
    async with AsyncCrawler(
        max_concurrent=4,
        timeout_seconds=5,
        max_depth=2,
    ) as crawler:
        results = await crawler.crawl(
            start_urls=START_URLS,
            max_pages=10,
            same_domain_only=True,
            show_progress=True,
        )

    summaries = [build_summary(result) for result in results.values()]

    OUTPUT_DIR.mkdir(exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            {
                "start_urls": START_URLS,
                "max_pages": 10,
                "max_depth": 2,
                "results": summaries,
            },
            file,
            ensure_ascii=False,
            indent=2,
        )

    print_summary(crawler)

    for summary in summaries:
        print("\n" + "=" * 80)
        print(f"URL: {summary['url']}")
        print(f"Title: {summary['title']}")
        print(f"Text length: {summary['text_length']}")
        print(f"Links count: {summary['links_count']}")

        if summary["parse_errors"]:
            print("Errors:")
            for error in summary["parse_errors"]:
                print(f"- {error}")

    print(f"\nSaved results to: {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
