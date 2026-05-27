"""Unit tests for AdvancedCrawler.

AsyncCrawler is mocked so no network or aiohttp session is opened.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crawler.advanced_crawler import AdvancedCrawler
from crawler.config import CrawlerConfig


def _make_mock_inner(results: dict | None = None) -> AsyncMock:
    """Build a fully-stubbed AsyncCrawler double."""
    inner = AsyncMock()
    inner.session = MagicMock()
    inner.crawl = AsyncMock(return_value=results or {})
    inner.get_crawl_stats = MagicMock(
        return_value={"avg_latency_seconds": 0.0, "processed_pages": 0, "errors": 0}
    )
    inner.failed_urls = {}
    inner.__aenter__ = AsyncMock(return_value=inner)
    inner.__aexit__ = AsyncMock(return_value=None)
    return inner


@pytest.fixture
def config() -> CrawlerConfig:
    return CrawlerConfig(start_urls=["https://example.com"], max_pages=1)


# ---------------------------------------------------------------------------
# initialize()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_crawl_calls_storage_initialize(config: CrawlerConfig) -> None:
    """AdvancedCrawler must call initialize() on the storage before crawling."""
    mock_storage = AsyncMock()
    mock_inner = _make_mock_inner()

    with patch("crawler.advanced_crawler.AsyncCrawler", return_value=mock_inner):
        async with AdvancedCrawler(config, storage=mock_storage) as crawler:
            await crawler.crawl(show_progress=False)

    mock_storage.initialize.assert_called_once()


@pytest.mark.asyncio
async def test_crawl_without_storage_does_not_crash(config: CrawlerConfig) -> None:
    """When storage_type is 'none' and no storage override, crawl completes without error."""
    mock_inner = _make_mock_inner()

    with patch("crawler.advanced_crawler.AsyncCrawler", return_value=mock_inner):
        async with AdvancedCrawler(config) as crawler:
            results = await crawler.crawl(show_progress=False)

    assert isinstance(results, dict)


# ---------------------------------------------------------------------------
# get_stats() / export guards
# ---------------------------------------------------------------------------


def test_get_stats_raises_before_crawl(config: CrawlerConfig) -> None:
    crawler = AdvancedCrawler(config)
    with pytest.raises(RuntimeError, match="crawl()"):
        crawler.get_stats()


def test_export_to_json_raises_before_crawl(config: CrawlerConfig, tmp_path) -> None:
    crawler = AdvancedCrawler(config)
    with pytest.raises(RuntimeError, match="crawl()"):
        crawler.export_to_json(tmp_path / "stats.json")


def test_export_to_html_raises_before_crawl(config: CrawlerConfig, tmp_path) -> None:
    crawler = AdvancedCrawler(config)
    with pytest.raises(RuntimeError, match="crawl()"):
        crawler.export_to_html_report(tmp_path / "report.html")
