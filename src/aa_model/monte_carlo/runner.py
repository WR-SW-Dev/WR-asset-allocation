"""Phase MC-1 — Monte Carlo runner and orchestration.

MonteCarloRunner: entry point for generating stochastic paths,
computing per-path metrics, aggregating results.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime

import numpy as np
import pandas as pd

from aa_model.monte_carlo.config import MonteCarloConfig
from aa_model.monte_carlo.random_paths import RandomPathGenerator
from aa_model.monte_carlo.result import MonteCarloManifest, MonteCarloPathResult, MonteCarloResult


def compute_monte_carlo(
    config: MonteCarloConfig,
    *,
    initial_nav: float,
    initial_liquid_nav: float,
    annual_spend: float,
    base_pe_commitments: dict[str, float] | None = None,
    breach_threshold: float = 1.0,
    confidence_levels: list[float] | None = None,
) -> MonteCarloResult:
    """Run Monte Carlo stochastic liquidity stress simulation.

    Parameters
    ----------
    config : MonteCarloConfig
        Configuration (scenarios, num_paths, horizon, seed).
    initial_nav : float
        Starting total NAV (USD).
    initial_liquid_nav : float
        Starting liquid NAV (cash + public_bond).
    annual_spend : float
        Starting annual spending (USD).
    base_pe_commitments : dict[str, float] | None
        Commitments by pe_sleeve for call timing (keyed by sleeve name).
        If None, no PE calls are modeled.
    breach_threshold : float
        Coverage threshold below which a quarter is a breach
        (default 1.0 = annual spend).
    confidence_levels : list[float] | None
        Confidence levels for required-reserve calculation
        (default [0.80, 0.90, 0.95]).

    Returns
    -------
    MonteCarloResult
        Aggregated result across all paths: breach probability, percentiles,
        required reserves, terminal NAV metrics.

    Raises
    ------
    ValueError
        If config is invalid or inputs are inconsistent.
    """
    if not isinstance(config, MonteCarloConfig):
        raise TypeError("config must be MonteCarloConfig")
    if initial_nav <= 0:
        raise ValueError(f"initial_nav must be > 0; got {initial_nav}")
    if initial_liquid_nav < 0:
        raise ValueError(f"initial_liquid_nav must be >= 0; got {initial_liquid_nav}")
    if initial_liquid_nav > initial_nav:
        raise ValueError(f"initial_liquid_nav > initial_nav ({initial_liquid_nav} > {initial_nav})")
    if annual_spend <= 0:
        raise ValueError(f"annual_spend must be > 0; got {annual_spend}")

    if confidence_levels is None:
        confidence_levels = [0.80, 0.90, 0.95]

    base_pe_commitments = base_pe_commitments or {}

    # Compute fixture hash from scenarios
    fixture_hash = _compute_fixture_hash(config)

    # Generate paths
    generator = RandomPathGenerator(config)
    paths: list[MonteCarloPathResult] = []

    for path_id in range(config.num_paths):
        seed = config.random_seed if config.random_seed is not None else None
        path = _generate_single_path(
            generator=generator,
            path_id=path_id,
            seed=seed,
            initial_nav=initial_nav,
            initial_liquid_nav=initial_liquid_nav,
            annual_spend=annual_spend,
            base_pe_commitments=base_pe_commitments,
            breach_threshold=breach_threshold,
        )
        paths.append(path)

    # Aggregate metrics
    all_coverages = np.concatenate(
        [path.coverage_months_by_quarter.values for path in paths if not path.coverage_months_by_quarter.empty]
    )

    all_final_navs = np.array([path.final_nav_usd for path in paths])

    breach_count = sum(1 for path in paths if path.breached_quarters)
    probability_of_breach = breach_count / config.num_paths

    percentiles = np.percentile(all_coverages, [5, 25, 50, 75, 95])
    median_coverage = float(np.median(all_coverages))
    p5_coverage = float(percentiles[0])
    p25_coverage = float(percentiles[1])
    p75_coverage = float(percentiles[3])
    p95_coverage = float(percentiles[4])

    # Worst 5% coverage: min of top 5% worst paths
    worst_5pct_count = max(1, config.num_paths // 20)
    worst_5pct_indices = np.argsort(all_coverages)[:worst_5pct_count]
    worst_5pct_coverage = float(np.mean(all_coverages[worst_5pct_indices]))

    # Best 5% coverage
    best_5pct_indices = np.argsort(all_coverages)[-worst_5pct_count:]
    best_5pct_coverage = float(np.mean(all_coverages[best_5pct_indices]))

    # Required reserves: empirical quantile of each path's closed-form
    # minimum initial liquid NAV, one per confidence level.
    req_nav_80, req_nav_90, req_nav_95 = _aggregate_required_reserves(
        paths, confidence_levels
    )

    # Final NAV percentiles
    median_final_nav = float(np.median(all_final_navs))
    p5_final_nav = float(np.percentile(all_final_navs, 5))
    p95_final_nav = float(np.percentile(all_final_navs, 95))

    manifest = MonteCarloManifest(
        timestamp_utc=datetime.now(UTC),
        config_hash=config.config_hash,
        fixture_hash=fixture_hash,
        num_paths=config.num_paths,
        horizon_quarters=config.horizon_quarters,
        seed=config.random_seed,
        synthetic_fixture_summary=_build_fixture_summary(config),
    )

    return MonteCarloResult(
        paths=paths,
        config_hash=config.config_hash,
        fixture_hash=fixture_hash,
        num_paths=config.num_paths,
        horizon_quarters=config.horizon_quarters,
        seed=config.random_seed,
        probability_of_breach=probability_of_breach,
        median_coverage_months=median_coverage,
        p5_coverage_months=p5_coverage,
        p25_coverage_months=p25_coverage,
        p75_coverage_months=p75_coverage,
        p95_coverage_months=p95_coverage,
        worst_5pct_coverage=worst_5pct_coverage,
        best_5pct_coverage=best_5pct_coverage,
        required_liquid_nav_80pct_confidence=req_nav_80,
        required_liquid_nav_90pct_confidence=req_nav_90,
        required_liquid_nav_95pct_confidence=req_nav_95,
        median_final_nav=median_final_nav,
        p5_final_nav=p5_final_nav,
        p95_final_nav=p95_final_nav,
        manifest=manifest,
    )


def _generate_single_path(
    generator: RandomPathGenerator,
    path_id: int,
    seed: int | None,
    initial_nav: float,
    initial_liquid_nav: float,
    annual_spend: float,
    base_pe_commitments: dict[str, float],
    breach_threshold: float,
) -> MonteCarloPathResult:
    """Generate one stochastic path.

    Returns MonteCarloPathResult with quarterly NAV, spending, coverage.
    """
    config = generator.config
    horizon = config.horizon_quarters

    # Initialize time series
    nav_by_quarter = np.zeros(horizon, dtype=float)
    liquid_nav_by_quarter = np.zeros(horizon, dtype=float)
    spending_by_quarter = np.zeros(horizon, dtype=float)
    coverage_by_quarter = np.zeros(horizon, dtype=float)

    nav_by_quarter[0] = initial_nav
    liquid_nav_by_quarter[0] = initial_liquid_nav

    # Generate primary spending path (from "base" spending scenario)
    base_scenario_key = list(config.spending_scenarios.keys())[0]
    spending_by_quarter = generator.generate_spending_path(base_scenario_key, annual_spend, path_id)

    # Generate return path from first return scenario
    base_return_key = list(config.return_scenarios.keys())[0]
    returns = generator.generate_return_path(base_return_key, path_id)

    # Total PE capital calls per quarter (summed across sleeves). Hoisted out
    # of the quarter loop — generate_call_path is deterministic per path, so
    # regenerating it each quarter only wasted work.
    total_calls_by_quarter = np.zeros(horizon, dtype=float)
    for pe_sleeve, commitment in base_pe_commitments.items():
        if pe_sleeve in config.call_scenarios:
            calls = generator.generate_call_path(pe_sleeve, commitment, path_id)
            n = min(horizon, len(calls))
            total_calls_by_quarter[:n] += calls[:n]

    # Simulate quarters
    current_nav = initial_nav
    current_liquid = initial_liquid_nav

    for q in range(horizon):
        # Apply return
        current_nav = current_nav * (1.0 + returns[q])
        current_liquid = current_liquid * (1.0 + returns[q])

        # Deduct spending
        quarterly_spend = spending_by_quarter[q]
        current_liquid = max(0.0, current_liquid - quarterly_spend)
        current_nav = max(0.0, current_nav - quarterly_spend)

        # Deduct PE calls (if any) — reduce liquid NAV
        quarterly_call = total_calls_by_quarter[q]
        current_liquid = max(0.0, current_liquid - quarterly_call)
        current_nav = max(0.0, current_nav - quarterly_call)

        nav_by_quarter[q] = current_nav
        liquid_nav_by_quarter[q] = current_liquid

        # Coverage: liquid NAV / monthly spend
        monthly_spend = spending_by_quarter[q] / 4.0 if q < len(spending_by_quarter) else 0.0
        if monthly_spend > 0:
            coverage_by_quarter[q] = current_liquid / monthly_spend
        else:
            coverage_by_quarter[q] = float("inf")

    # Closed-form reserve this path would have needed to avoid any breach.
    required_liquid = _required_initial_liquid_nav(
        returns, spending_by_quarter, total_calls_by_quarter, breach_threshold
    )

    # Identify breaches
    breached_quarters = [q for q in range(horizon) if coverage_by_quarter[q] < breach_threshold]
    earliest_breach = breached_quarters[0] if breached_quarters else None

    # Terminal metrics
    final_nav = nav_by_quarter[-1]
    final_liquid = liquid_nav_by_quarter[-1]
    cumulative_return = (final_nav / initial_nav - 1.0) if initial_nav > 0 else 0.0

    # Drawdown
    max_dd, dd_quarters = _compute_max_drawdown(nav_by_quarter)

    # Build index for Series
    quarter_index = pd.RangeIndex(start=0, stop=horizon)

    return MonteCarloPathResult(
        path_id=path_id,
        seed=seed if seed is not None else 0,
        nav_by_quarter=pd.Series(nav_by_quarter, index=quarter_index, name="nav"),
        liquid_nav_by_quarter=pd.Series(liquid_nav_by_quarter, index=quarter_index, name="liquid_nav"),
        spending_by_quarter=pd.Series(spending_by_quarter, index=quarter_index, name="spending"),
        coverage_months_by_quarter=pd.Series(coverage_by_quarter, index=quarter_index, name="coverage_months"),
        breached_quarters=breached_quarters,
        earliest_breach_quarter=earliest_breach,
        final_nav_usd=final_nav,
        final_liquid_nav_usd=final_liquid,
        cumulative_return_pct=cumulative_return,
        max_drawdown_pct=max_dd,
        drawdown_quarters=dd_quarters,
        required_initial_liquid_nav=required_liquid,
    )


def _compute_max_drawdown(nav_series: np.ndarray) -> tuple[float, int]:
    """Compute maximum peak-to-trough drawdown and duration."""
    if len(nav_series) == 0:
        return 0.0, 0

    cummax = np.maximum.accumulate(nav_series)
    drawdown = nav_series / cummax - 1.0
    max_dd = np.min(drawdown)

    if max_dd >= 0.0:
        return 0.0, 0

    trough_idx = np.argmin(drawdown)
    peak_idx = np.argmax(cummax[:trough_idx + 1])
    duration = trough_idx - peak_idx

    return float(max_dd), int(duration)


def _required_initial_liquid_nav(
    returns: np.ndarray,
    spending_by_quarter: np.ndarray,
    calls_by_quarter: np.ndarray,
    breach_threshold: float,
) -> float:
    """Closed-form minimum initial liquid NAV that avoids any coverage breach.

    Before the non-negativity floor (which only binds once a path is already
    breaching), liquid NAV evolves as
    ``liq[q] = liq[q-1]*(1+r[q]) - spend[q] - call[q]`` with ``liq[-1] = L``,
    which unrolls to ``liq[q] = L*G[q] - D[q]`` where ``G[q] = prod_{k<=q}(1+r[k])``
    and ``D[q] = D[q-1]*(1+r[q]) + spend[q] + call[q]``.

    Coverage is ``liq[q] / (spend[q]/4)``; a breach is coverage < threshold,
    i.e. ``L*G[q] - D[q] < threshold * spend[q]/4``. Solving each quarter for
    the smallest ``L`` that clears the bar and taking the max over quarters
    gives the reserve. Quarters with zero spend impose no constraint (coverage
    is infinite). Returns ``inf`` when a binding quarter has a non-positive
    gross factor ``G[q]`` — the portfolio is wiped out and no finite reserve
    suffices.

    The floor is ignored deliberately: at ``L`` >= the returned reserve the
    liquid balance stays at or above the (positive) coverage bar in every
    binding quarter, so flooring never triggers. This makes the estimate at
    worst marginally conservative, which is the safe direction for a reserve.
    """
    horizon = len(returns)
    gross_factor = 1.0
    outflow_compounded = 0.0
    required = 0.0
    for q in range(horizon):
        gross_factor *= 1.0 + returns[q]
        outflow_compounded = (
            outflow_compounded * (1.0 + returns[q])
            + spending_by_quarter[q]
            + calls_by_quarter[q]
        )
        spend = spending_by_quarter[q]
        if spend <= 0.0:
            continue  # coverage infinite; no constraint this quarter
        target_liquid = breach_threshold * spend / 4.0
        if gross_factor <= 0.0:
            return float("inf")
        required = max(required, (outflow_compounded + target_liquid) / gross_factor)
    return required


def _aggregate_required_reserves(
    paths: list[MonteCarloPathResult],
    confidence_levels: list[float],
) -> tuple[float, float, float]:
    """Reserve per confidence level = empirical quantile of per-path reserves.

    ``required_liquid_nav_<C>pct_confidence`` is the smallest initial liquid
    NAV that covers a fraction ``C`` of paths without breach — i.e. the
    C-quantile of each path's ``required_initial_liquid_nav``. Uses the
    ``higher`` order statistic so the reported reserve genuinely achieves at
    least ``C`` coverage rather than interpolating below it.
    """
    reqs = np.array([p.required_initial_liquid_nav for p in paths], dtype=float)

    def quantile(conf_level: float) -> float:
        return float(np.percentile(reqs, conf_level * 100.0, method="higher"))

    return (
        quantile(0.80) if 0.80 in confidence_levels else 0.0,
        quantile(0.90) if 0.90 in confidence_levels else 0.0,
        quantile(0.95) if 0.95 in confidence_levels else 0.0,
    )


def _compute_fixture_hash(config: MonteCarloConfig) -> str:
    """SHA256 of all synthetic fixture inputs (scenarios)."""
    parts = []

    for key in sorted(config.return_scenarios.keys()):
        s = config.return_scenarios[key]
        parts.append(f"ret|{key}|{s.mean_annual_return}|{s.annual_vol}|{s.shock_percentile}")

    for key in sorted(config.spending_scenarios.keys()):
        s = config.spending_scenarios[key]
        parts.append(f"spend|{key}|{s.mean_annual_growth}|{s.annual_vol}|{s.shock_multiplier}")

    for key in sorted(config.call_scenarios.keys()):
        s = config.call_scenarios[key]
        parts.append(
            f"call|{key}|{s.hazard_rate_median_years}|"
            f"{s.early_call_probability}|{tuple(s.base_called_pct_by_quarter)}"
        )

    canonical = "|".join(parts)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _build_fixture_summary(config: MonteCarloConfig) -> str:
    """Human-readable summary of synthetic assumptions."""
    lines = []

    lines.append(f"Paths: {config.num_paths}, Horizon: {config.horizon_quarters} quarters")
    lines.append(f"Return scenarios: {len(config.return_scenarios)}")
    for key, s in config.return_scenarios.items():
        lines.append(f"  {key}: {s.mean_annual_return:.1%} ± {s.annual_vol:.1%}")

    lines.append(f"Spending scenarios: {len(config.spending_scenarios)}")
    for key, s in config.spending_scenarios.items():
        lines.append(f"  {key}: {s.mean_annual_growth:.1%} ± {s.annual_vol:.1%}")

    lines.append(f"Call scenarios: {len(config.call_scenarios)}")
    for key, s in config.call_scenarios.items():
        lines.append(f"  {key}: median {s.hazard_rate_median_years:.1f}y, early_call_prob={s.early_call_probability:.1%}")

    return "\n".join(lines)
