"""``aa-model`` CLI entry point. Registered in pyproject.toml [project.scripts]."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from aa_model.assumptions.scenario_builder import make_scenarios
from aa_model.integration.comparison_report import write_comparison_report
from aa_model.integration.orchestrator import run_orchestrator
from aa_model.integration.sweep import run_scenario_sweep
from aa_model.io.loaders import load_study_config


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aa-model",
        description="SFO asset allocation study runner.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="run the study end-to-end")
    run.add_argument("--config", required=True, type=Path, help="path to base.yaml")
    run.add_argument(
        "--dry-run",
        action="store_true",
        help="validate configs + compute hashes, print manifest preview, write nothing",
    )
    run.add_argument(
        "--invocation-id",
        default=None,
        help=(
            "explicit per-invocation suffix for run_id; default = UTC timestamp + "
            "4-char hex nonce. Override to reproduce a specific historical run dir."
        ),
    )

    sweep = sub.add_parser("sweep", help="run the Phase 2 scenario set + write comparison.html")
    sweep.add_argument("--config", required=True, type=Path, help="path to base.yaml")
    sweep.add_argument(
        "--dry-run",
        action="store_true",
        help="validate + run scenarios in memory; do not write per-run or comparison artifacts",
    )
    sweep.add_argument(
        "--invocation-id",
        default=None,
        help="explicit timestamp/nonce stem for the sweep id (default = generated)",
    )
    return parser


def _run(args: argparse.Namespace) -> int:
    result = run_orchestrator(args.config, dry_run=args.dry_run, invocation_id=args.invocation_id)
    print(f"run_id:        {result.run_id}")
    print(f"output_dir:    {result.output_dir}")
    print(f"rows:          {len(result.ledger)}")
    print(f"config_hash:   {result.manifest.config_hash}")
    print(f"fixtures_hash: {result.manifest.fixtures_hash}")
    if args.dry_run:
        print("--- manifest preview (dry run) ---")
        print(json.dumps(result.manifest.to_dict(), sort_keys=True, indent=2))
    return 0


def _sweep(args: argparse.Namespace) -> int:
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
    else:
        print("(dry run — no comparison.html written)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.command == "run":
        return _run(args)
    if args.command == "sweep":
        return _sweep(args)
    parser.error(f"unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
