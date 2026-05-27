import html
import json
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from crawler.stats import CrawlerStats


class JsonStatsExporter:
    """Exports CrawlerStats to a JSON file."""

    def export(self, stats: "CrawlerStats", filename: str | Path) -> None:
        """Write stats.to_dict() to a JSON file (synchronous)."""
        data = stats.to_dict()
        Path(filename).write_text(
            json.dumps(data, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )


class HtmlReportExporter:
    """Exports CrawlerStats to a self-contained HTML report.

    Produces a single file with inline CSS and inline SVG bar charts.
    No external dependencies (no CDN, no JavaScript frameworks).
    All user-provided data is HTML-escaped before insertion.
    """

    def export(self, stats: "CrawlerStats", filename: str | Path) -> None:
        """Write a self-contained HTML report to the given path."""
        Path(filename).write_text(
            self._render(stats),
            encoding="utf-8",
        )

    def _render(self, stats: "CrawlerStats") -> str:
        d = stats.to_dict()

        status_section = self._render_status_chart(d["status_codes"])
        domain_section = self._render_domain_table(d["domain_frequencies"])

        success_pct = (
            round(d["successful"] / d["total_pages"] * 100, 1)
            if d["total_pages"] > 0
            else 0.0
        )

        return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Crawl Report</title>
<style>
  body {{ font-family: system-ui, sans-serif; margin: 0; padding: 24px; background: #f8f9fa; color: #212529; }}
  h1 {{ font-size: 1.6rem; margin-bottom: 4px; }}
  .meta {{ color: #6c757d; font-size: 0.9rem; margin-bottom: 24px; }}
  .cards {{ display: flex; gap: 16px; flex-wrap: wrap; margin-bottom: 32px; }}
  .card {{ background: #fff; border-radius: 8px; padding: 20px 24px; min-width: 150px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  .card .value {{ font-size: 2rem; font-weight: 700; line-height: 1; }}
  .card .label {{ font-size: 0.8rem; color: #6c757d; margin-top: 4px; text-transform: uppercase; letter-spacing: .05em; }}
  .card.green .value {{ color: #198754; }}
  .card.red .value {{ color: #dc3545; }}
  .card.blue .value {{ color: #0d6efd; }}
  section {{ background: #fff; border-radius: 8px; padding: 20px 24px; margin-bottom: 24px; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  section h2 {{ font-size: 1.1rem; margin: 0 0 16px; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 0.9rem; }}
  th {{ text-align: left; padding: 8px 12px; background: #f1f3f5; font-weight: 600; }}
  td {{ padding: 8px 12px; border-top: 1px solid #e9ecef; }}
  tr:hover td {{ background: #f8f9fa; }}
  .bar-wrap {{ display: flex; align-items: center; gap: 8px; }}
  .bar {{ height: 20px; background: #0d6efd; border-radius: 3px; min-width: 2px; }}
  .bar.s2xx {{ background: #198754; }}
  .bar.s3xx {{ background: #0dcaf0; }}
  .bar.s4xx {{ background: #ffc107; }}
  .bar.s5xx {{ background: #dc3545; }}
  .bar.sunk {{ background: #6c757d; }}
</style>
</head>
<body>
<h1>Crawl Report</h1>
<p class="meta">
  Started: {html.escape(str(d["start_time"]))} &nbsp;|&nbsp;
  Finished: {html.escape(str(d["end_time"] or "—"))} &nbsp;|&nbsp;
  Duration: {d["elapsed_seconds"]}s
</p>

<div class="cards">
  <div class="card blue"><div class="value">{d["total_pages"]}</div><div class="label">Total pages</div></div>
  <div class="card green"><div class="value">{d["successful"]}</div><div class="label">Successful</div></div>
  <div class="card red"><div class="value">{d["failed"]}</div><div class="label">Failed</div></div>
  <div class="card"><div class="value">{success_pct}%</div><div class="label">Success rate</div></div>
  <div class="card"><div class="value">{d["pages_per_second"]}</div><div class="label">Pages / sec</div></div>
  <div class="card"><div class="value">{d["avg_latency_seconds"]}s</div><div class="label">Avg latency</div></div>
</div>

{status_section}
{domain_section}
</body>
</html>"""

    def _render_status_chart(self, status_codes: dict) -> str:
        if not status_codes:
            return ""

        # Group into categories
        buckets: dict[str, int] = {
            "2xx": 0,
            "3xx": 0,
            "4xx": 0,
            "5xx": 0,
            "unknown": 0,
        }
        for code, count in status_codes.items():
            if code == "unknown":
                buckets["unknown"] += count
            elif isinstance(code, int):
                if 200 <= code < 300:
                    buckets["2xx"] += count
                elif 300 <= code < 400:
                    buckets["3xx"] += count
                elif 400 <= code < 500:
                    buckets["4xx"] += count
                elif 500 <= code < 600:
                    buckets["5xx"] += count
                else:
                    buckets["unknown"] += count

        total = sum(buckets.values()) or 1
        css_class = {
            "2xx": "s2xx",
            "3xx": "s3xx",
            "4xx": "s4xx",
            "5xx": "s5xx",
            "unknown": "sunk",
        }

        rows = ""
        for label, count in buckets.items():
            if count == 0:
                continue
            pct = round(count / total * 100, 1)
            bar_w = max(2, int(pct * 3))
            rows += (
                f"<tr><td>{html.escape(label)}</td>"
                f"<td>{count}</td>"
                f"<td><div class='bar-wrap'>"
                f"<div class='bar {css_class[label]}' style='width:{bar_w}px'></div>"
                f"<span>{pct}%</span></div></td></tr>\n"
            )

        # Also show individual codes in a detail table
        detail_rows = ""
        for code, count in sorted(status_codes.items(), key=lambda x: -x[1]):
            pct = round(count / total * 100, 1)
            detail_rows += (
                f"<tr><td>{html.escape(str(code))}</td>"
                f"<td>{count}</td><td>{pct}%</td></tr>\n"
            )

        return f"""<section>
<h2>HTTP Status Codes</h2>
<table>
<thead><tr><th>Category</th><th>Count</th><th>Share</th></tr></thead>
<tbody>{rows}</tbody>
</table>
<details style="margin-top:12px"><summary style="cursor:pointer;color:#0d6efd">Show individual codes</summary>
<table style="margin-top:8px">
<thead><tr><th>Code</th><th>Count</th><th>Share</th></tr></thead>
<tbody>{detail_rows}</tbody>
</table></details>
</section>"""

    def _render_domain_table(self, domain_frequencies: dict) -> str:
        if not domain_frequencies:
            return ""

        top = sorted(domain_frequencies.items(), key=lambda x: -x[1])[:20]
        total = sum(domain_frequencies.values()) or 1

        rows = ""
        for domain, count in top:
            pct = round(count / total * 100, 1)
            bar_w = max(2, int(pct * 3))
            rows += (
                f"<tr><td>{html.escape(domain)}</td>"
                f"<td>{count}</td>"
                f"<td><div class='bar-wrap'>"
                f"<div class='bar s2xx' style='width:{bar_w}px'></div>"
                f"<span>{pct}%</span></div></td></tr>\n"
            )

        total_domains = len(domain_frequencies)
        note = f" (showing top 20 of {total_domains})" if total_domains > 20 else ""

        return f"""<section>
<h2>Top Domains{html.escape(note)}</h2>
<table>
<thead><tr><th>Domain</th><th>Pages</th><th>Share</th></tr></thead>
<tbody>{rows}</tbody>
</table>
</section>"""
