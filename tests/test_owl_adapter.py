"""Phase 3c — Owl (guardrail spending rule) tests.

The audit framework for this phase is:

1. **Path-dependence correctness.** Output deterministic; depends only on
   prior-year annual spending and config; no NAV-feedback drift; no hidden
   state across runs.
2. **Boundary behavior.** Correct trigger at upper / lower bands; no
   spurious oscillation; off-by-one safety at year boundaries.
3. **Interaction with ledger.** Owl reads ``ledger.initial_nav`` only;
   never mutates; spending rows still emitted as normal external outflows.
4. **Comparability.** Predictable degenerate cases vs flat_real and vs
   smoothing.

The numerical anchor is the hand-worked Guyton-Klinger trip case at q8:
initial $4M annual / $100M NAV / 4% rate / forecast 4%/q / 20% bands /
10% raise → quarterly spending = $1,155,687.50.
"""

from __future__ import annotations

import pandas as pd
import pytest
from aa_model.integration.ledger import QuarterlyLedger
from aa_model.io.schemas import GuardrailConfig, SmoothingConfig, SpendingConfig
from aa_model.spending.base import SpendingParams
from aa_model.spending.owl_adapter import OwlRule
from aa_model.spending.rules import FlatRealRule, SmoothingRule, make_rule


def _ledger(initial_nav_total: float = 100_000_000.0) -> QuarterlyLedger:
    return QuarterlyLedger(
        "test",
        initial_nav={"cash": initial_nav_total},
        start_quarter=pd.Period("2026Q1", freq="Q-DEC"),
    )


def _params(
    *,
    rule: str = "owl",
    annual: float = 4_000_000.0,
    inflation: float = 0.025,
    upper: float = 0.20,
    lower: float = 0.20,
    raise_pct: float = 0.10,
    cut_pct: float = 0.10,
    forecast_q: float = 0.0,
    floor: float = 0.0,
    ceiling: float = 1e12,
    num_quarters: int = 12,
) -> SpendingParams:
    cfg = SpendingConfig(
        rule=rule,
        annual_spend_usd=annual,
        inflation_pct=inflation,
        smoothing=SmoothingConfig(window_quarters=12, weight=0.0),
        floor_usd=floor,
        ceiling_usd=ceiling,
        guardrail=GuardrailConfig(
            upper_band_pct=upper,
            lower_band_pct=lower,
            raise_pct=raise_pct,
            cut_pct=cut_pct,
            forecast_quarterly_return_pct=forecast_q,
        )
        if rule == "owl"
        else None,
    )
    return SpendingParams(
        config=cfg,
        start_quarter=pd.Period("2026Q1", freq="Q-DEC"),
        num_quarters=num_quarters,
    )


# ---- numerical anchor (hand-worked Guyton-Klinger trip) ---------------------


def test_numerical_anchor_q8_raise_trigger():
    """Initial $4M / $100M / 4% rate; forecast 4%/q; 20% bands; 10% raise.
    At q8: forecast NAV = $100M·(1.04)^8 = $136,856,905; annual spend after
    two inflation steps = $4M·(1.025)^2 = $4,202,500; rate = 3.0707% which
    is below 4% · (1 - 0.20) = 3.20% → raise triggers; new annual =
    $4,202,500 · 1.10 = $4,622,750; quarterly = $1,155,687.50.
    """
    p = _params(forecast_q=0.04)
    out = OwlRule().quarterly_outflows(_ledger(), p)
    assert out.iloc[8] == pytest.approx(1_155_687.50, abs=1e-9)


def test_anchor_year_0_constant_at_target_quarter():
    p = _params(forecast_q=0.04)
    out = OwlRule().quarterly_outflows(_ledger(), p)
    # First four quarters are $1M each (no inflation, no guardrail check at t=0).
    for i in range(4):
        assert out.iloc[i] == pytest.approx(1_000_000.0, abs=1e-9)


