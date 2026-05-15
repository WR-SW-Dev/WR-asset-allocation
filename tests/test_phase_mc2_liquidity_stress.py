"""Phase MC-2 — Monte Carlo liquidity stress integration tests.

4 acceptance tests:
1. Deterministic unchanged: existing coverage unaffected by MC-2
2. Opt-in works: Monte Carlo liquidity stress produces per-path metrics
3. Zero volatility: with vol=0, MC collapses to deterministic coverage
4. Breach detection: paths with coverage < threshold correctly identified
"""

from __future__ import annotations

import datetime

import pytest

from aa_model.ingestion.schemas_position import PositionRecord
from aa_model.liquidity.coverage import LiquidityObligationConfig
from aa_model.monte_carlo import (
    CallTimingScenario,
    MonteCarloConfig,
    ReturnScenario,
    SpendingScenario,
    compute_monte_carlo,
)
from aa_model.monte_carlo.liquidity_stress import apply_monte_carlo_stress_to_positions


# ---- fixtures ---------------------------------------------------------------


@pytest.fixture
def synthetic_positions() -> list[PositionRecord]:
    """Minimal synthetic position set for testing."""
    return [
        PositionRecord(
            position_id="liquid_1",
            account_id="acct_test",
            manager_id=None,
            market_value_usd=200_000.0,
            unfunded_commitment_usd=None,
            liquidity_bucket="cash_equivalent",
            valuation_date=datetime.date(2026, 3, 31),
            source_row=1,
        ),
        PositionRecord(
            position_id="illiquid_1",
            account_id="acct_test",
            manager_id=None,
            market_value_usd=800_000.0,
            unfunded_commitment_usd=None,
            liquidity_bucket="illiquid",
            valuation_date=datetime.date(2026, 3, 31),
            source_row=2,
        ),
    ]


@pytest.fixture
def synthetic_obligations() -> LiquidityObligationConfig:
    """Base obligations for testing."""
    return LiquidityObligationConfig(
        annual_spend_usd=50_000.0,
        next_12m_capital_calls_usd=None,
        next_12m_tax_obligations_usd=None,
        next_12m_entity_obligations_usd=None,
    )


@pytest.fixture
def synthetic_mc_config() -> MonteCarloConfig:
    """Monte Carlo config for stress testing."""
    return MonteCarloConfig(
        num_paths=50,
        horizon_quarters=8,
        random_seed=55555,
        return_scenarios={
            "eq": ReturnScenario("eq", 0.07, 0.15, 0.05),
        },
        spending_scenarios={
            "base": SpendingScenario("base", 0.03, 0.01, None),
        },
        call_scenarios={
            "pe": CallTimingScenario("pe", [0.25] * 8, 2.5, 0.1),
        },
    )


# ---- Test 1: Deterministic unchanged ----------------------------------------


def test_existing_liquidity_coverage_unchanged(
    synthetic_positions: list[PositionRecord],
    synthetic_obligations: LiquidityObligationConfig,
) -> None:
    """T1: MC-2 does not affect existing deterministic liquidity coverage."""
    from aa_model.liquidity.coverage import compute_liquidity_coverage

    # Compute coverage normally (no Monte Carlo)
    result = compute_liquidity_coverage(
        synthetic_positions,
        synthetic_obligations,
    )

    # Should have normal metrics
    assert result.liquid_nav == 200_000.0
    assert result.illiquid_nav == 800_000.0
    assert result.total_position_nav == 1_000_000.0
    assert result.liquid_to_annual_spend == pytest.approx(200_000.0 / 50_000.0)

    # Run again to ensure deterministic
    result2 = compute_liquidity_coverage(
        synthetic_positions,
        synthetic_obligations,
    )

    assert result.liquid_nav == result2.liquid_nav
    assert result.liquid_to_annual_spend == result2.liquid_to_annual_spend


# ---- Test 2: Opt-in works ---------------------------------------------------


def test_monte_carlo_stress_opt_in(
    synthetic_positions: list[PositionRecord],
    synthetic_obligations: LiquidityObligationConfig,
    synthetic_mc_config: MonteCarloConfig,
) -> None:
    """T2: Monte Carlo liquidity stress is opt-in and produces per-path metrics."""
    # Generate Monte Carlo result
    mc_result = compute_monte_carlo(
        synthetic_mc_config,
        initial_nav=1_000_000.0,
        initial_liquid_nav=200_000.0,
        annual_spend=50_000.0,
    )

    assert len(mc_result.paths) == 50

    # Apply stress to positions
    stress_by_path = apply_monte_carlo_stress_to_positions(
        mc_result,
        synthetic_positions,
        synthetic_obligations,
    )

    # Should have results for all 50 paths
    assert len(stress_by_path) == 50

    # Each path should have metrics
    for path_id, stress in stress_by_path.items():
        assert stress.path_id == path_id
        assert len(stress.liquid_nav_by_quarter) == 8  # 8 quarters
        assert len(stress.coverage_months_by_quarter) == 8
        assert stress.earliest_breach_quarter is None or isinstance(stress.earliest_breach_quarter, int)
        assert 0.0 <= stress.probability_of_breach_this_path <= 1.0


# ---- Test 3: Zero volatility collapses to deterministic -------------------


