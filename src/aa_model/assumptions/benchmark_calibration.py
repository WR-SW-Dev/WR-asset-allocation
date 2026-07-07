"""Empirical CMA calibration from the Morningstar benchmark data feed.

Thin, optional adapter between the ``morningstar_feed`` data feed
(``C:\\Projects\\morningstar``) and this model's capital market assumptions.
It maps each allocation *bucket* to a public benchmark proxy and derives
**empirical** annualized volatility, a correlation matrix, and trailing
annualized returns from daily total-return history.

It does **not** change model behavior: nothing here is imported by the
orchestrator or allocators. Production CMAs still come from ``configs/cma.yaml``
(:func:`aa_model.io.loaders.load_cma_config`). Use this to *inform or
cross-check* those hand-set assumptions, or to emit a calibrated candidate
YAML for review (see ``scripts/calibrate_cma_from_benchmarks.py``).

The ``morningstar_feed`` dependency is soft: it is imported lazily, and if it
is not installed the adapter looks for a ``MORNINGSTAR_FEED_DIR`` env var (the
feed checkout) before raising a clear, actionable error.
"""

from __future__ import annotations

import datetime as _dt
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType

import numpy as np
import pandas as pd
import yaml

_REPO_ROOT = Path(__file__).resolve().parents[3]
_DEFAULT_PROXY_CONFIG = _REPO_ROOT / "configs" / "benchmark_proxies.yaml"
_DEFAULT_CMA_CONFIG = _REPO_ROOT / "configs" / "cma.yaml"
_TRADING_DAYS = 252


def _import_feed() -> ModuleType:
    """Import ``morningstar_feed``; fall back to ``MORNINGSTAR_FEED_DIR`` on the path."""
    try:
        import morningstar_feed  # type: ignore

        return morningstar_feed
    except ImportError:
        feed_dir = os.environ.get("MORNINGSTAR_FEED_DIR")
        if feed_dir and (Path(feed_dir) / "morningstar_feed.py").exists():
            sys.path.insert(0, feed_dir)
            import morningstar_feed  # type: ignore

            return morningstar_feed
        raise ImportError(
            "morningstar_feed is not available. Either `pip install -e "
            "C:/Projects/morningstar`, or set MORNINGSTAR_FEED_DIR to that checkout."
        ) from None


@dataclass(frozen=True)
class EmpiricalMoments:
    """Empirical moments per bucket, derived from benchmark daily returns.

    Attributes:
        vol_annual: index = bucket, annualized volatility (fraction, e.g. 0.16).
        corr: bucket x bucket correlation matrix of daily returns.
        return_annual: index = bucket, trailing annualized total return (fraction).
        proxies: bucket -> benchmark name actually used.
        window: (start, end) dates of the return sample.
        n_obs: number of aligned trading-day observations.
    """

    vol_annual: pd.Series
    corr: pd.DataFrame
    return_annual: pd.Series
    proxies: dict[str, str]
    window: tuple[_dt.date, _dt.date]
    n_obs: int


def load_proxy_map(path: Path | str | None = None) -> tuple[dict[str, str], dict]:
    """Load the bucket -> benchmark proxy map and params from YAML.

    Returns ``(proxies, params)`` where params carries ``lookback_years`` and
    ``annualization_factor`` (with sensible defaults if absent).
    """
    p = Path(path) if path is not None else _DEFAULT_PROXY_CONFIG
    cfg = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
    proxies = {str(k): str(v) for k, v in (cfg.get("proxies") or {}).items()}
    params = {
        "lookback_years": int(cfg.get("lookback_years", 5)),
        "annualization_factor": int(cfg.get("annualization_factor", _TRADING_DAYS)),
    }
    return proxies, params


