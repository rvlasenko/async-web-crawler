import asyncio
import sys
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crawler.async_crawler import AsyncCrawler


class ProgressMonitor:
    """Async context manager that renders crawl progress to stderr in-place.

    Polls AsyncCrawler.get_crawl_stats() on a background asyncio.Task at a
    configurable interval. Uses \\r to overwrite the current line so the
    terminal stays clean during a long crawl.

    Output is written to sys.stderr to avoid interfering with stdout data
    pipelines (e.g. python -m crawler ... > results.json).

    When max_pages is known:
        [##########    ] 67% | 134 pages | 12.4 pg/s | ETA: 00:08 | Active: 5

    When max_pages is unknown:
        \\  134 pages | 12.4 pg/s | Active: 5

    Args:
        crawler: AsyncCrawler instance to poll. Must already be entered (session
            open) when the monitor is started.
        max_pages: Total page target used for percentage and ETA. Pass None when
            unknown.
        interval_seconds: Polling interval in seconds. Default 0.5.
        enabled: When False, __aenter__ is a no-op. Allows --no-progress without
            wrapping the call in a conditional.
    """

    _SPINNER = "|/-\\"

    def __init__(
        self,
        crawler: "AsyncCrawler",
        max_pages: int | None = None,
        interval_seconds: float = 0.5,
        enabled: bool = True,
    ) -> None:
        self._crawler = crawler
        self._max_pages = max_pages
        self._interval = interval_seconds
        self._enabled = enabled
        self._task: asyncio.Task | None = None
        self._start: float = 0.0

    async def __aenter__(self) -> "ProgressMonitor":
        if self._enabled:
            self._start = time.perf_counter()
            self._task = asyncio.create_task(self._poll_loop())
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.stop()

    async def stop(self) -> None:
        """Cancel the background polling task and clear the progress line."""
        if self._task is not None and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        if self._enabled:
            # Clear the line so subsequent output starts on a clean line
            print("\r" + " " * 80 + "\r", end="", flush=True, file=sys.stderr)

    async def _poll_loop(self) -> None:
        while True:
            try:
                stats = self._crawler.get_crawl_stats()
                line = self._render_line(stats)
                print(f"\r{line}", end="", flush=True, file=sys.stderr)
            except Exception:
                pass
            await asyncio.sleep(self._interval)

    def _render_line(self, stats: dict) -> str:
        """Format the progress line. Pure function — easy to unit-test."""
        processed: int = stats.get("processed_pages", 0)
        speed: float = stats.get("pages_per_second", 0.0)
        active: int = stats.get("active_tasks", 0)

        speed_str = f"{speed:.1f} pg/s"

        if self._max_pages and self._max_pages > 0:
            pct = min(100, int(processed / self._max_pages * 100))
            bar_w = 20
            filled = int(bar_w * pct / 100)
            bar = "#" * filled + " " * (bar_w - filled)

            remaining = max(0, self._max_pages - processed)
            if speed > 0:
                eta_secs = int(remaining / speed)
                eta_str = f"{eta_secs // 60:02d}:{eta_secs % 60:02d}"
            else:
                eta_str = "--:--"

            return (
                f"[{bar}] {pct:3d}% | {processed} pages | "
                f"{speed_str} | ETA: {eta_str} | Active: {active}"
            )

        spinner = self._SPINNER[int(time.perf_counter() * 4) % 4]
        return f"{spinner} | {processed} pages | {speed_str} | Active: {active}"
