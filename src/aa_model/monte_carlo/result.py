"""Phase MC-1 — Monte Carlo result dataclasses.

Frozen (immutable). Same inputs → byte-stable output.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

import pandas as pd


@dataclass(frozen=True)
class MonteCarloPathResult:
    """One stochastic liquidity path (deterministic once computed).

    Attributes
    ----------
    path_id : int
        Path index in [0, num_paths).
    seed : int
        Seed used for this path (reproducible).
    nav_by_quarter : pd.Series
        Total NAV by quarter_end_date (float indexed).
    liquid_nav_by_quarter : pd.Series
        Liquid NAV (cash + public_bond) by quarter (float indexed).
    spending_by_quarter : pd.Series
        Quarterly spending amount.
    coverage_months_by_quarter : pd.Series
        Months of spending covered by liquid NAV per quarter.
    breached_quarters : list[int]
        Quarter indices where coverage < breach_threshold.
    earliest_breach_quarter : int | None
        First quarter_index with breach; None if no breach.
    final_nav_usd : float
        Terminal NAV at horizon end.
    final_liquid_nav_usd : float
        Terminal liquid NAV.
    cumulative_return_pct : float
        Total return from start to end (e.g., 0.25 = +25%).
    max_drawdown_pct : float
        Worst peak-to-trough decline (≤ 0).
    drawdown_quarters : int
        Duration of max drawdown in quarters.
    required_initial_liquid_nav : float
        Minimum *initial* liquid NAV this path would have needed to avoid
        any coverage breach, given its own realized returns / spending / PE
        calls. Closed-form (see ``runner._required_initial_liquid_nav``);
        ``float('inf')`` when no finite reserve suffices (gross return factor
        turns non-positive). Aggregated across paths into the confidence-level
        reserves on :class:`MonteCarloResult`.
    """

    path_id: int
    seed: int
    nav_by_quarter: pd.Series
    liquid_nav_by_quarter: pd.Series
    spending_by_quarter: pd.Series
    coverage_months_by_quarter: pd.Series
    breached_quarters: list[int] = field(default_factory=list)
    earliest_breach_quarter: int | None = None
    final_nav_usd: float = 0.0
    final_liquid_nav_usd: float = 0.0
    cumulative_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    drawdown_quarters: int = 0
    required_initial_liquid_nav: float = 0.0


@dataclass(frozen=True)
class MonteCarloManifest:
    """Audit trail for Monte Carlo run.

    Attributes
    ----------
    timestamp_utc : datetime
        Run timestamp (UTC).
    config_hash : str
        SHA256 of MonteCarloConfig (excludes seed).
    fixture_hash : str
        SHA256 of all synthetic fixtures (return / spending / call scenarios).
    num_paths : int
        Number of paths generated.
    horizon_quarters : int
        Horizon used.
    seed : int | None
        Random seed (None → no replay).
    synthetic_fixture_summary : str
        Human-readable description of synthetic assumptions.
    advisory_caveat : str
        Standing advisory text (outputs not decision-grade until real data).
    """

    timestamp_utc: datetime
    config_hash: str
    fixture_hash: str
    num_paths: int
    horizon_quarters: int
    seed: int | None
    synthetic_fixture_summary: str = ""
    advisory_caveat: str = (
        "These Monte Carlo results are stochastic stress-test simulations "
        "using synthetic assumptions. Not suitable for final family-unit "
        "liquidity decisions until deterministic spine validated."
    )


@dataclass(frozen=True)
class MonteCarloResult:
    """Aggregated Monte Carlo results across all paths.

    Attributes
    ----------
    paths : list[MonteCarloPathResult]
        All generated paths.
    config_hash : str
        Config hash (from MonteCarloConfig).
    fixture_hash : str
        Fixture hash (all synthetic inputs).
    num_paths : int
        Number of paths.
    horizon_quarters : int
        Horizon in quarters.
    seed : int | None
        Random seed (reproducibility).
    probability_of_breach : float
        Fraction of paths with coverage < breach_threshold.
    median_coverage_months : float
        Median coverage across all quarters and paths.
    p5_coverage_months : float
        5th percentile.
    p25_coverage_months : float
        25th percentile.
    p75_coverage_months : float
        75th percentile.
    p95_coverage_months : float
        95th percentile.
    worst_5pct_coverage : float
        Minimum coverage from worst-5% paths.
    best_5pct_coverage : float
        Maximum coverage from best-5% paths.
    required_liquid_nav_80pct_confidence : float
        Absolute initial liquid NAV that covers 80% of paths without a
        breach — the 80th-percentile order statistic of each path's
        closed-form ``required_initial_liquid_nav``.
    required_liquid_nav_90pct_confidence : float
        As above, at 90% path coverage.
    required_liquid_nav_95pct_confidence : float
        As above, at 95% path coverage.
    median_final_nav : float
        Median terminal NAV.
    p5_final_nav : float
        5th percentile terminal NAV.
    p95_final_nav : float
        95th percentile terminal NAV.
    manifest : MonteCarloManifest
        Audit trail.
    """

    paths: list[MonteCarloPathResult]
    config_hash: str
    fixture_hash: str
    num_paths: int
    horizon_quarters: int
    seed: int | None
    probability_of_breach: float
    median_coverage_months: float
    p5_coverage_months: float
    p25_coverage_months: float
    p75_coverage_months: float
    p95_coverage_months: float
    worst_5pct_coverage: float
    best_5pct_coverage: float
    required_liquid_nav_80pct_confidence: float
    required_liquid_nav_90pct_confidence: float
    required_liquid_nav_95pct_confidence: float
    median_final_nav: float
    p5_final_nav: float
    p95_final_nav: float
    manifest: MonteCarloManifest
