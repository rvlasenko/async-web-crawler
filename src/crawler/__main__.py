"""CLI entry point for the async web crawler.

Usage:
    python -m crawler --urls https://example.com --max-pages 100
    python -m crawler --config config.yaml --report report.html
    crawler --urls https://example.com  (after pip install -e .)
"""

import argparse
import asyncio
import sys
from pathlib import Path

from crawler.advanced_crawler import AdvancedCrawler
from crawler.config import CrawlerConfig


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m crawler",
        description="Async breadth-first web crawler with rate limiting, robots.txt support, and structured output.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Output options:
  --output saves crawled PAGE DATA  (url, title, text, links, ...)
  --report creates an HTML STATS REPORT (speed, status codes, top domains)

Examples:
  %(prog)s --urls https://example.com --max-pages 50 --output pages.jsonl
  %(prog)s --config config.yaml --report report.html --no-progress
  %(prog)s --urls https://example.com --respect-robots --rate-limit 1.0 --log-file crawl.log
""",
    )

    p.add_argument(
        "--urls",
        nargs="+",
        metavar="URL",
        help="One or more seed URLs to crawl.",
    )
    p.add_argument(
        "--config",
        metavar="FILE",
        help="Path to a YAML or JSON config file.",
    )
    p.add_argument(
        "--max-pages",
        type=int,
        metavar="N",
        help="Stop after N successfully crawled pages (default: 100).",
    )
    p.add_argument(
        "--max-depth",
        type=int,
        metavar="N",
        help="Maximum link depth from seed URLs.",
    )

    out = p.add_argument_group("page output (crawled page data)")
    out.add_argument(
        "--output",
        metavar="FILE",
        help="Save crawled pages to this file (JSON Lines or CSV).",
    )
    out.add_argument(
        "--output-format",
        choices=["json", "csv"],
        default="json",
        dest="output_format",
        help="Format for --output (default: json).",
    )

    rep = p.add_argument_group("stats report")
    rep.add_argument(
        "--report",
        metavar="FILE",
        help="Write an HTML statistics report to this file.",
    )

    crawl = p.add_argument_group("crawl behaviour")
    crawl.add_argument(
        "--respect-robots",
        action="store_true",
        help="Fetch and obey robots.txt files.",
    )
    crawl.add_argument(
        "--rate-limit",
        type=float,
        metavar="RPS",
        dest="requests_per_second",
        help="Maximum requests per second.",
    )
    crawl.add_argument(
        "--retry-max-retries",
        type=int,
        metavar="N",
        dest="retry_max_retries",
        help="Maximum retry attempts per URL (default: 3). Set 0 to disable retries.",
    )

    log = p.add_argument_group("logging")
    log.add_argument("--log-file", metavar="FILE", help="Write logs to this file.")
    log.add_argument(
        "--log-level",
        default=None,
        metavar="LEVEL",
        help="Log level: DEBUG, INFO, WARNING, ERROR (default: INFO).",
    )
    log.add_argument(
        "--no-progress",
        action="store_true",
        help="Disable the real-time progress bar.",
    )

    return p


def main() -> int:
    """CLI entry point. Returns exit code (0 = success, 1 = error)."""
    parser = build_parser()
    args = parser.parse_args()

    # Load config file if provided, otherwise start with an empty config
    if args.config:
        try:
            config = CrawlerConfig.load(args.config)
        except FileNotFoundError:
            print(f"Error: config file not found: {args.config}", file=sys.stderr)
            return 1
        except (ValueError, ImportError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
    else:
        config = CrawlerConfig(start_urls=[])

    # Apply CLI overrides in order of priority
    if args.urls:
        # Merge CLI URLs after config URLs, deduplicated
        config.start_urls = list(dict.fromkeys(config.start_urls + args.urls))
    if args.max_pages is not None:
        config.max_pages = args.max_pages
    if args.max_depth is not None:
        config.max_depth = args.max_depth
    if args.requests_per_second is not None:
        config.requests_per_second = args.requests_per_second
    if args.retry_max_retries is not None:
        config.retry_max_retries = args.retry_max_retries
    if args.respect_robots:
        config.respect_robots = True
    if args.log_file:
        config.log_file = args.log_file
    if args.log_level:
        config.log_level = args.log_level

    # --output overrides config storage entirely (json/csv only via CLI)
    if args.output:
        config.storage_path = args.output
        config.storage_type = args.output_format

    try:
        config.validate()
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    # Ensure output directory exists for file outputs
    if config.storage_path:
        Path(config.storage_path).parent.mkdir(parents=True, exist_ok=True)

    show_progress = not args.no_progress

    async def run() -> int:
        async with AdvancedCrawler(config) as crawler:
            results = await crawler.crawl(show_progress=show_progress)

            if args.report:
                Path(args.report).parent.mkdir(parents=True, exist_ok=True)
                crawler.export_to_html_report(args.report)
                print(f"Report saved to {args.report}")

        print(
            f"Done — {len(results)} pages crawled.",
            file=sys.stderr if show_progress else sys.stdout,
        )
        return 0

    try:
        return asyncio.run(run())
    except KeyboardInterrupt:
        print("\nInterrupted.", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