def empirical_moments(
    proxies: dict[str, str] | None = None,
    *,
    lookback_years: int | None = None,
    as_of: _dt.date | str | None = None,
    annualization_factor: int | None = None,
) -> EmpiricalMoments:
    """Compute empirical vol / correlation / trailing return per bucket.

    Buckets without a benchmark proxy (e.g. ``pe_buyout``) are simply omitted;
    the caller overlays those from the hand-set CMA.
    """
    if proxies is None:
        proxies, params = load_proxy_map()
        lookback_years = lookback_years or params["lookback_years"]
        annualization_factor = annualization_factor or params["annualization_factor"]
    lookback_years = lookback_years or 5
    ann = annualization_factor or _TRADING_DAYS
    if not proxies:
        raise ValueError(
            "No bucket->benchmark proxies configured (see configs/benchmark_proxies.yaml)."
        )

    mf = _import_feed()
    end = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp(mf.latest_date())
    start = end - pd.DateOffset(years=lookback_years)

    names = list(proxies.values())
    # feed returns daily percent; align on common trading days, drop non-trading zeros
    daily_pct = mf.load_daily_returns(names, start=start, end=end, trading_days_only=True)
    rev = {v: k for k, v in proxies.items()}
    daily_pct = daily_pct.rename(columns=rev)[list(proxies)].dropna()
    frac = daily_pct / 100.0

    vol_annual = frac.std(ddof=1) * np.sqrt(ann)
    vol_annual.name = None
    corr = frac.corr()
    return_annual = pd.Series(
        {
            b: mf.trailing_return(proxies[b], f"{lookback_years}Y", as_of=end) / 100.0
            for b in proxies
        },
        dtype=float,
    )

    return EmpiricalMoments(
        vol_annual=vol_annual.reindex(list(proxies)),
        corr=corr.reindex(index=list(proxies), columns=list(proxies)),
        return_annual=return_annual.reindex(list(proxies)),
        proxies=dict(proxies),
        window=(start.date(), end.date()),
        n_obs=int(len(frac)),
    )


def to_cma_yaml_dict(
    moments: EmpiricalMoments,
    base_cma_path: Path | str | None = _DEFAULT_CMA_CONFIG,
    *,
    include_expected_returns: bool = False,
) -> dict:
    """Render empirical moments into a ``cma.yaml``-shaped dict.

    Overlays the empirically-calibrated buckets onto the base ``cma.yaml`` so
    unmapped buckets (e.g. ``pe_buyout``) and ``liquidity`` are preserved. By
    default expected returns are left as the base config's (historical trailing
    returns are a poor forward CMA); pass ``include_expected_returns=True`` to
    write the trailing figures too.
    """
    base: dict = {}
    if base_cma_path is not None and Path(base_cma_path).exists():
        base = yaml.safe_load(Path(base_cma_path).read_text(encoding="utf-8")) or {}

    buckets_all = list(base.get("vol_annual", {}).keys()) or list(moments.vol_annual.index)
    out = {k: dict(v) if isinstance(v, dict) else v for k, v in base.items()}

    out.setdefault("vol_annual", {})
    for b in moments.vol_annual.index:
        out["vol_annual"][b] = round(float(moments.vol_annual[b]), 6)

    corr_out = out.setdefault("correlations", {})
    calibrated = list(moments.corr.index)
    for i in buckets_all:
        row = dict(corr_out.get(i, {}))
        for j in buckets_all:
            if i in calibrated and j in calibrated:
                row[j] = round(float(moments.corr.loc[i, j]), 6)
            else:
                row.setdefault(j, 1.0 if i == j else 0.0)
        corr_out[i] = row

    if include_expected_returns:
        er = out.setdefault("expected_returns_annual", {})
        for b in moments.return_annual.index:
            er[b] = round(float(moments.return_annual[b]), 6)

    out["_provenance"] = {
        "source": "morningstar_feed empirical calibration",
        "window": f"{moments.window[0]} -> {moments.window[1]}",
        "n_obs": moments.n_obs,
        "proxies": moments.proxies,
        "generated_at": _dt.datetime.now().isoformat(timespec="seconds"),
        "note": "vol/correlation are empirical; expected returns remain forward CMA unless overridden.",
    }
    return out
