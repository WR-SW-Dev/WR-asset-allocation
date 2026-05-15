"""Phase MC-3 — Monte Carlo reporting and artifact generation.

Produce summary CSV, paths parquet, markdown report, and JSON manifest.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from aa_model.monte_carlo.result import MonteCarloResult


def write_monte_carlo_artifacts(
    result: MonteCarloResult,
    output_dir: Path | str,
    *,
    write_summary: bool = True,
    write_paths: bool = True,
    write_report: bool = True,
    write_manifest: bool = True,
) -> dict[str, Path]:
    """Write Monte Carlo outputs to disk.

    Parameters
    ----------
    result : MonteCarloResult
        Aggregated Monte Carlo result.
    output_dir : Path | str
        Directory for outputs. Created if not present.
    write_summary : bool
        Write monte_carlo_summary.csv (default True).
    write_paths : bool
        Write monte_carlo_paths.parquet (default True).
    write_report : bool
        Write monte_carlo_report.md (default True).
    write_manifest : bool
        Write monte_carlo_manifest.json (default True).

    Returns
    -------
    dict[str, Path]
        Map of artifact type to output path.
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    written: dict[str, Path] = {}

    if write_summary:
        summary_path = output_dir / "monte_carlo_summary.csv"
        _write_summary_csv(result, summary_path)
        written["summary"] = summary_path

    if write_paths:
        paths_path = output_dir / "monte_carlo_paths.parquet"
        _write_paths_parquet(result, paths_path)
        written["paths"] = paths_path

    if write_report:
        report_path = output_dir / "monte_carlo_report.md"
        _write_report_markdown(result, report_path)
        written["report"] = report_path

    if write_manifest:
        manifest_path = output_dir / "monte_carlo_manifest.json"
        _write_manifest_json(result, manifest_path)
        written["manifest"] = manifest_path

    return written


def _write_summary_csv(result: MonteCarloResult, path: Path) -> None:
    """Write summary metrics to CSV."""
    summary_data = {
        "metric": [
            "num_paths",
            "horizon_quarters",
            "seed",
            "probability_of_breach",
            "median_coverage_months",
            "p5_coverage_months",
            "p25_coverage_months",
            "p75_coverage_months",
            "p95_coverage_months",
            "worst_5pct_coverage",
            "best_5pct_coverage",
            "required_liquid_nav_80pct_confidence",
            "required_liquid_nav_90pct_confidence",
            "required_liquid_nav_95pct_confidence",
            "median_final_nav",
            "p5_final_nav",
            "p95_final_nav",
        ],
        "value": [
            result.num_paths,
            result.horizon_quarters,
            result.seed if result.seed is not None else "None",
            f"{result.probability_of_breach:.4f}",
            f"{result.median_coverage_months:.2f}",
            f"{result.p5_coverage_months:.2f}",
            f"{result.p25_coverage_months:.2f}",
            f"{result.p75_coverage_months:.2f}",
            f"{result.p95_coverage_months:.2f}",
            f"{result.worst_5pct_coverage:.2f}",
            f"{result.best_5pct_coverage:.2f}",
            f"${result.required_liquid_nav_80pct_confidence:,.0f}",
            f"${result.required_liquid_nav_90pct_confidence:,.0f}",
            f"${result.required_liquid_nav_95pct_confidence:,.0f}",
            f"${result.median_final_nav:,.0f}",
            f"${result.p5_final_nav:,.0f}",
            f"${result.p95_final_nav:,.0f}",
        ],
    }

    df = pd.DataFrame(summary_data)
    df.to_csv(path, index=False)


