import json
from datetime import datetime, timezone
from pathlib import Path

from crawler.exporters import HtmlReportExporter, JsonStatsExporter
from crawler.stats import CrawlerStats


def make_stats_with_data() -> CrawlerStats:
    stats = CrawlerStats(start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    stats.record_page("https://example.com/", status_code=200, success=True)
    stats.record_page("https://example.com/about", status_code=200, success=True)
    stats.record_page("https://example.com/missing", status_code=404, success=False)
    stats.finalize(avg_latency=0.15)
    return stats


def test_json_exporter_creates_file(tmp_path: Path) -> None:
    out = tmp_path / "stats.json"
    JsonStatsExporter().export(make_stats_with_data(), out)

    assert out.exists()


def test_json_exporter_produces_valid_json(tmp_path: Path) -> None:
    out = tmp_path / "stats.json"
    JsonStatsExporter().export(make_stats_with_data(), out)

    data = json.loads(out.read_text())
    assert isinstance(data, dict)


def test_json_exporter_contains_expected_keys(tmp_path: Path) -> None:
    out = tmp_path / "stats.json"
    JsonStatsExporter().export(make_stats_with_data(), out)

    data = json.loads(out.read_text())
    for key in (
        "total_pages",
        "successful",
        "failed",
        "pages_per_second",
        "status_codes",
    ):
        assert key in data, f"Missing key: {key}"


def test_html_exporter_creates_file(tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    HtmlReportExporter().export(make_stats_with_data(), out)

    assert out.exists()


def test_html_exporter_produces_valid_html(tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    HtmlReportExporter().export(make_stats_with_data(), out)

    content = out.read_text()
    assert "<html" in content
    assert "</html>" in content


def test_html_exporter_escapes_xss_in_domain(tmp_path: Path) -> None:
    stats = CrawlerStats(start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    # Inject a malicious domain name directly into the Counter to test escaping
    stats.domain_frequencies["<script>alert(1)</script>"] = 3
    stats.finalize()
    out = tmp_path / "report.html"
    HtmlReportExporter().export(stats, out)

    content = out.read_text()
    assert "<script>alert(1)</script>" not in content
    assert "&lt;script&gt;" in content


def test_html_exporter_works_with_zero_pages(tmp_path: Path) -> None:
    stats = CrawlerStats(start_time=datetime(2024, 1, 1, tzinfo=timezone.utc))
    stats.finalize()
    out = tmp_path / "report.html"
    # Must not raise
    HtmlReportExporter().export(stats, out)

    assert out.exists()
