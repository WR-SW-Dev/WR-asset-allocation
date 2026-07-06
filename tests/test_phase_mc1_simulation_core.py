"""Phase MC-1 — Monte Carlo simulation core tests.

6 acceptance tests:
1. Seed stability: same seed → identical paths
2. Seed difference: different seed → different paths
3. Schema validation: invalid config rejected
4. Path count: num_paths honored
5. Zero volatility: collapses to deterministic baseline
6. No global randomness: seeded per-instance, reproducible
"""

from __future__ import annotations

import pytest
from aa_model.monte_carlo import (
    CallTimingScenario,
    MonteCarloConfig,
    ReturnScenario,
    SpendingScenario,
    compute_monte_carlo,
)

# ---- fixtures ---------------------------------------------------------------


@pytest.fixture
def synthetic_config() -> MonteCarloConfig:
    """Minimal synthetic config for testing."""
    return MonteCarloConfig(
        num_paths=100,
        horizon_quarters=8,
        random_seed=12345,
        return_scenarios={
            "public_equity": ReturnScenario(
                asset_class="public_equity",
                mean_annual_return=0.07,
                annual_vol=0.15,
                shock_percentile=0.05,
            ),
        },
        spending_scenarios={
            "base": SpendingScenario(
                driver="base",
                mean_annual_growth=0.03,
                annual_vol=0.01,
                shock_multiplier=None,
            ),
        },
        call_scenarios={
            "pe_buyout": CallTimingScenario(
                pe_sleeve="pe_buyout",
                base_called_pct_by_quarter=[0.2, 0.4, 0.6, 0.8, 1.0, 1.0, 1.0, 1.0],
                hazard_rate_median_years=2.5,
                early_call_probability=0.1,
            ),
        },
    )


# ---- Test 1: Seed stability -----------------------------------------------


def test_same_seed_produces_identical_paths(synthetic_config: MonteCarloConfig) -> None:
    """T1: Same seed + same config → identical paths byte-for-byte."""
    result1 = compute_monte_carlo(
        synthetic_config,
        initial_nav=1_000_000,
        initial_liquid_nav=200_000,
        annual_spend=50_000,
    )

    result2 = compute_monte_carlo(
        synthetic_config,
        initial_nav=1_000_000,
        initial_liquid_nav=200_000,
        annual_spend=50_000,
    )

    assert result1.num_paths == result2.num_paths
    assert result1.seed == result2.seed
    assert result1.config_hash == result2.config_hash

    # Compare aggregate metrics (should be identical)
    assert result1.probability_of_breach == result2.probability_of_breach
    assert result1.median_coverage_months == result2.median_coverage_months
    assert result1.p5_coverage_months == result2.p5_coverage_months

    # Compare individual paths
    for p1, p2 in zip(result1.paths, result2.paths, strict=False):
        assert p1.path_id == p2.path_id
        assert p1.final_nav_usd == p2.final_nav_usd
        assert p1.cumulative_return_pct == p2.cumulative_return_pct


# ---- Test 2: Different seed → different paths ----------------------------


def test_different_seed_produces_different_paths(synthetic_config: MonteCarloConfig) -> None:
    """T2: Different seed → different stochastic paths."""
    config_seed1 = MonteCarloConfig(
        num_paths=50,
        horizon_quarters=8,
        random_seed=111,
        return_scenarios=synthetic_config.return_scenarios,
        spending_scenarios=synthetic_config.spending_scenarios,
        call_scenarios=synthetic_config.call_scenarios,
    )

    config_seed2 = MonteCarloConfig(
        num_paths=50,
        horizon_quarters=8,
        random_seed=222,
        return_scenarios=synthetic_config.return_scenarios,
        spending_scenarios=synthetic_config.spending_scenarios,
        call_scenarios=synthetic_config.call_scenarios,
    )

    result1 = compute_monte_carlo(
        config_seed1,
        initial_nav=1_000_000,
        initial_liquid_nav=200_000,
        annual_spend=50_000,
    )

    result2 = compute_monte_carlo(
        config_seed2,
        initial_nav=1_000_000,
        initial_liquid_nav=200_000,
        annual_spend=50_000,
    )

    # Different seeds → different final NAVs (with high probability)
    final_navs_1 = [p.final_nav_usd for p in result1.paths]
    final_navs_2 = [p.final_nav_usd for p in result2.paths]

    assert final_navs_1 != final_navs_2