def _write_paths_parquet(result: MonteCarloResult, path: Path) -> None:
    """Write full path data to parquet."""
    rows = []

    for path_result in result.paths:
        for quarter in range(len(path_result.nav_by_quarter)):
            nav = path_result.nav_by_quarter.iloc[quarter] if quarter < len(path_result.nav_by_quarter) else 0.0
            liquid_nav = (
                path_result.liquid_nav_by_quarter.iloc[quarter]
                if quarter < len(path_result.liquid_nav_by_quarter)
                else 0.0
            )
            spending = (
                path_result.spending_by_quarter.iloc[quarter]
                if quarter < len(path_result.spending_by_quarter)
                else 0.0
            )
            coverage = (
                path_result.coverage_months_by_quarter.iloc[quarter]
                if quarter < len(path_result.coverage_months_by_quarter)
                else 0.0
            )

            is_breach = 1 if quarter in path_result.breached_quarters else 0

            rows.append(
                {
                    "path_id": path_result.path_id,
                    "seed": path_result.seed,
                    "quarter": quarter,
                    "nav_usd": nav,
                    "liquid_nav_usd": liquid_nav,
                    "spending_usd": spending,
                    "coverage_months": coverage,
                    "is_breach": is_breach,
                    "final_nav_usd": path_result.final_nav_usd,
                    "cumulative_return_pct": path_result.cumulative_return_pct,
                }
            )

    df = pd.DataFrame(rows)
    df.to_parquet(path, index=False)


