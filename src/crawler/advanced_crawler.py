import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from crawler.async_crawler import AsyncCrawler
from crawler.config import CrawlerConfig
from crawler.exporters import HtmlReportExporter, JsonStatsExporter
from crawler.logging_config import setup_logging
from crawler.monitoring import ProgressMonitor
from crawler.sitemap_parser import SitemapParser
from crawler.stats import CrawlerStats
from crawler.storage.base import DataStorage
from crawler.storage.csv_storage import CSVStorage
from crawler.storage.json_storage import JSONStorage
from crawler.storage.postgres_storage import PostgreSQLStorage

logger = logging.getLogger(__name__)


class AdvancedCrawler:
    """High-level crawler that integrates AsyncCrawler with config, sitemap
    discovery, progress monitoring, statistics, and report export.

    Composes AsyncCrawler — does not inherit from it. The public API is
    intentionally smaller than AsyncCrawler's to keep the interface clean.

    Typical usage as an async context manager:

        async with AdvancedCrawler(config) as crawler:
            results = await crawler.crawl()
            crawler.export_to_html_report("report.html")

    Or loaded from a config file:

        async with AdvancedCrawler.from_config("config.yaml") as crawler:
            await crawler.crawl()

    Args:
        config: CrawlerConfig instance. validate() is called in __init__.
        storage: Optional DataStorage override. When provided it takes
            precedence over config.storage_type.
    """

    def __init__(
        self,
        config: CrawlerConfig,
        storage: DataStorage | None = None,
    ) -> None:
        config.validate()
        self._config = config
        self._storage_override = storage
        self._inner: AsyncCrawler | None = None
        self._storage: DataStorage | None = None
        self._stats: CrawlerStats | None = None

    @classmethod
    def from_config(cls, path: str | Path) -> "AdvancedCrawler":
        """Create an AdvancedCrawler by loading a YAML or JSON config file."""
        config = CrawlerConfig.load(path)
        return cls(config)

    async def crawl(self, show_progress: bool = True) -> dict[str, dict[str, Any]]:
        """Orchestrate the full crawl lifecycle.

        Steps:
        1. Configure logging.
        2. Build storage backend from config (unless overridden in __init__).
        3. Open AsyncCrawler session.
        4. Fetch sitemap URLs and merge with start_urls.
        5. Run inner.crawl() with ProgressMonitor.
        6. Build CrawlerStats from results.
        7. Return results dict.

        Returns:
            Mapping of URL → parsed page data for every successfully
            processed page (same format as AsyncCrawler.crawl()).
        """
        cfg = self._config

        setup_logging(level=cfg.log_level, log_file=cfg.log_file)

        self._storage = self._storage_override or self._build_storage()
        if self._storage is not None:
            await self._storage.initialize()

        inner = AsyncCrawler(
            max_concurrent=cfg.max_concurrent,
            max_depth=cfg.max_depth,
            requests_per_second=cfg.requests_per_second,
            rate_limit_per_domain=cfg.rate_limit_per_domain,
            respect_robots_txt=cfg.respect_robots,
            user_agent=cfg.user_agent,
            storage=self._storage,
        )
        self._inner = inner

        crawl_started_at = datetime.now(tz=timezone.utc)

        async with inner:
            # Fetch sitemap URLs using the already-open session
            sitemap_urls: list[str] = []
            if cfg.sitemap_urls:
                assert inner.session is not None
                parser = SitemapParser(inner.session)
                batches = await asyncio.gather(
                    *[parser.fetch_sitemap(u) for u in cfg.sitemap_urls]
                )
                seen: set[str] = set()
                for batch in batches:
                    for url in batch:
                        if url not in seen:
                            seen.add(url)
                            sitemap_urls.append(url)
                logger.info("Fetched %d URLs from sitemaps", len(sitemap_urls))

            # Merge config start_urls with sitemap discoveries (config first)
            all_start: list[str] = list(dict.fromkeys(cfg.start_urls + sitemap_urls))

            monitor = ProgressMonitor(
                crawler=inner,
                max_pages=cfg.max_pages,
                enabled=show_progress,
            )

            async with monitor:
                results = await inner.crawl(
                    start_urls=all_start,
                    max_pages=cfg.max_pages,
                    same_domain_only=cfg.same_domain_only,
                    include_patterns=cfg.include_patterns or None,
                    exclude_patterns=cfg.exclude_patterns or None,
                )

            runtime = inner.get_crawl_stats()

        stats = CrawlerStats(start_time=crawl_started_at)
        for url, page_data in results.items():
            stats.record_page(
                url=url,
                status_code=page_data.get("status_code"),
                success=True,
            )
        for url in inner.failed_urls:
            stats.record_page(url=url, status_code=None, success=False)

        stats.finalize(avg_latency=runtime.get("avg_latency_seconds", 0.0))
        self._stats = stats

        logger.info(
            "Crawl complete — %d successful, %d failed, %.1f pg/s",
            stats.successful,
            stats.failed,
            stats.pages_per_second,
        )

        return results

    def get_stats(self) -> dict[str, Any]:
        """Return a serialisable stats dict.

        Raises:
            RuntimeError: If crawl() has not been called yet.
        """
        if self._stats is None:
            raise RuntimeError("No stats available — call crawl() first.")
        return self._stats.to_dict()

    def export_to_json(self, filename: str | Path) -> None:
        """Export crawl statistics to a JSON file.

        Note: exports *statistics* (counts, speed, domains), not page data.
        To save page data use storage_type in config or --output in CLI.

        Raises:
            RuntimeError: If crawl() has not been called yet.
        """
        if self._stats is None:
            raise RuntimeError("No stats to export — call crawl() first.")
        JsonStatsExporter().export(self._stats, filename)

    def export_to_html_report(self, filename: str | Path) -> None:
        """Export crawl statistics to a self-contained HTML report.

        Note: exports *statistics*, not page data.

        Raises:
            RuntimeError: If crawl() has not been called yet.
        """
        if self._stats is None:
            raise RuntimeError("No stats to export — call crawl() first.")
        HtmlReportExporter().export(self._stats, filename)

    async def close(self) -> None:
        """Close the inner crawler session and storage. Idempotent."""
        if self._inner is not None:
            await self._inner.close()
            self._inner = None
        if self._storage is not None:
            await self._storage.close()
            self._storage = None

    async def __aenter__(self) -> "AdvancedCrawler":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    def _build_storage(self) -> DataStorage | None:
        cfg = self._config
        match cfg.storage_type:
            case "json":
                assert cfg.storage_path is not None  # guaranteed by validate()
                return JSONStorage(cfg.storage_path)
            case "csv":
                assert cfg.storage_path is not None  # guaranteed by validate()
                return CSVStorage(cfg.storage_path)
            case "postgres":
                assert cfg.postgres_dsn is not None  # guaranteed by validate()
                return PostgreSQLStorage(cfg.postgres_dsn)
            case _:
                return None
