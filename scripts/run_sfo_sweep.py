"""End-to-end Phase 2 scenario sweep runner.

Usage::

    python scripts/run_sfo_sweep.py --config configs/base.yaml
    python scripts/run_sfo_sweep.py --config configs/base.yaml --dry-run
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow direct ``python scripts/run_sfo_sweep.py`` from the repo root without
# requiring an editable install.
_REPO_SRC = Path(__file__).resolve().parent.parent / "src"
if _REPO_SRC.is_dir() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))

from aa_model.assumptions.scenario_builder import make_scenarios  # noqa: E402
from aa_model.integration.comparison_report import write_comparison_report  # noqa: E402
from aa_model.integration.sweep import run_scenario_sweep  # noqa: E402
from aa_model.io.loaders import load_study_config  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the Phase 2 scenario sweep and write comparison.html."
    )
    parser.add_argument("--config", required=True, type=Path, help="path to base.yaml")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="validate + run in memory; skip per-run and comparison artifacts",
    )
    parser.add_argument(
        "--invocation-id",
        default=None,
        help="explicit timestamp/nonce stem for the sweep id (default = generated)",
    )
    args = parser.parse_args(argv)

    cfg = load_study_config(args.config)
    scenarios = make_scenarios(cfg.fixture_scenario, cfg.pe_pacing, cfg.spending)
    sweep = run_scenario_sweep(
        args.config,
        scenarios,
        invocation_id=args.invocation_id,
        dry_run=args.dry_run,
    )
    print(f"sweep_id:   {sweep.sweep_id}")
    print(f"output_dir: {sweep.output_dir}")
    print(f"scenarios:  {len(sweep.results)}")
    for r in sweep.results:
        m = r.metrics
        print(
            f"  - {r.name:30s}  final=${m.final_nav_usd:>14,.0f}  "
            f"return={m.cumulative_return_pct:+6.2f}%  "
            f"min_cov={m.min_coverage_months:5.1f}mo  "
            f"max_dd={m.max_drawdown_pct:+6.2f}%"
        )
    if not args.dry_run:
        html_path = write_comparison_report(sweep)
        print(f"comparison: {html_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
