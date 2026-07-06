"""Empirically calibrate CMA vol/correlation from the Morningstar benchmark feed.

Read-only diagnostic + candidate generator. Prints an empirical moments table
comparing against the current configs/cma.yaml, and (with --write) emits a
calibrated candidate YAML for REVIEW. It never overwrites configs/cma.yaml.

Usage:
    python scripts/calibrate_cma_from_benchmarks.py
    python scripts/calibrate_cma_from_benchmarks.py --lookback 7 --write
    python scripts/calibrate_cma_from_benchmarks.py --as-of 2026-06-30 --with-returns

Requires the morningstar_feed data feed:
    pip install -e C:/Projects/morningstar     # or set MORNINGSTAR_FEED_DIR
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import yaml

# Make the package importable when run as a plain script (no editable install).
_SRC = Path(__file__).resolve().parents[1] / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from aa_model.assumptions.benchmark_calibration import (  # noqa: E402
    _DEFAULT_CMA_CONFIG,
    empirical_moments,
    load_proxy_map,
    to_cma_yaml_dict,
)

_REPO_ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--lookback", type=int, default=None, help="Lookback years (default: config).")
    ap.add_argument("--as-of", default=None, help="As-of date YYYY-MM-DD (default: feed latest).")
    ap.add_argument("--with-returns", action="store_true", help="Include trailing returns in candidate.")
    ap.add_argument("--write", action="store_true", help="Write configs/cma_empirical.yaml candidate.")
    ap.add_argument("--out", default=None, help="Output path (default configs/cma_empirical.yaml).")
    args = ap.parse_args()

    proxies, params = load_proxy_map()
    m = empirical_moments(proxies, lookback_years=args.lookback, as_of=args.as_of)

    base = yaml.safe_load(_DEFAULT_CMA_CONFIG.read_text(encoding="utf-8")) or {}
    base_vol = base.get("vol_annual", {})

    print(f"Empirical CMA calibration  |  window {m.window[0]} -> {m.window[1]}  |  n={m.n_obs} obs")
    print(f"{'bucket':16}{'proxy':44}{'vol emp':>9}{'vol cma':>9}{'ret ann':>9}")
    for b in m.vol_annual.index:
        cma_v = base_vol.get(b)
        cma_s = f"{cma_v:.3f}" if isinstance(cma_v, (int, float)) else "   -"
        print(f"{b:16}{proxies[b][:42]:44}{m.vol_annual[b]:>9.3f}{cma_s:>9}{m.return_annual[b]:>9.3f}")
    print("\nCorrelation (empirical):")
    print(m.corr.round(3).to_string())

    if args.write:
        out = Path(args.out) if args.out else _REPO_ROOT / "configs" / "cma_empirical.yaml"
        doc = to_cma_yaml_dict(m, include_expected_returns=args.with_returns)
        out.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
        print(f"\nWrote candidate (for review, NOT loaded by the model): {out}")
    else:
        print("\n(dry run — pass --write to emit configs/cma_empirical.yaml for review)")


if __name__ == "__main__":
    main()