def _write_report_markdown(result: MonteCarloResult, path: Path) -> None:
    """Write human-readable markdown report."""
    lines = []

    lines.append("# Monte Carlo Liquidity Stress Report\n")
    lines.append(f"**Generated:** {datetime.now(timezone.utc).isoformat()}\n")
    lines.append(f"**Config Hash:** `{result.config_hash}`\n")
    lines.append(f"**Fixture Hash:** `{result.fixture_hash}`\n")
    lines.append(f"**Seed:** {result.seed if result.seed is not None else 'None (non-deterministic)'}\n")

    lines.append("\n## Standing Advisory\n")
    lines.append(result.manifest.advisory_caveat)
    lines.append("\n")

    lines.append("\n## Synthetic Fixture Summary\n")
    lines.append("```")
    lines.append(result.manifest.synthetic_fixture_summary)
    lines.append("```\n")

    lines.append("\n## Simulation Parameters\n")
    lines.append(f"- **Paths:** {result.num_paths}")
    lines.append(f"- **Horizon:** {result.horizon_quarters} quarters")
    lines.append(f"- **Timestamp (UTC):** {result.manifest.timestamp_utc.isoformat()}\n")

    lines.append("\n## Key Results\n")
    lines.append(f"- **Probability of Liquidity Breach:** {result.probability_of_breach:.1%}")
    lines.append(f"- **Median Coverage (months of spending):** {result.median_coverage_months:.1f}")
    lines.append(f"- **Worst 5% Coverage:** {result.worst_5pct_coverage:.1f} months")
    lines.append(f"- **Best 5% Coverage:** {result.best_5pct_coverage:.1f} months\n")

    lines.append("\n## Coverage Percentiles\n")
    lines.append("| Percentile | Months of Coverage |")
    lines.append("|---|---|")
    lines.append(f"| 5th | {result.p5_coverage_months:.1f} |")
    lines.append(f"| 25th | {result.p25_coverage_months:.1f} |")
    lines.append(f"| 50th (Median) | {result.median_coverage_months:.1f} |")
    lines.append(f"| 75th | {result.p75_coverage_months:.1f} |")
    lines.append(f"| 95th | {result.p95_coverage_months:.1f} |")
    lines.append("")

    lines.append("\n## Required Liquid NAV (Confidence Levels)\n")
    lines.append("Reserve levels needed to achieve specified no-breach probability:\n")
    lines.append("| Confidence | Required Liquid NAV |")
    lines.append("|---|---|")
    lines.append(f"| 80% | ${result.required_liquid_nav_80pct_confidence:,.0f} |")
    lines.append(f"| 90% | ${result.required_liquid_nav_90pct_confidence:,.0f} |")
    lines.append(f"| 95% | ${result.required_liquid_nav_95pct_confidence:,.0f} |")
    lines.append("")

    lines.append("\n## Terminal NAV Distribution\n")
    lines.append("End-of-horizon NAV across all paths:\n")
    lines.append("| Percentile | NAV |")
    lines.append("|---|---|")
    lines.append(f"| 5th | ${result.p5_final_nav:,.0f} |")
    lines.append(f"| 50th (Median) | ${result.median_final_nav:,.0f} |")
    lines.append(f"| 95th | ${result.p95_final_nav:,.0f} |")
    lines.append("")

    lines.append("\n## Interpretation\n")
    lines.append("### Breach Probability\n")
    if result.probability_of_breach > 0.2:
        lines.append(
            f"**HIGH RISK:** {result.probability_of_breach:.1%} of simulated paths breach "
            "the liquidity threshold. Current structure is fragile under downside scenarios."
        )
    elif result.probability_of_breach > 0.05:
        lines.append(
            f"**MODERATE RISK:** {result.probability_of_breach:.1%} of paths breach. "
            "Consider reserve increases or liquidity rebalancing."
        )
    else:
        lines.append(
            f"**LOW RISK:** {result.probability_of_breach:.1%} of paths breach. "
            "Current liquidity structure is robust under synthetic stress."
        )
    lines.append("")

    lines.append("\n### Coverage Metrics\n")
    if result.median_coverage_months < 1.0:
        lines.append(
            "**Tight Liquidity:** Median coverage is below 1 month of annual spending. "
            "Limited buffer for market disruptions."
        )
    elif result.median_coverage_months < 3.0:
        lines.append(
            "**Adequate Base:** Median coverage is 1–3 months. Standard SFO range. "
            "Confirm alignment with IPS policy."
        )
    else:
        lines.append(
            f"**Strong Position:** Median coverage is {result.median_coverage_months:.1f} months. "
            "Well-cushioned for adverse scenarios."
        )
    lines.append("")

    lines.append("\n### Reserve Recommendation\n")
    lines.append(
        f"To achieve **80% confidence** of no breach under simulated stress, "
        f"increase liquid reserves by **${result.required_liquid_nav_80pct_confidence:,.0f}**.\n"
    )
    lines.append(
        f"To achieve **95% confidence**, increase by **${result.required_liquid_nav_95pct_confidence:,.0f}**.\n"
    )

    lines.append("\n## Caveats\n")
    lines.append("1. **Synthetic Assumptions:** Return volatility, spending shocks, and call timing")
    lines.append("   are from CMA long-term expectations and generic PE hazard rates.")
    lines.append("2. **Not Forecasts:** These are stress-test scenarios, not predictions.")
    lines.append("3. **Advisory Only:** Outputs are not decision-grade until deterministic spine")
    lines.append("   (L19 row classification, L20 workbook validation, Phase 23 PE data) is validated.")
    lines.append("4. **No Real Data:** Entity cash flows, manager terms, and PE actuals are not")
    lines.append("   yet integrated from live client sources.")
    lines.append("5. **Deterministic Path:** Run with seed=None for non-reproducible results;")
    lines.append("   with seed=int for reproducible, auditable stress tests.")
    lines.append("")

    path.write_text("\n".join(lines))


