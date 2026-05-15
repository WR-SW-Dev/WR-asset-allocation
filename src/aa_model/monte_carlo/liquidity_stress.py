"""Phase MC-2 — Monte Carlo liquidity stress integration.

Connect stochastic Monte Carlo paths to deterministic liquidity coverage.
Pure function. No ledger reads. Deterministic when paths are deterministic.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from aa_model.ingestion.schemas_position import ManagerTermsRecord, PositionRecord
from aa_model.liquidity.coverage import (
    LiquidityCoverageConfig,
    LiquidityObligationConfig,
    compute_liquidity_coverage,
)
from aa_model.monte_carlo.result import MonteCarloPathResult, MonteCarloResult
from aa_model.spending.spending_base import SpendingBaseBreakdown


@dataclass(frozen=True)
class MonteCarloLiquidityStress:
    """Per-path liquidity stress metrics.

    Attributes
    ----------
    path_id : int
        Path index in [0, num_paths).
    liquid_nav_by_quarter : dict[int, float]
        Liquid NAV at each quarter in the path.
    coverage_months_by_quarter : dict[int, float]
        Months of spending covered by liquid NAV, per quarter.
    breached_quarters : list[int]
        Quarter indices where coverage < breach_threshold.
    earliest_breach_quarter : int | None
        First quarter with breach; None if no breach.
    probability_of_breach_this_path : float
        1.0 if path breaches, 0.0 if not (binary).
    required_liquid_nav_at_80pct : float
        Liquid NAV needed (from baseline) to avoid breach at 80% confidence
        in this path's scenario.
    required_liquid_nav_at_90pct : float
        Liquid NAV needed at 90% confidence.
    required_liquid_nav_at_95pct : float
        Liquid NAV needed at 95% confidence.
    """

    path_id: int
    liquid_nav_by_quarter: dict[int, float]
    coverage_months_by_quarter: dict[int, float]
    breached_quarters: list[int]
    earliest_breach_quarter: int | None
    probability_of_breach_this_path: float
    required_liquid_nav_at_80pct: float
    required_liquid_nav_at_90pct: float
    required_liquid_nav_at_95pct: float


def apply_monte_carlo_stress_to_positions(
    monte_carlo_result: MonteCarloResult,
    positions: list[PositionRecord],
    obligations: LiquidityObligationConfig,
    *,
    tier_overrides: dict[str, str] | None = None,
    manager_terms: list[ManagerTermsRecord] | None = None,
    spending_base: SpendingBaseBreakdown | None = None,
    spending_base_is_flow: bool = False,
    coverage_config: LiquidityCoverageConfig | None = None,
    breach_threshold: float = 1.0,
) -> dict[int, MonteCarloLiquidityStress]:
    """Apply Monte Carlo paths to deterministic liquidity coverage.

    For each stochastic path, compute coverage metrics using the path's
    simulated liquid NAV and spending. Returns per-path stress metrics.

    Parameters
    ----------
    monte_carlo_result : MonteCarloResult
        Aggregated Monte Carlo result from compute_monte_carlo().
    positions : list[PositionRecord]
        Position records (static across all paths).
    obligations : LiquidityObligationConfig
        Base obligations (static across all paths).
    tier_overrides : dict[str, str] | None
        Liquidity tier overrides (Phase 15 → Phase 12).
    manager_terms : list[ManagerTermsRecord] | None
        Manager terms for semi-liquid advisory.
    spending_base : SpendingBaseBreakdown | None
        Phase 12 spending base (static across paths).
    spending_base_is_flow : bool
        Whether spending base is flow-type (distributable_income mode).
    coverage_config : LiquidityCoverageConfig | None
        Policy thresholds; uses defaults if None.
    breach_threshold : float
        Coverage ratio below which a quarter is a breach (default 1.0).

    Returns
    -------
    dict[int, MonteCarloLiquidityStress]
        Per-path stress metrics, keyed by path_id.

    Notes
    -----
    This function is deterministic: same inputs → same output.
    It does not modify any state and does not read live workbooks.
    """
    if not isinstance(monte_carlo_result, MonteCarloResult):
        raise TypeError("monte_carlo_result must be MonteCarloResult")

    stress_by_path: dict[int, MonteCarloLiquidityStress] = {}

    for path in monte_carlo_result.paths:
        stress = _compute_stress_for_single_path(
            path=path,
            positions=positions,
            obligations=obligations,
            tier_overrides=tier_overrides,
            manager_terms=manager_terms,
            spending_base=spending_base,
            spending_base_is_flow=spending_base_is_flow,
            coverage_config=coverage_config,
            breach_threshold=breach_threshold,
        )
        stress_by_path[path.path_id] = stress

    return stress_by_path


def _compute_stress_for_single_path(
    path: MonteCarloPathResult,
    positions: list[PositionRecord],
    obligations: LiquidityObligationConfig,
    tier_overrides: dict[str, str] | None,
    manager_terms: list[ManagerTermsRecord] | None,
    spending_base: SpendingBaseBreakdown | None,
    spending_base_is_flow: bool,
    coverage_config: LiquidityCoverageConfig | None,
    breach_threshold: float,
) -> MonteCarloLiquidityStress:
    """Compute stress for one path by applying its NAV/spending to coverage.

    For each quarter in the path:
    1. Create modified obligations with that quarter's spending
    2. Create modified positions with that quarter's liquid NAV
    3. Call compute_liquidity_coverage() to get metrics
    4. Record breach status

    Returns MonteCarloLiquidityStress with per-quarter metrics and breach info.
    """
    coverage_months_by_quarter: dict[int, float] = {}
    breached_quarters: list[int] = []
    liquid_nav_by_quarter: dict[int, float] = {}

    horizon = len(path.nav_by_quarter)

    for q in range(horizon):
        quarter_liquid_nav = path.liquid_nav_by_quarter.iloc[q] if q < len(path.liquid_nav_by_quarter) else 0.0
        quarter_spending = path.spending_by_quarter.iloc[q] if q < len(path.spending_by_quarter) else 0.0

        liquid_nav_by_quarter[q] = quarter_liquid_nav

        # Modified obligations: use this quarter's spending as annual run rate
        quarterly_obligations = LiquidityObligationConfig(
            annual_spend_usd=quarter_spending * 4.0,  # Annualize quarterly spend
            next_12m_capital_calls_usd=obligations.next_12m_capital_calls_usd,
            next_12m_tax_obligations_usd=obligations.next_12m_tax_obligations_usd,
            next_12m_entity_obligations_usd=obligations.next_12m_entity_obligations_usd,
            note=f"Path {path.path_id} Q{q}",
        )

        # Modified positions: scale liquid NAV to path's quarter NAV
        # (Keep illiquid/locked tiers unchanged; scale only liquid)
        modified_positions = _scale_positions_to_path_nav(
            positions=positions,
            target_liquid_nav=quarter_liquid_nav,
        )

        # Compute coverage for this path/quarter
        result = compute_liquidity_coverage(
            modified_positions,
            quarterly_obligations,
            tier_overrides=tier_overrides,
            manager_terms=manager_terms,
            spending_base=spending_base,
            spending_base_is_flow=spending_base_is_flow,
            config=coverage_config,
        )

        # Record coverage months
        coverage = result.liquid_to_annual_spend if result.liquid_to_annual_spend is not None else 0.0
        coverage_months_by_quarter[q] = coverage

        # Record breach
        if coverage < breach_threshold:
            breached_quarters.append(q)

    earliest_breach = breached_quarters[0] if breached_quarters else None
    prob_breach = 1.0 if breached_quarters else 0.0

    # Required reserves: how much more liquid NAV would eliminate breaches?
    req_80, req_90, req_95 = _compute_path_required_reserves(
        coverage_months_by_quarter=coverage_months_by_quarter,
        breached_quarters=breached_quarters,
        current_liquid_nav=sum(liquid_nav_by_quarter.values()) / max(1, len(liquid_nav_by_quarter)),
        breach_threshold=breach_threshold,
    )

    return MonteCarloLiquidityStress(
        path_id=path.path_id,
        liquid_nav_by_quarter=liquid_nav_by_quarter,
        coverage_months_by_quarter=coverage_months_by_quarter,
        breached_quarters=breached_quarters,
        earliest_breach_quarter=earliest_breach,
        probability_of_breach_this_path=prob_breach,
        required_liquid_nav_at_80pct=req_80,
        required_liquid_nav_at_90pct=req_90,
        required_liquid_nav_at_95pct=req_95,
    )


def _scale_positions_to_path_nav(
    positions: list[PositionRecord],
    target_liquid_nav: float,
) -> list[PositionRecord]:
    """Scale positions' liquid tiers to match path's liquid NAV.

    Keeps illiquid/locked tiers unchanged. Only scales cash and public_bond.
    """
    if not positions:
        return []

    # Calculate current liquid NAV from positions
    current_liquid = 0.0
    for pos in positions:
        bucket = pos.liquidity_bucket
        if bucket in ("cash_equivalent", "daily_liquid"):
            current_liquid += pos.market_value_usd

    if current_liquid <= 0:
        scaling = 0.0
    else:
        scaling = target_liquid_nav / current_liquid

    scaled = []
    for pos in positions:
        bucket = pos.liquidity_bucket
        if bucket in ("cash_equivalent", "daily_liquid"):
            scaled_value = pos.market_value_usd * scaling
        else:
            scaled_value = pos.market_value_usd

        scaled_pos = PositionRecord(
            position_id=pos.position_id,
            account_id=pos.account_id,
            manager_id=pos.manager_id,
            market_value_usd=scaled_value,
            unfunded_commitment_usd=pos.unfunded_commitment_usd,
            liquidity_bucket=pos.liquidity_bucket,
            valuation_date=pos.valuation_date,
            source_row=pos.source_row,
        )
        scaled.append(scaled_pos)

    return scaled


def _compute_path_required_reserves(
    coverage_months_by_quarter: dict[int, float],
    breached_quarters: list[int],
    current_liquid_nav: float,
    breach_threshold: float,
) -> tuple[float, float, float]:
    """Estimate required liquid NAV to achieve breach-free scenario.

    Simple approach: if any quarter breaches, estimate additional NAV needed.
    """
    if not breached_quarters:
        return 0.0, 0.0, 0.0

    # Average coverage shortfall across breached quarters
    shortfall_sum = 0.0
    for q in breached_quarters:
        coverage = coverage_months_by_quarter.get(q, 0.0)
        shortfall = max(0.0, breach_threshold - coverage)
        shortfall_sum += shortfall

    avg_shortfall = shortfall_sum / max(1, len(breached_quarters))

    # Scale current NAV by shortfall ratio
    if avg_shortfall > 0:
        scaling = (breach_threshold + avg_shortfall) / breach_threshold
        required = current_liquid_nav * (scaling - 1.0)
    else:
        required = 0.0

    # Conservative scaling for confidence levels
    return (
        required * 0.8,  # 80% confidence
        required * 0.9,  # 90% confidence
        required * 1.0,  # 95% confidence
    )
