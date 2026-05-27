from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


@dataclass
class CrawlerStats:
    """Post-crawl statistics computed from final crawl results.

    Built by AdvancedCrawler after inner.crawl() returns. Not a live view.
    Call record_page() for each URL, then finalize() before reading properties.
    """

    start_time: datetime = field(
        default_factory=lambda: datetime.now(tz=timezone.utc)
    )
    end_time: datetime | None = None

    total_pages: int = 0
    successful: int = 0
    failed: int = 0

    # int | str keys: status code (int) or "unknown" for network errors
    status_codes: Counter = field(default_factory=Counter)
    domain_frequencies: Counter = field(default_factory=Counter)

    # Scalar from AsyncCrawler.get_crawl_stats(); per-page latency not available
    avg_latency_seconds: float = 0.0

    def record_page(
        self,
        url: str,
        status_code: int | None,
        success: bool,
    ) -> None:
        """Record one crawled page into the statistics."""
        self.total_pages += 1

        if success:
            self.successful += 1
        else:
            self.failed += 1

        key: int | str = status_code if status_code is not None else "unknown"
        self.status_codes[key] += 1

        domain = urlparse(url).netloc.lower()
        if domain:
            self.domain_frequencies[domain] += 1

    def finalize(
        self,
        avg_latency: float = 0.0,
        end_time: datetime | None = None,
    ) -> None:
        """Mark crawl complete. Call once after all record_page() calls."""
        self.avg_latency_seconds = avg_latency
        self.end_time = end_time or datetime.now(tz=timezone.utc)

    @property
    def elapsed_seconds(self) -> float:
        end = self.end_time or datetime.now(tz=timezone.utc)
        return (end - self.start_time).total_seconds()

    @property
    def pages_per_second(self) -> float:
        elapsed = self.elapsed_seconds
        if elapsed <= 0:
            return 0.0
        return self.successful / elapsed

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serialisable representation of the statistics."""
        return {
            "start_time": self.start_time.isoformat(),
            "end_time": self.end_time.isoformat() if self.end_time else None,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "total_pages": self.total_pages,
            "successful": self.successful,
            "failed": self.failed,
            "pages_per_second": round(self.pages_per_second, 2),
            "avg_latency_seconds": round(self.avg_latency_seconds, 3),
            "status_codes": dict(self.status_codes),
            "domain_frequencies": dict(self.domain_frequencies),
        }
