"""Import a Morningstar Direct index-return export into the normalized store.

Default mode is DRY-RUN / validation: it parses, validates the mapping, and
prints a coverage report but writes nothing. Pass ``--write`` to persist the
normalized store (and ``--coverage-report`` to persist the coverage CSV).

Examples
--------
Dry run (validate + preview, no writes)::

    python scripts/import_morningstar_index_returns.py \\
      --input "data/vendor/morningstar/raw/Index Returns - June 30 2026.xlsx" \\
      --universe configs/morningstar_index_universe.yaml \\
      --asset-class-map configs/asset_class_index_map.yaml \\
      --output data/normalized/morningstar_index_returns.parquet \\
      --coverage-report reports/morningstar_index_coverage.csv \\
      --dry-run

Persist::

    python scripts/import_morningstar_index_returns.py \\
      --input "data/vendor/morningstar/raw/Index Returns - June 30 2026.xlsx" \\
      --universe configs/morningstar_index_universe.yaml \\
      --asset-class-map configs/asset_class_index_map.yaml \\
      --output data/normalized/morningstar_index_returns.parquet \\
      --coverage-report reports/morningstar_index_coverage.csv \\
      --write

Never reads live Morningstar; consumes a manual export only. Raw exports and
normalized outputs are gitignored (licensed vendor data).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Make the package importable when run as a plain script (no editable install).
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aa_model.ingestion.morningstar_returns import (  # noqa: E402
    MorningstarIngestError,
    run_ingestion,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]
_DEFAULT_UNIVERSE = _REPO_ROOT / "configs" / "morningstar_index_universe.yaml"
_DEFAULT_MAP = _REPO_ROOT / "configs" / "asset_class_index_map.yaml"


def _write_normalized(df, out: Path) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.suffix.lower() == ".parquet":
        df.to_parquet(out, index=False)
    else:
        df.to_csv(out, index=False)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--input", required=True, help="Morningstar export (.xlsx/.xlsm/.csv).")
    ap.add_argument("--universe", default=str(_DEFAULT_UNIVERSE), help="Index universe YAML.")
    ap.add_argument("--asset-class-map", default=str(_DEFAULT_MAP), help="Asset-class map YAML.")
    ap.add_argument("--output", default=None, help="Normalized output path (.parquet/.csv).")
    ap.add_argument("--coverage-report", default=None, help="Coverage report CSV path.")
    ap.add_argument("--sheet", default="Common Indices", help="Worksheet name (xlsx only).")
    ap.add_argument("--asof", default=None, help="As-of date YYYY-MM-DD (default: modal return date).")
    ap.add_argument(
        "--value-scale",
        choices=["percent", "decimal"],
        default="percent",
        help="Source value units. 'percent' divides by 100 exactly once.",
    )
    ap.add_argument("--allow-unmapped", action="store_true", help="Permit workbook rows not in the universe.")
    ap.add_argument(
        "--allow-missing-configured",
        action="store_true",
        help="Permit configured indices absent from the workbook.",
    )
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--dry-run", action="store_true", default=True, help="Validate only (default).")
    grp.add_argument("--write", dest="write", action="store_true", help="Persist outputs.")
    args = ap.parse_args(argv)

    try:
        result = run_ingestion(
            args.input,
            universe_path=args.universe,
            asset_class_map_path=args.asset_class_map,
            sheet=args.sheet,
            asof=args.asof,
            value_scale=args.value_scale,
            allow_unmapped=args.allow_unmapped,
            allow_missing_configured=args.allow_missing_configured,
        )
    except (MorningstarIngestError, FileNotFoundError) as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2

    print("=== Morningstar index-return ingestion ===")
    print(json.dumps(result.meta, indent=2))
    if result.unmapped_names:
        print(f"\n[WARN] {len(result.unmapped_names)} unmapped workbook name(s): {result.unmapped_names}")
    if result.missing_configured:
        print(
            f"\n[WARN] {len(result.missing_configured)} configured index/indices missing "
            f"from workbook: {result.missing_configured}"
        )

    cov = result.coverage
    print(f"\n=== Coverage ({len(cov)} configured indices) ===")
    with_pd_opts = cov[
        [
            "index_key",
            "present_in_workbook",
            "return_date",
            "n_monthly_observations",
            "n_horizons",
            "stale_series",
            "short_history_flag",
            "quality_flags",
        ]
    ]
    print(with_pd_opts.to_string(index=False))

    n_stale = int(cov["stale_series"].sum())
    n_absent = int((~cov["present_in_workbook"]).sum())
    print(f"\nSummary: {len(cov)} indices | stale={n_stale} | absent_from_workbook={n_absent} "
          f"| normalized_rows={len(result.normalized)}")

    if args.write:
        if args.output:
            _write_normalized(result.normalized, Path(args.output))
            print(f"\nWrote normalized store: {args.output}")
        else:
            print("\n[WARN] --write given but no --output path; normalized store not persisted.")
        if args.coverage_report:
            cov_path = Path(args.coverage_report)
            cov_path.parent.mkdir(parents=True, exist_ok=True)
            cov.to_csv(cov_path, index=False)
            print(f"Wrote coverage report: {args.coverage_report}")
    else:
        print("\n(dry run — pass --write to persist --output / --coverage-report)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
