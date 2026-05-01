"""Phase 2 comparison report.

Produces ``comparison.md`` and ``comparison.html`` summarizing a
:class:`SweepResult`. Per-scenario rows show final NAV, cumulative return,
worst drawdown + window length, min/mean coverage months, and shortfall
frequency. The exit gate (SPEC §6 Phase 2) requires only ``comparison.html``;
the markdown sibling is written for diffability and pasting into PRs.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from jinja2 import Template

from aa_model.integration.sweep import ScenarioResult, SweepResult

_HTML_TEMPLATE = Template(
    """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>SFO scenario sweep — {{ sweep_id }}</title>
<style>
  body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
         max-width: 1200px; margin: 2em auto; padding: 0 1em; color: #222; }
  h1 { margin-bottom: 0.2em; }
  .meta { color: #666; font-size: 0.9em; margin-bottom: 1.5em; }
  .meta code { background: #f3f4f6; padding: 0 0.3em; border-radius: 3px; }
  table { border-collapse: collapse; width: 100%; font-variant-numeric: tabular-nums; }
  th, td { padding: 0.45em 0.7em; border-bottom: 1px solid #e5e7eb; text-align: right; }
  th:first-child, td:first-child { text-align: left; }
  th { background: #f9fafb; font-weight: 600; }
  tbody tr:hover { background: #fafafa; }
  ul.scenarios { padding-left: 1.2em; }
  ul.scenarios li { margin: 0.25em 0; }
  .neg { color: #b91c1c; }
  .pos { color: #15803d; }
</style>
</head>
<body>
<h1>SFO scenario sweep</h1>
<div class="meta">
  sweep id: <code>{{ sweep_id }}</code><br>
  base config_hash: <code>{{ base_config_hash }}</code><br>
  scenarios: {{ rows|length }}
</div>

<h2>Per-scenario summary</h2>
<table>
<thead>
<tr>
  <th>scenario</th>
  <th>final NAV</th>
  <th>cum. return</th>
  <th>max drawdown</th>
  <th>dd quarters</th>
  <th>min coverage (mo)</th>
  <th>mean coverage (mo)</th>
  <th>shortfall freq</th>
</tr>
</thead>
<tbody>
{% for r in rows %}
<tr>
  <td>{{ r.name }}</td>
  <td>${{ "{:,.0f}".format(r.final_nav) }}</td>
  <td class="{{ 'pos' if r.cum_return >= 0 else 'neg' }}">{{ "{:+.2f}".format(r.cum_return) }}%</td>
  <td class="{{ 'neg' if r.max_dd < 0 else '' }}">{{ "{:+.2f}".format(r.max_dd) }}%</td>
  <td>{{ r.dd_quarters }}</td>
  <td>{{ "{:.1f}".format(r.min_coverage) }}</td>
  <td>{{ "{:.1f}".format(r.mean_coverage) }}</td>
  <td>{{ "{:.1f}".format(r.shortfall * 100) }}%</td>
</tr>
{% endfor %}
</tbody>
</table>

<h2>Scenarios</h2>
<ul class="scenarios">
{% for r in rows %}
<li><b>{{ r.name }}</b> — {{ r.description }} <small>(run_id: <code>{{ r.run_id }}</code>)</small></li>
{% endfor %}
</ul>
</body>
</html>
"""
)


@dataclass(frozen=True)
class _Row:
    name: str
    description: str
    run_id: str
    final_nav: float
    cum_return: float
    max_dd: float
    dd_quarters: int
    min_coverage: float
    mean_coverage: float
    shortfall: float


def _row_from_result(r: ScenarioResult) -> _Row:
    m = r.metrics
    return _Row(
        name=r.name,
        description=r.description,
        run_id=r.run.run_id,
        final_nav=m.final_nav_usd,
        cum_return=m.cumulative_return_pct,
        max_dd=m.max_drawdown_pct,
        dd_quarters=m.drawdown_quarters,
        min_coverage=m.min_coverage_months,
        mean_coverage=m.mean_coverage_months,
        shortfall=m.shortfall_frequency,
    )


def _render_markdown(sweep: SweepResult, rows: list[_Row]) -> str:
    lines: list[str] = [
        f"# Scenario sweep — {sweep.sweep_id}",
        "",
        f"- base config_hash: `{sweep.base_config_hash}`",
        f"- scenarios: {len(rows)}",
        "",
        "## Per-scenario summary",
        "",
        "| scenario | final NAV | cum. return | max drawdown | dd quarters | min coverage (mo) | mean coverage (mo) | shortfall freq |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        lines.append(
            f"| {r.name} "
            f"| ${r.final_nav:,.0f} "
            f"| {r.cum_return:+.2f}% "
            f"| {r.max_dd:+.2f}% "
            f"| {r.dd_quarters} "
            f"| {r.min_coverage:.1f} "
            f"| {r.mean_coverage:.1f} "
            f"| {r.shortfall * 100:.1f}% |"
        )
    lines.append("")
    lines.append("## Scenarios")
    lines.append("")
    for r in rows:
        lines.append(f"- **{r.name}** — {r.description} (run_id: `{r.run_id}`)")
    lines.append("")
    return "\n".join(lines)


def write_comparison_report(sweep: SweepResult) -> Path:
    """Write ``comparison.md`` + ``comparison.html`` to the sweep's output dir.

    Returns the path to ``comparison.html`` (the artifact named in the
    Phase 2 exit gate).
    """
    sweep.output_dir.mkdir(parents=True, exist_ok=True)
    rows = [_row_from_result(r) for r in sweep.results]
    md = _render_markdown(sweep, rows)
    (sweep.output_dir / "comparison.md").write_text(md, encoding="utf-8")
    html = _HTML_TEMPLATE.render(
        sweep_id=sweep.sweep_id,
        base_config_hash=sweep.base_config_hash,
        rows=rows,
    )
    html_path = sweep.output_dir / "comparison.html"
    html_path.write_text(html, encoding="utf-8")
    return html_path
