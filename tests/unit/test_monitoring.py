from unittest.mock import MagicMock

import pytest

from crawler.monitoring import ProgressMonitor


def make_monitor(max_pages: int | None = None) -> ProgressMonitor:
    mock_crawler = MagicMock()
    return ProgressMonitor(crawler=mock_crawler, max_pages=max_pages)


def test_render_line_with_known_max_pages_contains_percent() -> None:
    monitor = make_monitor(max_pages=100)
    stats = {
        "processed_pages": 67,
        "pages_per_second": 10.0,
        "active_tasks": 5,
    }

    line = monitor._render_line(stats)

    assert "%" in line
    assert "[" in line
    assert "67" in line


def test_render_line_with_unknown_max_pages_shows_spinner() -> None:
    monitor = make_monitor(max_pages=None)
    stats = {
        "processed_pages": 42,
        "pages_per_second": 5.0,
        "active_tasks": 3,
    }

    line = monitor._render_line(stats)

    # Should contain one of the spinner characters, no progress bar bracket
    assert any(c in line for c in "|/-\\")
    assert "[" not in line


def test_render_line_zero_speed_no_eta_crash() -> None:
    monitor = make_monitor(max_pages=100)
    stats = {
        "processed_pages": 10,
        "pages_per_second": 0.0,
        "active_tasks": 0,
    }

    line = monitor._render_line(stats)

    assert "--:--" in line
    assert "%" in line