def test_anchor_year_1_inflation_only_no_trigger():
    p = _params(forecast_q=0.04)
    out = OwlRule().quarterly_outflows(_ledger(), p)
    # Year 1 annual = $4M·1.025 = $4.1M; rate at q4 = $4.1M / $100M·(1.04)^4
    # = $4.1M / $116,985,856 = 3.5048% → still > 3.20%, < 4.80% → no trigger.
    assert out.iloc[4] == pytest.approx(1_025_000.0, abs=1e-9)
    assert out.iloc[7] == pytest.approx(1_025_000.0, abs=1e-9)


def test_anchor_post_trigger_constant_within_year():
    p = _params(forecast_q=0.04)
    out = OwlRule().quarterly_outflows(_ledger(), p)
    # After the q8 raise, q9..q11 must equal q8 (within-year constancy).
    for i in range(8, 12):
        assert out.iloc[i] == pytest.approx(1_155_687.50, abs=1e-9)


# ---- boundary behavior ------------------------------------------------------


def test_cut_trigger_when_forecast_nav_falls():
    """Negative forecast growth → NAV shrinks → rate rises → cut triggers
    when rate exceeds 4% · (1 + 0.20) = 4.80%.
    """
    # forecast -5%/q → NAV at q4 = $100M · (0.95)^4 = $81.45M;
    # annual spend after one year of inflation = $4.1M; rate = 5.034%.
    # 5.034% > 4.80% → cut triggers; new annual = $4.1M · 0.90 = $3.69M;
    # quarterly = $922,500.
    p = _params(forecast_q=-0.05)
    out = OwlRule().quarterly_outflows(_ledger(), p)
    assert out.iloc[4] == pytest.approx(922_500.0, abs=1e-9)


def test_no_trigger_when_forecast_keeps_rate_in_band():
    """Forecast growth that keeps inflation-adjusted rate inside the band:
    no raise / no cut; spending tracks pure inflation step-up — equivalent
    to flat_real's first-year-on inflation increment.
    """
    # forecast 2.5%/q exactly cancels 2.5% annual inflation? Not quite.
    # Set bands wide enough that no trigger fires across 12q.
    p = _params(upper=0.95, lower=0.95, forecast_q=0.0)
    out = OwlRule().quarterly_outflows(_ledger(), p)
    # Should match FlatRealRule output for the same horizon (no triggers).
    flat_p = _params(rule="flat_real")
    flat_out = FlatRealRule().quarterly_outflows(_ledger(), flat_p)
    pd.testing.assert_series_equal(out, flat_out)


def test_within_year_spending_is_constant():
    """Within any calendar year (4 quarters from start), Owl spending is
    constant. Triggers only fire at year boundaries.
    """
    p = _params(forecast_q=0.04)
    out = OwlRule().quarterly_outflows(_ledger(), p)
    for year in range(3):  # 12q / 4 = 3 years
        year_slice = out.iloc[year * 4 : (year + 1) * 4]
        assert year_slice.nunique() == 1, f"spending varied within year {year}"


# ---- path-dependence correctness --------------------------------------------


def test_deterministic_two_runs_match():
    p = _params(forecast_q=0.04)
    a = OwlRule().quarterly_outflows(_ledger(), p)
    b = OwlRule().quarterly_outflows(_ledger(), p)
    pd.testing.assert_series_equal(a, b)


def test_owl_path_is_scale_invariant_in_initial_nav():
    """Owl's spending series is **invariant** to initial-NAV scale:

        current_rate     = annual_spend / [initial_nav · (1+g)^t]
        initial_rate     = annual_spend_0 / initial_nav
        threshold(rate)  = initial_rate · (1 ± band)

    Substituting the threshold cancels initial_nav: the trigger condition
    reduces to ``annual_spend(t) ≷ annual_spend_0 · (1 ± band) · (1+g)^t``.
    Doubling initial NAV therefore produces an identical spending series.
    Documented as L16 — a real-world weakness of this minimum
    implementation: doubling portfolio size does not alter Owl's
    spending decisions.
    """
    p = _params(forecast_q=0.04)
    a = OwlRule().quarterly_outflows(_ledger(100_000_000.0), p)
    b = OwlRule().quarterly_outflows(_ledger(200_000_000.0), p)
    pd.testing.assert_series_equal(a, b)


