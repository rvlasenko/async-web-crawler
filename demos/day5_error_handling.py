import asyncio
import json
import logging
import sys
import time
from pathlib import Path

from aiohttp import web

from crawler.async_crawler import AsyncCrawler
from crawler.errors import TransientError
from crawler.retry_strategy import RetryStats, RetryStrategy, RetryTypeConfig

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT / "src"))

# Route logging to stdout so it stays in order with print() output.
logging.basicConfig(
    stream=sys.stdout,
    level=logging.WARNING,
    format="  [log] %(message)s",
    force=True,
)
# Suppress crawler-internal warnings — results speak for themselves.
logging.getLogger("crawler").setLevel(logging.ERROR)

OUTPUT_DIR = Path("output")
OUTPUT_FILE = OUTPUT_DIR / "day5_results.json"


# ---------------------------------------------------------------------------
# Local test server
# ---------------------------------------------------------------------------

_call_counts: dict[str, int] = {}


async def handle_flaky(request: web.Request) -> web.Response:
    _call_counts["flaky"] = _call_counts.get("flaky", 0) + 1
    if _call_counts["flaky"] <= 2:
        return web.Response(status=503, text="Service Unavailable")
    return web.Response(
        content_type="text/html",
        text="<html><body><p>Recovered after retries</p></body></html>",
    )


async def handle_always503(request: web.Request) -> web.Response:
    _call_counts["always503"] = _call_counts.get("always503", 0) + 1
    return web.Response(status=503, text="Service Unavailable")


async def handle_not_found(request: web.Request) -> web.Response:
    _call_counts["not_found"] = _call_counts.get("not_found", 0) + 1
    return web.Response(status=404, text="Not Found")


async def handle_slow(request: web.Request) -> web.Response:
    _call_counts["slow"] = _call_counts.get("slow", 0) + 1
    if _call_counts["slow"] == 1:
        await asyncio.sleep(2.0)
    return web.Response(
        content_type="text/html",
        text="<html><body><p>Slow but eventually OK</p></body></html>",
    )


async def start_server(port: int) -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/flaky", handle_flaky)
    app.router.add_get("/always503", handle_always503)
    app.router.add_get("/not-found", handle_not_found)
    app.router.add_get("/slow", handle_slow)

    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "localhost", port).start()
    return runner


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_success(result: dict) -> bool:
    return not result.get("fetch_error") and not result.get("parse_errors")


def _error_msg(result: dict) -> str:
    fetch_error = result.get("fetch_error")
    if fetch_error:
        return fetch_error
    errors = result.get("parse_errors", [])
    return errors[0] if errors else "unknown"


def _short_error(result: dict) -> str:
    msg = _error_msg(result)
    # "Fetch failed: HTTP 503: http://..." -> "HTTP 503"
    # "Fetch failed: Timeout: http://..."  -> "Timeout"
    if msg.startswith("Fetch failed: "):
        msg = msg[len("Fetch failed: "):]
    if ": http" in msg:
        msg = msg[: msg.index(": http")]
    return msg


def _attempts_str(n: int) -> str:
    return f"{n} attempt" if n == 1 else f"{n} attempts"


def _count_successes(results: dict[str, dict]) -> int:
    return sum(1 for r in results.values() if _is_success(r))


def print_run_header(label: str) -> None:
    print()
    print("─" * 64)
    print(f"  {label}")
    print("─" * 64)


def print_url_list(results: dict[str, dict], urls: list[str], counts: dict) -> None:
    for url in urls:
        path = "/" + url.split("/", 3)[-1]
        key = path.lstrip("/").replace("-", "_")
        n = counts.get(key, "?")
        attempts = _attempts_str(n) if isinstance(n, int) else str(n)
        if _is_success(results[url]):
            print(f"  {path:<14}  [ok]    {attempts}")
        else:
            err = _short_error(results[url])
            print(f"  {path:<14}  [FAIL]  {attempts}  -- {err}")


def print_retry_stats(stats: RetryStats) -> None:
    print()
    print("  Retry statistics:")
    print(f"    total_calls        : {stats.total_calls}")
    print(f"    total_retries      : {stats.total_retries}")
    print(f"    successful_retries : {stats.successful_retries}")
    print(f"    failed_calls       : {stats.failed_calls}")
    print(f"    total_delay        : {stats.total_delay_seconds:.3f} s")
    print(f"    avg_delay/retry    : {stats.avg_delay_per_retry:.3f} s")
    if stats.errors_by_type:
        print("    errors by type:")
        for name, count in sorted(stats.errors_by_type.items()):
            print(f"      {name:<24}: {count}")


# ---------------------------------------------------------------------------
# Crawl runs
# ---------------------------------------------------------------------------


async def run_without_retry(urls: list[str]) -> tuple[dict[str, dict], float]:
    print_run_header("Run A — no retry strategy (single attempt per URL)")
    async with AsyncCrawler(timeout_seconds=0.5) as crawler:
        t0 = time.perf_counter()
        results = await crawler.fetch_and_parse_urls(urls)
        elapsed = time.perf_counter() - t0

    counts = {
        "flaky": _call_counts.get("flaky", 0),
        "always503": _call_counts.get("always503", 0),
        "not_found": _call_counts.get("not_found", 0),
        "slow": _call_counts.get("slow", 0),
    }
    print_url_list(results, urls, counts)
    print(f"\n  Elapsed: {elapsed:.2f} s   Succeeded: {_count_successes(results)}/{len(urls)}")
    return results, elapsed


