import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from crawler.async_crawler import AsyncCrawler

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s",
)

OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "day2_results.json"


def build_summary(result: dict[str, Any]) -> dict[str, Any]:
    return {
        "url": result["url"],
        "title": result["title"],
        "text_length": len(result["text"]),
        "links_count": len(result["links"]),
        "links": result["links"][:10],
        "images_count": len(result["images"]),
        "headings_count": sum(len(items) for items in result["headings"].values()),
        "tables_count": len(result["tables"]),
        "lists_count": len(result["lists"]),
        "parse_errors": result["parse_errors"],
    }


async def main() -> None:
    urls = [
        "https://example.com",
        "https://httpbin.org/html",
        "https://httpbin.org/status/404",
    ]

    async with AsyncCrawler(
        max_concurrent=3,
        timeout_seconds=5,
    ) as crawler:
        results = await crawler.fetch_and_parse_urls(urls)

    summaries = [build_summary(result) for result in results.values()]

    OUTPUT_DIR.mkdir(exist_ok=True)

    with OUTPUT_FILE.open("w", encoding="utf-8") as file:
        json.dump(
            summaries,
            file,
            ensure_ascii=False,
            indent=2,
        )

    for summary in summaries:
        print("\n" + "=" * 80)
        print(f"URL: {summary['url']}")
        print(f"Title: {summary['title']}")
        print(f"Text length: {summary['text_length']}")
        print(f"Links count: {summary['links_count']}")
        print(f"Images count: {summary['images_count']}")
        print(f"Headings count: {summary['headings_count']}")
        print(f"Tables count: {summary['tables_count']}")
        print(f"Lists count: {summary['lists_count']}")

        if summary["parse_errors"]:
            print("Errors:")
            for error in summary["parse_errors"]:
                print(f"- {error}")

    print(f"\nSaved results to: {OUTPUT_FILE}")


if __name__ == "__main__":
    asyncio.run(main())
