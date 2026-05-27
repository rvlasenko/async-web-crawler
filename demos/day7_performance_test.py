"""Day 7 performance test: async crawl vs sequential baseline.

Starts a local server with N dynamically generated pages, measures:
  - Sequential crawl time using urllib.request (50 pages)
  - Async crawl time + peak memory via tracemalloc

Run:
    python demos/day7_performance_test.py
"""

import asyncio
import time
import tracemalloc
import urllib.request

from aiohttp import web

from crawler.advanced_crawler import AdvancedCrawler
from crawler.config import CrawlerConfig

PORT = 18778


# ---------------------------------------------------------------------------
# Dynamic test server
# ---------------------------------------------------------------------------


def build_app(base_url: str, n_pages: int) -> web.Application:
    app = web.Application()

    async def index(r: web.Request) -> web.Response:
        links = " ".join(
            f'<a href="{base_url}/page/{i}">p{i}</a>' for i in range(1, n_pages + 1)
        )
        return web.Response(
            text=f"<html><body><h1>Index</h1>{links}</body></html>",
            content_type="text/html",
        )

    async def page(r: web.Request) -> web.Response:
        n = int(r.match_info["n"])
        prev = f'<a href="{base_url}/page/{n - 1}">prev</a>' if n > 1 else ""
        nxt = f'<a href="{base_url}/page/{n + 1}">next</a>' if n < n_pages else ""
        return web.Response(
            text=f"<html><body><h1>Page {n}</h1>{prev} {nxt}</body></html>",
            content_type="text/html",
        )

    app.router.add_get("/", index)
    app.router.add_get("/page/{n}", page)
    return app


async def start_server(n_pages: int) -> tuple[web.AppRunner, str]:
    base_url = f"http://localhost:{PORT}"
    runner = web.AppRunner(build_app(base_url, n_pages))
    await runner.setup()
    await web.TCPSite(runner, "localhost", PORT).start()
    return runner, base_url


# ---------------------------------------------------------------------------
# Baselines
# ---------------------------------------------------------------------------


def sequential_fetch(base_url: str, n: int) -> float:
    """Fetch n pages sequentially with urllib (stdlib). Returns elapsed seconds."""
    start = time.perf_counter()
    for i in range(1, n + 1):
        urllib.request.urlopen(f"{base_url}/page/{i}", timeout=10)
    return time.perf_counter() - start


async def async_crawl(base_url: str, n_pages: int) -> tuple[float, float]:
    """Crawl n_pages with AdvancedCrawler. Returns (elapsed_s, peak_memory_mb)."""
    config = CrawlerConfig(
        start_urls=[f"{base_url}/"],
        max_pages=n_pages,
        max_concurrent=10,
        same_domain_only=True,
        log_level="ERROR",
    )

    tracemalloc.start()
    t0 = time.perf_counter()

    async with AdvancedCrawler(config) as crawler:
        await crawler.crawl(show_progress=False)

    elapsed = time.perf_counter() - t0
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    return elapsed, peak / (1024 * 1024)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    seq_n = 50  # sequential baseline capped at 50 to keep demo fast

    for n_pages in (100, 500, 1000):
        print(f"\n{'─' * 50}")
        print(f"  Pages: {n_pages}")
        print(f"{'─' * 50}")

        runner, base_url = await start_server(n_pages)
        try:
            # Sequential baseline runs in a thread so the asyncio event loop
            # (and the aiohttp server) remain responsive during blocking I/O.
            print(f"  Sequential ({seq_n} pages) …", end=" ", flush=True)
            seq_elapsed = await asyncio.to_thread(sequential_fetch, base_url, seq_n)
            seq_rps = seq_n / seq_elapsed
            print(f"{seq_elapsed:.2f}s  ({seq_rps:.1f} req/s)")

            # Async crawl (full n_pages)
            print(f"  Async      ({n_pages} pages) …", end=" ", flush=True)
            async_elapsed, peak_mb = await async_crawl(base_url, n_pages)
            async_rps = n_pages / async_elapsed
            print(
                f"{async_elapsed:.2f}s  ({async_rps:.1f} req/s)  peak={peak_mb:.1f} MB"
            )

            # Normalised speedup (pages/s ratio)
            speedup = async_rps / seq_rps if seq_rps > 0 else 0.0
            print(f"  Speedup:   {speedup:.1f}x  (normalised requests/sec)")
            if speedup < 1.0:
                print(
                    "  Note: localhost has ~0ms latency, so async concurrency "
                    "doesn't help here. On real websites (50–200ms/req) speedup "
                    "is typically 5–20x."
                )

        finally:
            await runner.cleanup()

    print()


if __name__ == "__main__":
    asyncio.run(main())
