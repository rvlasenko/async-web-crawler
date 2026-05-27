import json
from datetime import datetime, timezone

import pytest

from crawler.stats import CrawlerStats


def make_stats() -> CrawlerStats:
    return CrawlerStats(start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))


def test_record_page_counts_successful() -> None:
    stats = make_stats()
    stats.record_page("https://example.com/a", status_code=200, success=True)

    assert stats.total_pages == 1
    assert stats.successful == 1
    assert stats.failed == 0


def test_record_page_counts_failed() -> None:
    stats = make_stats()
    stats.record_page("https://example.com/a", status_code=None, success=False)

    assert stats.total_pages == 1
    assert stats.successful == 0
    assert stats.failed == 1


def test_record_page_tracks_status_codes() -> None:
    stats = make_stats()
    stats.record_page("https://a.com/1", status_code=200, success=True)
    stats.record_page("https://a.com/2", status_code=200, success=True)
    stats.record_page("https://a.com/3", status_code=404, success=False)

    assert stats.status_codes[200] == 2
    assert stats.status_codes[404] == 1


def test_record_page_none_status_uses_unknown_key() -> None:
    stats = make_stats()
    stats.record_page("https://a.com/", status_code=None, success=False)

    assert stats.status_codes["unknown"] == 1


def test_record_page_tracks_domain_frequency() -> None:
    stats = make_stats()
    stats.record_page("https://example.com/a", status_code=200, success=True)
    stats.record_page("https://example.com/b", status_code=200, success=True)
    stats.record_page("https://other.com/c", status_code=200, success=True)

    assert stats.domain_frequencies["example.com"] == 2
    assert stats.domain_frequencies["other.com"] == 1


def test_finalize_sets_avg_latency_and_end_time() -> None:
    stats = make_stats()
    stats.finalize(avg_latency=0.42)

    assert stats.avg_latency_seconds == 0.42
    assert stats.end_time is not None


def test_pages_per_second_zero_before_finalize() -> None:
    stats = make_stats()
    stats.record_page("https://a.com/", status_code=200, success=True)
    # elapsed is effectively 0 at the same instant — should not raise
    result = stats.pages_per_second
    assert result >= 0.0


def test_to_dict_is_json_serialisable() -> None:
    stats = make_stats()
    stats.record_page("https://example.com/", status_code=200, success=True)
    stats.finalize(avg_latency=0.1)

    d = stats.to_dict()
    dumped = json.dumps(d)
    assert dumped  # non-empty
    loaded = json.loads(dumped)
    assert loaded["total_pages"] == 1
    assert loaded["successful"] == 1
