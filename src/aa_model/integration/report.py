"""Markdown run report.

Phase 1: minimal — run id, hashes, scenario, horizon, initial / final NAV,
cumulative return, end-of-horizon allocation, total NAV per quarter.
HTML rendering is a Phase 4 deliverable.
"""

from __future__ import annotations

from pathlib import Path

from aa_model.integration.ledger import QuarterlyLedger
from aa_model.io.schemas import StudyConfig


def write_markdown_report(
    path: Path,
    *,
    cfg: StudyConfig,
    ledger: QuarterlyLedger,
    run_id: str,
    config_hash: str,
    fixtures_hash: str,
) -> None:
    end_nav = ledger.end_nav_by_quarter()
    initial_total = sum(ledger.initial_nav.values())
    if not end_nav.empty:
        final_total = float(end_nav.iloc[-1].sum())
        last_q = str(end_nav.index[-1])
    else:
        final_total = initial_total
        last_q = ""

    lines: list[str] = []
    lines.append(f"# Run report — {run_id}")
    lines.append("")
    lines.append(f"- config_hash: `{config_hash}`")
    lines.append(f"- fixtures_hash: `{fixtures_hash}`")
    lines.append(
        f"- scenario: `{cfg.fixture_scenario.name}` — {cfg.fixture_scenario.description}"
    )
    lines.append(
        f"- horizon: {cfg.base.horizon.start_quarter} + {cfg.base.horizon.num_quarters}q"
    )
    lines.append("")
    lines.append("## Total NAV")
    lines.append("")
    lines.append(f"- initial: ${initial_total:,.0f}")
    lines.append(f"- final ({last_q}): ${final_total:,.0f}")
    if initial_total > 0:
        ret = (final_total / initial_total) - 1.0
        lines.append(f"- cumulative return: {ret * 100:.2f}%")
    lines.append("")

    if not end_nav.empty:
        lines.append("## End-of-horizon allocation")
        lines.append("")
        last = end_nav.iloc[-1]
        total = float(last.sum())
        if total != 0:
            for bucket in last.index:
                v = float(last[bucket])
                pct = v / total * 100.0 if total != 0 else 0.0
                lines.append(f"- {bucket}: {pct:.2f}% (${v:,.0f})")
        lines.append("")

        lines.append("## Total NAV by quarter")
        lines.append("")
        lines.append("| quarter | total NAV |")
        lines.append("|---|---|")
        for q, row in end_nav.iterrows():
            lines.append(f"| {q} | ${float(row.sum()):,.0f} |")
        lines.append("")

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