# ---- Test 3: Schema validation ------------------------------------------


def test_config_rejects_invalid_num_paths() -> None:
    """T3a: num_paths < 10 rejected."""
    with pytest.raises(ValueError, match="num_paths must be in"):
        MonteCarloConfig(
            num_paths=5,  # Too small
            horizon_quarters=8,
            random_seed=123,
            return_scenarios={
                "eq": ReturnScenario("eq", 0.07, 0.15, None),
            },
            spending_scenarios={
                "base": SpendingScenario("base", 0.03, 0.01, None),
            },
            call_scenarios={
                "pe": CallTimingScenario("pe", [0.5, 0.75, 1.0] + [1.0] * 5, 2.5, 0.1),
            },
        )


def test_config_rejects_invalid_horizon() -> None:
    """T3b: horizon_quarters > 40 rejected."""
    with pytest.raises(ValueError, match="horizon_quarters must be in"):
        MonteCarloConfig(
            num_paths=100,
            horizon_quarters=50,  # Too large
            random_seed=123,
            return_scenarios={
                "eq": ReturnScenario("eq", 0.07, 0.15, None),
            },
            spending_scenarios={
                "base": SpendingScenario("base", 0.03, 0.01, None),
            },
            call_scenarios={
                "pe": CallTimingScenario("pe", [0.5, 0.75, 1.0] + [1.0] * 7, 2.5, 0.1),
            },
        )


def test_return_scenario_rejects_negative_vol() -> None:
    """T3c: negative annual_vol rejected."""
    with pytest.raises(ValueError, match="annual_vol must be"):
        ReturnScenario("eq", 0.07, -0.05, None)  # Negative vol


def test_spending_scenario_rejects_invalid_shock() -> None:
    """T3d: shock_multiplier <= 0 rejected."""
    with pytest.raises(ValueError, match="shock_multiplier must be"):
        SpendingScenario("stress", 0.03, 0.01, shock_multiplier=0.0)


def test_call_scenario_rejects_non_monotonic() -> None:
    """T3e: non-monotonic base_called_pct rejected."""
    with pytest.raises(ValueError, match="monotonically"):
        CallTimingScenario(
            "pe",
            [0.2, 0.8, 0.5, 1.0],  # Not monotonic: 0.8 → 0.5
            2.5,
            0.1,
        )


# ---- Test 4: Path count -----------------------------------------------


def test_num_paths_honored(synthetic_config: MonteCarloConfig) -> None:
    """T4: Result contains exactly num_paths paths."""
    for test_num in [100, 250, 500]:
        config = MonteCarloConfig(
            num_paths=test_num,
            horizon_quarters=8,
            random_seed=999,
            return_scenarios=synthetic_config.return_scenarios,
            spending_scenarios=synthetic_config.spending_scenarios,
            call_scenarios=synthetic_config.call_scenarios,
        )

        result = compute_monte_carlo(
            config,
            initial_nav=1_000_000,
            initial_liquid_nav=200_000,
            annual_spend=50_000,
        )

        assert len(result.paths) == test_num
        assert result.num_paths == test_num


# ---- Test 5: Zero volatility collapses to deterministic ----------------


