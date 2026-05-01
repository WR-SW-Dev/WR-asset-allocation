"""Spending rule tests."""

from __future__ import annotations

import pandas as pd
import pytest
from aa_model.integration.ledger import QuarterlyLedger
from aa_model.io.schemas import SmoothingConfig, SpendingConfig
from aa_model.spending.base import SpendingParams
from aa_model.spending.rules import FlatRealRule, SmoothingRule, make_rule


def _params(
    rule: str = "flat_real",
    weight: float = 0.0,
    inflation: float = 0.025,
    annual: float = 4_000_000,
) -> SpendingParams:
    cfg = SpendingConfig(
        rule=rule,
        annual_spend_usd=annual,
        inflation_pct=inflation,
        smoothing=SmoothingConfig(window_quarters=12, weight=weight),
        floor_usd=0.0,
        ceiling_usd=1e12,
    )
    return SpendingParams(
        config=cfg,
        start_quarter=pd.Period("2026Q1", freq="Q-DEC"),
        num_quarters=8,
    )


def _empty_ledger(p: SpendingParams) -> QuarterlyLedger:
    return QuarterlyLedger("test", initial_nav={"cash": 0.0}, start_quarter=p.start_quarter)


def test_flat_real_first_year_constant():
    p = _params()
    out = FlatRealRule().quarterly_outflows(_empty_ledger(p), p)
    assert all(v == 1_000_000.0 for v in out.iloc[:4])


def test_flat_real_inflation_steps_up_at_year_boundary():
    p = _params()
    out = FlatRealRule().quarterly_outflows(_empty_ledger(p), p)
    assert pytest.approx(out.iloc[4]) == 1_025_000.0
    assert pytest.approx(out.iloc[7]) == 1_025_000.0


def test_smoothing_zero_weight_collapses_to_flat_real():
    p = _params(rule="smoothing", weight=0.0)
    L = _empty_ledger(p)
    pd.testing.assert_series_equal(
        FlatRealRule().quarterly_outflows(L, p),
        SmoothingRule().quarterly_outflows(L, p),
    )


def test_smoothing_nonzero_weight_not_implemented():
    p = _params(rule="smoothing", weight=0.5)
    L = _empty_ledger(p)
    with pytest.raises(NotImplementedError):
        SmoothingRule().quarterly_outflows(L, p)


def test_make_rule_factory():
    assert isinstance(make_rule("flat_real"), FlatRealRule)
    assert isinstance(make_rule("smoothing"), SmoothingRule)
    with pytest.raises(ValueError):
        make_rule("unknown")


def test_floor_clip():
    p = _params(annual=0.0)  # zero spend; floor should be 0 by default and not clip
    out = FlatRealRule().quarterly_outflows(_empty_ledger(p), p)
    assert (out == 0.0).all()