def test_zero_vol_monte_carlo_matches_deterministic(
    synthetic_positions: list[PositionRecord],
    synthetic_obligations: LiquidityObligationConfig,
) -> None:
    """T3: With vol=0, Monte Carlo liquidity stress matches deterministic coverage."""
    from aa_model.liquidity.coverage import compute_liquidity_coverage

    # Deterministic coverage
    det_result = compute_liquidity_coverage(
        synthetic_positions,
        synthetic_obligations,
    )

    # Monte Carlo with zero volatility
    config_zero_vol = MonteCarloConfig(
        num_paths=20,
        horizon_quarters=8,
        random_seed=777,
        return_scenarios={
            "eq": ReturnScenario("eq", 0.05, 0.0, None),  # Zero vol
        },
        spending_scenarios={
            "base": SpendingScenario("base", 0.0, 0.0, None),  # Zero growth, zero vol
        },
        call_scenarios={
            "pe": CallTimingScenario("pe", [0.0] * 8, 1.0, 0.0),  # No calls
        },
    )

    mc_result = compute_monte_carlo(
        config_zero_vol,
        initial_nav=1_000_000.0,
        initial_liquid_nav=200_000.0,
        annual_spend=50_000.0,
    )

    stress_by_path = apply_monte_carlo_stress_to_positions(
        mc_result,
        synthetic_positions,
        synthetic_obligations,
    )

    # All paths should have the same coverage (deterministic)
    coverages = [stress.coverage_months_by_quarter.get(0, 0.0) for stress in stress_by_path.values()]
    assert len(set(coverages)) == 1, "Zero-vol paths should all have same Q0 coverage"

    # Coverage should match deterministic (approximately, within 10%)
    expected_coverage = det_result.liquid_to_annual_spend
    if expected_coverage is not None:
        actual_coverage = coverages[0]
        assert actual_coverage == pytest.approx(expected_coverage, rel=0.10)


# ---- Test 4: Breach detection -----------------------------------------------


def test_breach_detection_in_paths(
    synthetic_obligations: LiquidityObligationConfig,
) -> None:
    """T4: Paths with low liquid NAV correctly detect breaches."""
    # Create positions with very low liquid NAV (will breach)
    low_liquid_positions = [
        PositionRecord(
            position_id="liquid_tiny",
            account_id="acct_test",
            manager_id=None,
            market_value_usd=10_000.0,  # Very small liquid NAV
            unfunded_commitment_usd=None,
            liquidity_bucket="cash_equivalent",
            valuation_date=datetime.date(2026, 3, 31),
            source_row=1,
        ),
        PositionRecord(
            position_id="illiquid_large",
            account_id="acct_test",
            manager_id=None,
            market_value_usd=990_000.0,
            unfunded_commitment_usd=None,
            liquidity_bucket="illiquid",
            valuation_date=datetime.date(2026, 3, 31),
            source_row=2,
        ),
    ]

    obligations = LiquidityObligationConfig(
        annual_spend_usd=100_000.0,  # High spend relative to liquid NAV
        next_12m_capital_calls_usd=None,
        next_12m_tax_obligations_usd=None,
        next_12m_entity_obligations_usd=None,
    )

    config = MonteCarloConfig(
        num_paths=30,
        horizon_quarters=8,
        random_seed=888,
        return_scenarios={
            "eq": ReturnScenario("eq", 0.0, 0.0, None),  # No return growth
        },
        spending_scenarios={
            "base": SpendingScenario("base", 0.0, 0.0, None),  # Stable spend
        },
        call_scenarios={
            "pe": CallTimingScenario("pe", [0.0] * 8, 1.0, 0.0),
        },
    )

    mc_result = compute_monte_carlo(
        config,
        initial_nav=1_000_000.0,
        initial_liquid_nav=10_000.0,
        annual_spend=100_000.0,
    )

    stress_by_path = apply_monte_carlo_stress_to_positions(
        mc_result,
        low_liquid_positions,
        obligations,
    )

    # Most paths should breach (coverage ratio = 10k / 100k ≈ 0.1 << 1.0)
    breached_count = sum(1 for stress in stress_by_path.values() if stress.breached_quarters)
    assert breached_count > 0, "Expected at least some paths to breach"
    assert stress_by_path[0].probability_of_breach_this_path == 1.0, "Path 0 should breach"


# ---- Additional: Integration with zero-volatility path -----


def test_zero_volatility_path_no_breaches(
    synthetic_positions: list[PositionRecord],
    synthetic_obligations: LiquidityObligationConfig,
) -> None:
    """Integration: Zero-volatility scenario with healthy coverage should not breach."""
    config = MonteCarloConfig(
        num_paths=10,
        horizon_quarters=8,
        random_seed=999,
        return_scenarios={
            "eq": ReturnScenario("eq", 0.05, 0.0, None),
        },
        spending_scenarios={
            "base": SpendingScenario("base", 0.0, 0.0, None),
        },
        call_scenarios={
            "pe": CallTimingScenario("pe", [0.0] * 8, 1.0, 0.0),
        },
    )

    mc_result = compute_monte_carlo(
        config,
        initial_nav=1_000_000.0,
        initial_liquid_nav=200_000.0,  # Healthy relative to 50k annual spend
        annual_spend=50_000.0,
    )

    stress_by_path = apply_monte_carlo_stress_to_positions(
        mc_result,
        synthetic_positions,
        synthetic_obligations,
    )

    # All paths should be breach-free (200k liquid / 50k annual = 4x coverage)
    for stress in stress_by_path.values():
        assert len(stress.breached_quarters) == 0, f"Path {stress.path_id} should not breach"
        assert stress.probability_of_breach_this_path == 0.0