async def run_with_retry(urls: list[str]) -> tuple[dict[str, dict], float, RetryStats]:
    retry_strategy = RetryStrategy(
        max_retries=3,
        base_delay=0.1,
        backoff_factor=2.0,
        per_type_config={
            TransientError: RetryTypeConfig(
                max_retries=2,
                base_delay=0.2,
                backoff_factor=2.0,
            ),
        },
    )

    _call_counts["flaky"] = 0
    _call_counts["always503"] = 0
    _call_counts["not_found"] = 0
    _call_counts["slow"] = 0

    print_run_header("Run B — RetryStrategy(max_retries=3, base_delay=0.1, backoff_factor=2.0)")
    print("  per-type TransientError: max_retries=2, base_delay=0.2, backoff_factor=2.0")

    async with AsyncCrawler(timeout_seconds=0.5, retry_strategy=retry_strategy) as crawler:
        t0 = time.perf_counter()
        results = await crawler.fetch_and_parse_urls(urls)
        elapsed = time.perf_counter() - t0

    counts = {
        "flaky": _call_counts.get("flaky", 0),
        "always503": _call_counts.get("always503", 0),
        "not_found": _call_counts.get("not_found", 0),
        "slow": _call_counts.get("slow", 0),
    }
    print_url_list(results, urls, counts)
    print(f"\n  Elapsed: {elapsed:.2f} s   Succeeded: {_count_successes(results)}/{len(urls)}")
    print_retry_stats(retry_strategy.stats)
    return results, elapsed, retry_strategy.stats


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main() -> None:
    print("=" * 64)
    print("  DAY 5: ERROR HANDLING + RETRY STRATEGIES")
    print("=" * 64)
    print()
    print("  Test endpoints:")
    print("    /flaky      -- HTTP 503 x2, then 200  (verifies successful retry)")
    print("    /always503  -- always HTTP 503         (verifies retry exhaustion)")
    print("    /not-found  -- always HTTP 404         (permanent -- no retries)")
    print("    /slow       -- sleeps 2 s on 1st call  (timeout -> retry -> success)")
    sys.stdout.flush()

    port = 18765
    runner = await start_server(port)
    base = f"http://localhost:{port}"
    urls = [
        f"{base}/flaky",
        f"{base}/always503",
        f"{base}/not-found",
        f"{base}/slow",
    ]

    try:
        results_a, elapsed_a = await run_without_retry(urls)
        results_b, elapsed_b, retry_stats = await run_with_retry(urls)

        print()
        print("=" * 64)
        print("  Summary")
        print("=" * 64)
        print(f"  {'URL':<14}  {'Run A':<8}  {'Run B':<8}  Expected")
        print(f"  {'-'*14}  {'-'*8}  {'-'*8}  {'-'*20}")

        expected = {
            "/flaky": "retry -> succeed",
            "/always503": "retries exhausted",
            "/not-found": "no retry (4xx)",
            "/slow": "timeout -> retry ok",
        }
        for url in urls:
            path = "/" + url.split("/", 3)[-1]
            a = "ok" if _is_success(results_a[url]) else "FAIL"
            b = "ok" if _is_success(results_b[url]) else "FAIL"
            note = expected.get(path, "")
            print(f"  {path:<14}  {a:<8}  {b:<8}  {note}")

        OUTPUT_DIR.mkdir(exist_ok=True)
        report = {
            "run_a": {
                "strategy": None,
                "results": {
                    url: {
                        "success": _is_success(r),
                        "error": _error_msg(r) if not _is_success(r) else None,
                    }
                    for url, r in results_a.items()
                },
                "elapsed_seconds": round(elapsed_a, 3),
            },
            "run_b": {
                "strategy": {
                    "max_retries": 3,
                    "base_delay": 0.1,
                    "backoff_factor": 2.0,
                    "per_type_config": {
                        "TransientError": {
                            "max_retries": 2,
                            "base_delay": 0.2,
                            "backoff_factor": 2.0,
                        }
                    },
                },
                "results": {
                    url: {
                        "success": _is_success(r),
                        "error": _error_msg(r) if not _is_success(r) else None,
                    }
                    for url, r in results_b.items()
                },
                "elapsed_seconds": round(elapsed_b, 3),
                "retry_stats": {
                    "total_calls": retry_stats.total_calls,
                    "total_retries": retry_stats.total_retries,
                    "successful_retries": retry_stats.successful_retries,
                    "failed_calls": retry_stats.failed_calls,
                    "errors_by_type": retry_stats.errors_by_type,
                    "total_delay_seconds": round(retry_stats.total_delay_seconds, 4),
                    "avg_delay_per_retry": round(retry_stats.avg_delay_per_retry, 4),
                },
            },
        }

        with OUTPUT_FILE.open("w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)

        print(f"\n  Report saved to: {OUTPUT_FILE}")
        print()

    finally:
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.run(main())
