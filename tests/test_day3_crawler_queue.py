import asyncio

import pytest

from crawler.crawler_queue import CrawlerQueue
from crawler.models import CrawlTask


@pytest.mark.asyncio
async def test_queue_returns_higher_priority_first() -> None:
    queue = CrawlerQueue()

    queue.add_url(
        url="https://low-priority.com",
        priority=10,
    )

    queue.add_url(
        url="https://high-priority.com",
        priority=1,
    )

    task = await queue.get_next()

    assert task == CrawlTask(
        url="https://high-priority.com",
        priority=1,
    )


@pytest.mark.asyncio
async def test_queue_preserves_insertion_order_for_same_priority() -> None:
    queue = CrawlerQueue()

    queue.add_url("https://first.com", priority=1)
    queue.add_url("https://second.com", priority=1)

    first = await queue.get_next()
    second = await queue.get_next()

    assert first is not None
    assert second is not None

    assert first.url == "https://first.com"
    assert second.url == "https://second.com"


@pytest.mark.asyncio
async def test_queue_preserves_depth_in_task() -> None:
    queue = CrawlerQueue()

    queue.add_url(
        url="https://example.com/deep-page",
        priority=3,
        depth=2,
    )

    task = await queue.get_next()

    assert task == CrawlTask(
        url="https://example.com/deep-page",
        priority=3,
        depth=2,
    )


@pytest.mark.asyncio
async def test_queue_skips_duplicate_url_while_already_queued() -> None:
    queue = CrawlerQueue()

    queue.add_url("https://example.com")
    queue.add_url("https://example.com", priority=10, depth=1)

    first_task = await queue.get_next()
    second_task = await queue.get_next()

    assert first_task == CrawlTask(
        url="https://example.com",
        priority=0,
        depth=0,
    )
    assert second_task is None


@pytest.mark.asyncio
async def test_queue_skips_duplicate_url_when_already_processed() -> None:
    queue = CrawlerQueue()

    queue.mark_processed("https://example.com")

    queue.add_url("https://example.com")

    task = await queue.get_next()

    assert task is None


@pytest.mark.asyncio
async def test_queue_skips_duplicate_url_when_already_failed() -> None:
    queue = CrawlerQueue()

    queue.mark_failed(
        url="https://example.com",
        error="TimeoutError",
    )

    queue.add_url("https://example.com")

    task = await queue.get_next()

    assert task is None


@pytest.mark.asyncio
async def test_queue_returns_none_when_empty() -> None:
    queue = CrawlerQueue()

    task = await queue.get_next()

    assert task is None


def test_queue_marks_url_as_processed() -> None:
    queue = CrawlerQueue()

    queue.mark_processed("https://example.com")

    stats = queue.get_stats()

    assert stats["processed"] == 1
    assert stats["failed"] == 0


def test_queue_marks_url_as_failed() -> None:
    queue = CrawlerQueue()

    queue.mark_failed(
        url="https://example.com",
        error="TimeoutError",
    )

    stats = queue.get_stats()

    assert stats["processed"] == 0
    assert stats["failed"] == 1
    assert queue.failed_urls["https://example.com"] == "TimeoutError"


@pytest.mark.asyncio
async def test_get_next_concurrent_calls_return_each_item_exactly_once() -> None:
    """In asyncio, get_next() is safe to call concurrently: no await exists between
    the empty() check and get_nowait(), so no other coroutine can interleave.
    Each item is returned exactly once regardless of how many callers race."""
    queue = CrawlerQueue()
    for i in range(5):
        queue.add_url(f"https://example.com/page-{i}")

    results = await asyncio.gather(*[queue.get_next() for _ in range(7)])
    tasks = [r for r in results if r is not None]

    assert len(tasks) == 5
    assert len({t.url for t in tasks}) == 5


def test_queue_stats_include_only_unique_pending_urls() -> None:
    queue = CrawlerQueue()

    queue.add_url("https://queued.com")
    queue.add_url("https://queued.com")
    queue.mark_processed("https://processed.com")
    queue.mark_failed(
        url="https://failed.com",
        error="NetworkError",
    )

    stats = queue.get_stats()

    assert stats == {
        "queued": 1,
        "processed": 1,
        "failed": 1,
    }