def test_zero_volatility_matches_deterministic() -> None:
    """T5: With vol=0 and no shocks, Monte Carlo ≈ deterministic baseline."""
    config = MonteCarloConfig(
        num_paths=10,
        horizon_quarters=8,
        random_seed=777,
        return_scenarios={
            "eq": ReturnScenario(
                asset_class="eq",
                mean_annual_return=0.05,
                annual_vol=0.0,  # ZERO volatility
                shock_percentile=None,
            ),
        },
        spending_scenarios={
            "base": SpendingScenario(
                driver="base",
                mean_annual_growth=0.0,  # No growth
                annual_vol=0.0,  # ZERO volatility
                shock_multiplier=None,
            ),
        },
        call_scenarios={
            "pe": CallTimingScenario(
                pe_sleeve="pe",
                base_called_pct_by_quarter=[0, 0, 0, 0, 0, 0, 0, 0],
                hazard_rate_median_years=1.0,
                early_call_probability=0.0,  # No early calls
            ),
        },
    )

    result = compute_monte_carlo(
        config,
        initial_nav=1_000_000,
        initial_liquid_nav=200_000,
        annual_spend=50_000,
    )

    # All paths should have nearly identical final NAV (up to rounding)
    final_navs = [p.final_nav_usd for p in result.paths]
    assert len(set(final_navs)) == 1, "Zero-vol paths should all have same final NAV"


# ---- Test 6: No global randomness, seeded per-instance ----------------


def test_no_side_effects_between_runs(synthetic_config: MonteCarloConfig) -> None:
    """T6: Running Monte Carlo twice with same seed is deterministic.

    (Tests that there's no global random state mutation.)
    """
    initial_nav = 1_500_000
    initial_liquid = 300_000
    annual_spend = 60_000

    # Run 1
    result_a = compute_monte_carlo(
        synthetic_config,
        initial_nav=initial_nav,
        initial_liquid_nav=initial_liquid,
        annual_spend=annual_spend,
    )

    # Do something else (create another config, run another sim)
    other_config = MonteCarloConfig(
        num_paths=50,
        horizon_quarters=12,
        random_seed=999,
        return_scenarios={
            "bond": ReturnScenario("bond", 0.02, 0.05, None),
        },
        spending_scenarios={
            "other": SpendingScenario("other", 0.02, 0.02, None),
        },
        call_scenarios={
            "pe2": CallTimingScenario("pe2", [0.25] * 12, 3.0, 0.05),
        },
    )

    compute_monte_carlo(
        other_config,
        initial_nav=2_000_000,
        initial_liquid_nav=400_000,
        annual_spend=80_000,
    )

    # Run original config again
    result_b = compute_monte_carlo(
        synthetic_config,
        initial_nav=initial_nav,
        initial_liquid_nav=initial_liquid,
        annual_spend=annual_spend,
    )

    # Results should still be identical (no global state side effects)
    assert result_a.probability_of_breach == result_b.probability_of_breach
    assert result_a.median_coverage_months == result_b.median_coverage_months
    assert len(result_a.paths) == len(result_b.paths)


# ---- Additional: Input validation ----------------------------------------


def test_compute_monte_carlo_rejects_zero_initial_nav() -> None:
    """Input validation: initial_nav must be > 0."""
    config = MonteCarloConfig(
        num_paths=100,
        horizon_quarters=8,
        random_seed=123,
        return_scenarios={
            "eq": ReturnScenario("eq", 0.07, 0.15, None),
        },
        spending_scenarios={
            "base": SpendingScenario("base", 0.03, 0.01, None),
        },
        call_scenarios={
            "pe": CallTimingScenario("pe", [0.5, 0.75, 1.0] + [1.0] * 5, 2.5, 0.1),
        },
    )

    with pytest.raises(ValueError, match="initial_nav must be > 0"):
        compute_monte_carlo(
            config,
            initial_nav=0.0,  # Invalid
            initial_liquid_nav=100_000,
            annual_spend=50_000,
        )