def test_path_dependence_one_step_back_only():
    """Year-N spending depends only on year-(N-1) spending and the guardrail
    check. Replacing the rule's call-time params with a different start
    quarter must produce the same series shape (12 elements) and identical
    values modulo the index — proving no hidden state carries between calls.
    """
    p_a = _params(forecast_q=0.04)
    out_a = OwlRule().quarterly_outflows(_ledger(), p_a)
    p_b = _params(forecast_q=0.04)
    p_b = SpendingParams(
        config=p_b.config,
        start_quarter=pd.Period("2030Q1", freq="Q-DEC"),
        num_quarters=p_b.num_quarters,
    )
    out_b = OwlRule().quarterly_outflows(_ledger(), p_b)
    assert list(out_a.values) == list(out_b.values)


# ---- structural parity ------------------------------------------------------


def test_output_format_matches_other_rules():
    p = _params()
    out_owl = OwlRule().quarterly_outflows(_ledger(), p)
    out_flat = FlatRealRule().quarterly_outflows(_ledger(), _params(rule="flat_real"))
    assert out_owl.dtype == out_flat.dtype
    assert out_owl.name == out_flat.name
    assert out_owl.index.equals(out_flat.index)
    assert len(out_owl) == 12


def test_no_nan_no_negative_no_inf():
    p = _params(forecast_q=0.04, num_quarters=20)
    out = OwlRule().quarterly_outflows(_ledger(), p)
    assert not out.isna().any()
    assert (out >= 0.0).all()
    import math

    assert all(math.isfinite(v) for v in out.values)


def test_floor_clip_applied():
    """Floor must clamp Owl output the same way it does for flat_real."""
    p = _params(annual=0.0, floor=500.0, num_quarters=4)
    out = OwlRule().quarterly_outflows(_ledger(), p)
    assert (out == 500.0).all()


def test_ceiling_clip_applied():
    p = _params(annual=4_000_000.0, ceiling=900_000.0, num_quarters=4)
    out = OwlRule().quarterly_outflows(_ledger(), p)
    assert (out == 900_000.0).all()


# ---- comparability vs flat_real and smoothing -------------------------------


def test_owl_with_inactive_bands_matches_flat_real():
    """Set bands so wide they never trigger → Owl reduces to flat_real."""
    p_owl = _params(upper=10.0, lower=10.0, forecast_q=0.0, num_quarters=20)
    p_flat = _params(rule="flat_real", num_quarters=20)
    out_owl = OwlRule().quarterly_outflows(_ledger(), p_owl)
    out_flat = FlatRealRule().quarterly_outflows(_ledger(), p_flat)
    pd.testing.assert_series_equal(out_owl, out_flat)


def test_owl_distinct_from_smoothing_w1():
    """w=1 smoothing == flat_real, but Owl with active bands diverges."""
    p_owl = _params(forecast_q=0.04, num_quarters=12)
    out_owl = OwlRule().quarterly_outflows(_ledger(), p_owl)
    p_smooth = _params(rule="smoothing")
    smooth = SmoothingRule().quarterly_outflows(_ledger(), p_smooth)
    assert not out_owl.equals(smooth)


# ---- factory + schema -------------------------------------------------------


def test_make_rule_factory():
    assert isinstance(make_rule("owl"), OwlRule)


def test_owl_without_guardrail_config_raises_at_validation():
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SpendingConfig.model_validate(
            {
                "rule": "owl",
                "annual_spend_usd": 4_000_000.0,
                "inflation_pct": 0.025,
                "smoothing": {"window_quarters": 12, "weight": 0.0},
                "floor_usd": 0.0,
                "ceiling_usd": 1e12,
                # guardrail missing
            }
        )


def test_owl_rule_raises_if_initial_nav_zero():
    p = _params()
    bad_ledger = QuarterlyLedger("x", initial_nav={"cash": 0.0}, start_quarter=p.start_quarter)
    with pytest.raises(ValueError, match="positive initial NAV"):
        OwlRule().quarterly_outflows(bad_ledger, p)
