"""Day 7 demo: AdvancedCrawler with sitemap, progress monitor, and HTML report.

Starts a local aiohttp server with 10 pages and a sitemap.xml,
then crawls it using AdvancedCrawler and exports an HTML report.

Run:
    python demos/day7_advanced_crawler.py
"""

import asyncio
import logging
from pathlib import Path

from aiohttp import web

from crawler.advanced_crawler import AdvancedCrawler
from crawler.config import CrawlerConfig

PORT = 18777
OUTPUT_DIR = Path("output")
OUTPUT_DIR.mkdir(exist_ok=True)

N_PAGES = 10


# ---------------------------------------------------------------------------
# Local demo server
# ---------------------------------------------------------------------------


def build_app(base_url: str) -> web.Application:
    """Build a small site with N_PAGES and a sitemap."""
    app = web.Application()

    async def index(r: web.Request) -> web.Response:
        links = "\n".join(
            f'<li><a href="{base_url}/page/{i}">Page {i}</a></li>'
            for i in range(1, N_PAGES + 1)
        )
        return web.Response(
            text=f"<html><body><h1>Home</h1><ul>{links}</ul></body></html>",
            content_type="text/html",
        )

    async def page(r: web.Request) -> web.Response:
        n = r.match_info["n"]
        prev_link = (
            f'<a href="{base_url}/page/{int(n) - 1}">Prev</a>' if int(n) > 1 else ""
        )
        next_link = (
            f'<a href="{base_url}/page/{int(n) + 1}">Next</a>'
            if int(n) < N_PAGES
            else ""
        )
        return web.Response(
            text=(
                f"<html><body><h1>Page {n}</h1>"
                f"<a href='{base_url}/'>Home</a> {prev_link} {next_link}"
                f"<p>Content of page {n}.</p></body></html>"
            ),
            content_type="text/html",
        )

    async def sitemap(r: web.Request) -> web.Response:
        ns = "http://www.sitemaps.org/schemas/sitemap/0.9"
        locs = "\n".join(
            f"  <url><loc>{base_url}/page/{i}</loc></url>"
            for i in range(1, N_PAGES + 1)
        )
        xml = (
            f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<urlset xmlns="{ns}">\n{locs}\n</urlset>'
        )
        return web.Response(text=xml, content_type="application/xml")

    app.router.add_get("/", index)
    app.router.add_get("/page/{n}", page)
    app.router.add_get("/sitemap.xml", sitemap)
    return app


async def start_server() -> tuple[web.AppRunner, str]:
    base_url = f"http://localhost:{PORT}"
    app = build_app(base_url)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "localhost", PORT)
    await site.start()
    return runner, base_url


# ---------------------------------------------------------------------------
# Demo
# ---------------------------------------------------------------------------


async def main() -> None:
    logging.basicConfig(level=logging.WARNING)  # keep demo output clean

    runner, base_url = await start_server()

    try:
        print(f"Demo server running at {base_url}")
        print(f"Crawling {N_PAGES} pages + sitemap discovery …\n")

        # ---- Variant 1: construct config directly ----
        config = CrawlerConfig(
            start_urls=[f"{base_url}/"],
            sitemap_urls=[f"{base_url}/sitemap.xml"],
            max_pages=20,
            same_domain_only=True,
            log_level="WARNING",
        )

        async with AdvancedCrawler(config) as crawler:
            await crawler.crawl(show_progress=True)

        stats = crawler.get_stats()
        report_path = OUTPUT_DIR / "day7_report.html"
        crawler.export_to_html_report(report_path)
        crawler.export_to_json(OUTPUT_DIR / "day7_stats.json")

        print(f"\nCrawled    : {stats['total_pages']} pages")
        print(f"Successful : {stats['successful']}")
        print(f"Failed     : {stats['failed']}")
        print(f"Speed      : {stats['pages_per_second']:.1f} pg/s")
        print(f"Duration   : {stats['elapsed_seconds']:.2f}s")
        print(f"\nHTML report : {report_path}")
        print(f"Stats JSON  : {OUTPUT_DIR / 'day7_stats.json'}")

        # ---- Variant 2: from_config (commented out — requires config.yaml) ----
        # async with AdvancedCrawler.from_config("config.yaml") as crawler:
        #     await crawler.crawl()
        #     crawler.export_to_html_report("output/report.html")

    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
