"""Unit tests for AdvancedCrawler.

AsyncCrawler is mocked so no network or aiohttp session is opened.
"""

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from crawler.advanced_crawler import AdvancedCrawler
from crawler.config import CrawlerConfig
from crawler.retry_strategy import RetryStrategy


def _make_mock_inner(
    results: dict | None = None,
    failed_urls: dict | None = None,
    failed_url_statuses: dict | None = None,
) -> AsyncMock:
    """Build a fully-stubbed AsyncCrawler double."""
    inner = AsyncMock()
    inner.session = MagicMock()
    inner.crawl = AsyncMock(return_value=results or {})
    inner.get_crawl_stats = MagicMock(
        return_value={"avg_latency_seconds": 0.0, "processed_pages": 0, "errors": 0}
    )
    inner.failed_urls = failed_urls or {}
    inner.failed_url_statuses = failed_url_statuses or {}
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


# ---------------------------------------------------------------------------
# Fix 1: RetryStrategy wired from CrawlerConfig
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_strategy_passed_when_max_retries_positive() -> None:
    """AdvancedCrawler must create and pass RetryStrategy when retry_max_retries > 0."""
    config = CrawlerConfig(
        start_urls=["https://example.com"],
        retry_max_retries=2,
        retry_backoff_factor=1.5,
        retry_base_delay=0.5,
    )
    mock_inner = _make_mock_inner()
    captured: list = []

    def capturing_constructor(**kwargs):
        captured.append(kwargs.get("retry_strategy"))
        return mock_inner

    with patch("crawler.advanced_crawler.AsyncCrawler", side_effect=capturing_constructor):
        async with AdvancedCrawler(config) as crawler:
            await crawler.crawl(show_progress=False)

    assert len(captured) == 1
    rs = captured[0]
    assert isinstance(rs, RetryStrategy)
    assert rs.max_retries == 2
    assert rs.backoff_factor == 1.5
    assert rs.base_delay == 0.5


@pytest.mark.asyncio
async def test_no_retry_strategy_when_max_retries_zero() -> None:
    """retry_max_retries=0 must result in retry_strategy=None (no retries)."""
    config = CrawlerConfig(
        start_urls=["https://example.com"],
        retry_max_retries=0,
    )
    mock_inner = _make_mock_inner()
    captured: list = []

    def capturing_constructor(**kwargs):
        captured.append(kwargs.get("retry_strategy"))
        return mock_inner

    with patch("crawler.advanced_crawler.AsyncCrawler", side_effect=capturing_constructor):
        async with AdvancedCrawler(config) as crawler:
            await crawler.crawl(show_progress=False)

    assert captured[0] is None


# ---------------------------------------------------------------------------
# Fix 2: failed_url_statuses reflected in CrawlerStats
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_failed_url_status_codes_recorded_in_stats() -> None:
    """Status codes from failed_url_statuses must appear in crawl statistics."""
    config = CrawlerConfig(start_urls=["https://example.com"])
    mock_inner = _make_mock_inner(
        failed_urls={"https://example.com/404": "HTTP 404"},
        failed_url_statuses={"https://example.com/404": 404},
    )

    with patch("crawler.advanced_crawler.AsyncCrawler", return_value=mock_inner):
        async with AdvancedCrawler(config) as crawler:
            await crawler.crawl(show_progress=False)
            stats = crawler.get_stats()

    assert stats["status_codes"].get(404, 0) == 1


@pytest.mark.asyncio
async def test_failed_url_unknown_status_when_no_http_code() -> None:
    """When a URL fails due to a network error (no HTTP status), stats shows unknown."""
    config = CrawlerConfig(start_urls=["https://example.com"])
    mock_inner = _make_mock_inner(
        failed_urls={"https://example.com/timeout": "Timeout"},
        failed_url_statuses={"https://example.com/timeout": None},
    )

    with patch("crawler.advanced_crawler.AsyncCrawler", return_value=mock_inner):
        async with AdvancedCrawler(config) as crawler:
            await crawler.crawl(show_progress=False)
            stats = crawler.get_stats()

    assert stats["status_codes"].get("unknown", 0) == 1