def _write_manifest_json(result: MonteCarloResult, path: Path) -> None:
    """Write audit trail to JSON."""
    manifest_dict = {
        "timestamp_utc": result.manifest.timestamp_utc.isoformat(),
        "config_hash": result.config_hash,
        "fixture_hash": result.fixture_hash,
        "num_paths": result.num_paths,
        "horizon_quarters": result.horizon_quarters,
        "seed": result.seed,
        "synthetic_fixture_summary": result.manifest.synthetic_fixture_summary,
        "advisory_caveat": result.manifest.advisory_caveat,
        "metrics": {
            "probability_of_breach": result.probability_of_breach,
            "median_coverage_months": result.median_coverage_months,
            "p5_coverage_months": result.p5_coverage_months,
            "p25_coverage_months": result.p25_coverage_months,
            "p75_coverage_months": result.p75_coverage_months,
            "p95_coverage_months": result.p95_coverage_months,
            "worst_5pct_coverage": result.worst_5pct_coverage,
            "best_5pct_coverage": result.best_5pct_coverage,
            "required_liquid_nav_80pct_confidence": result.required_liquid_nav_80pct_confidence,
            "required_liquid_nav_90pct_confidence": result.required_liquid_nav_90pct_confidence,
            "required_liquid_nav_95pct_confidence": result.required_liquid_nav_95pct_confidence,
            "median_final_nav": result.median_final_nav,
            "p5_final_nav": result.p5_final_nav,
            "p95_final_nav": result.p95_final_nav,
        },
    }

    path.write_text(json.dumps(manifest_dict, indent=2))


def monte_carlo_summary_table(result: MonteCarloResult) -> pd.DataFrame:
    """Return summary metrics as DataFrame (in-memory, no file I/O)."""
    summary_data = {
        "metric": [
            "num_paths",
            "horizon_quarters",
            "seed",
            "probability_of_breach",
            "median_coverage_months",
            "p5_coverage_months",
            "p25_coverage_months",
            "p75_coverage_months",
            "p95_coverage_months",
            "worst_5pct_coverage",
            "best_5pct_coverage",
            "required_liquid_nav_80pct_confidence",
            "required_liquid_nav_90pct_confidence",
            "required_liquid_nav_95pct_confidence",
            "median_final_nav",
            "p5_final_nav",
            "p95_final_nav",
        ],
        "value": [
            result.num_paths,
            result.horizon_quarters,
            result.seed if result.seed is not None else "None",
            result.probability_of_breach,
            result.median_coverage_months,
            result.p5_coverage_months,
            result.p25_coverage_months,
            result.p75_coverage_months,
            result.p95_coverage_months,
            result.worst_5pct_coverage,
            result.best_5pct_coverage,
            result.required_liquid_nav_80pct_confidence,
            result.required_liquid_nav_90pct_confidence,
            result.required_liquid_nav_95pct_confidence,
            result.median_final_nav,
            result.p5_final_nav,
            result.p95_final_nav,
        ],
    }

    return pd.DataFrame(summary_data)


def monte_carlo_paths_dataframe(result: MonteCarloResult) -> pd.DataFrame:
    """Return all path data as DataFrame (in-memory, no file I/O)."""
    rows = []

    for path_result in result.paths:
        for quarter in range(len(path_result.nav_by_quarter)):
            nav = path_result.nav_by_quarter.iloc[quarter] if quarter < len(path_result.nav_by_quarter) else 0.0
            liquid_nav = (
                path_result.liquid_nav_by_quarter.iloc[quarter]
                if quarter < len(path_result.liquid_nav_by_quarter)
                else 0.0
            )
            spending = (
                path_result.spending_by_quarter.iloc[quarter]
                if quarter < len(path_result.spending_by_quarter)
                else 0.0
            )
            coverage = (
                path_result.coverage_months_by_quarter.iloc[quarter]
                if quarter < len(path_result.coverage_months_by_quarter)
                else 0.0
            )

            is_breach = 1 if quarter in path_result.breached_quarters else 0

            rows.append(
                {
                    "path_id": path_result.path_id,
                    "seed": path_result.seed,
                    "quarter": quarter,
                    "nav_usd": nav,
                    "liquid_nav_usd": liquid_nav,
                    "spending_usd": spending,
                    "coverage_months": coverage,
                    "is_breach": is_breach,
                    "final_nav_usd": path_result.final_nav_usd,
                    "cumulative_return_pct": path_result.cumulative_return_pct,
                }
            )

    return pd.DataFrame(rows)