def test_compute_monte_carlo_rejects_liquid_greater_than_total() -> None:
    """Input validation: liquid NAV cannot exceed total NAV."""
    config = MonteCarloConfig(
        num_paths=100,
        horizon_quarters=8,
        random_seed=123,
        return_scenarios={
            "eq": ReturnScenario("eq", 0.07, 0.15, None),
        },
        spending_scenarios={
            "base": SpendingScenario("base", 0.03, 0.01, None),
        },
        call_scenarios={
            "pe": CallTimingScenario("pe", [0.5, 0.75, 1.0] + [1.0] * 5, 2.5, 0.1),
        },
    )

    with pytest.raises(ValueError, match="initial_liquid_nav > initial_nav"):
        compute_monte_carlo(
            config,
            initial_nav=500_000,
            initial_liquid_nav=600_000,  # Exceeds total
            annual_spend=50_000,
        )


# ---- Required-reserve solve ------------------------------------------------


def test_required_reserves_monotonic_in_confidence(synthetic_config: MonteCarloConfig) -> None:
    """Higher confidence must never require a smaller reserve."""
    result = compute_monte_carlo(
        synthetic_config,
        initial_nav=1_000_000,
        initial_liquid_nav=200_000,
        annual_spend=50_000,
    )
    assert (
        result.required_liquid_nav_80pct_confidence
        <= result.required_liquid_nav_90pct_confidence
        <= result.required_liquid_nav_95pct_confidence
    )
    # Every path carries a finite, non-negative reserve for this benign config.
    for p in result.paths:
        assert p.required_initial_liquid_nav >= 0.0


def test_required_reserves_deterministic(synthetic_config: MonteCarloConfig) -> None:
    """Same seed + config → identical per-path and aggregate reserves."""
    kw = dict(initial_nav=1_000_000, initial_liquid_nav=200_000, annual_spend=50_000)
    r1 = compute_monte_carlo(synthetic_config, **kw)
    r2 = compute_monte_carlo(synthetic_config, **kw)
    assert r1.required_liquid_nav_90pct_confidence == r2.required_liquid_nav_90pct_confidence
    assert [p.required_initial_liquid_nav for p in r1.paths] == [
        p.required_initial_liquid_nav for p in r2.paths
    ]


def test_required_reserve_matches_closed_form_zero_vol() -> None:
    """Zero-vol, no-return, no-call case has a hand-computable reserve.

    Returns are 0 (gross factor stays 1.0), quarterly spend is a constant
    40_000/4 = 10_000, no PE calls, threshold = 1.0 month. The binding quarter
    is the last: cumulative outflow 8*10_000 plus the 1-month bar 10_000/4,
    all at gross factor 1.0 → 82_500. All paths are identical, so every
    confidence level reports the same reserve.
    """
    config = MonteCarloConfig(
        num_paths=10,
        horizon_quarters=8,
        random_seed=7,
        return_scenarios={"eq": ReturnScenario("eq", 0.0, 0.0, None)},
        spending_scenarios={"base": SpendingScenario("base", 0.0, 0.0, None)},
        call_scenarios={"pe": CallTimingScenario("pe", [0.0] * 8, 2.5, 0.0)},
    )
    result = compute_monte_carlo(
        config,
        initial_nav=1_000_000,
        initial_liquid_nav=500_000,
        annual_spend=40_000,
        # no base_pe_commitments → no PE calls
    )
    for p in result.paths:
        assert p.required_initial_liquid_nav == pytest.approx(82_500.0)
    assert result.required_liquid_nav_80pct_confidence == pytest.approx(82_500.0)
    assert result.required_liquid_nav_95pct_confidence == pytest.approx(82_500.0)

    # Independent check: exactly this reserve avoids breach; a dollar less breaches.
    at_reserve = compute_monte_carlo(
        config, initial_nav=1_000_000, initial_liquid_nav=82_500.0, annual_spend=40_000
    )
    assert at_reserve.probability_of_breach == 0.0
    below = compute_monte_carlo(
        config, initial_nav=1_000_000, initial_liquid_nav=82_499.0, annual_spend=40_000
    )
    assert below.probability_of_breach == 1.0
