"""Validate the JPM 6-bucket study profile (configs/base_jpm.yaml).

Uses a SYNTHETIC 6-bucket CMA rather than the real (gitignored) configs/cma_jpm.yaml,
so the profile's tracked configs are exercised without depending on JPM material.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pytest
from aa_model.allocation.constraints import Constraints
from aa_model.allocation.factory import make_allocator
from aa_model.allocation.riskfolio_adapter import RiskfolioAdapter
from aa_model.assumptions.cma import CMA
from aa_model.io.loaders import (
    load_base_config,
    load_fixture_scenario,
    load_pe_pacing_config,
    load_public_allocation_config,
    load_scenarios_config,
    load_spending_config,
    resolve_repo_root,
)
from aa_model.io.schemas import CMAConfig, PublicAllocationConfig, StudyConfig
from aa_model.io.validation import validate_study_config

_ROOT = resolve_repo_root(Path(__file__).resolve())
_PROFILE_BUCKETS = [
    "equity",
    "fixed_income",
    "real_estate",
    "pe_buyout",
    "absolute_return",
    "cash",
]


def _synthetic_cma() -> CMAConfig:
    """A 6-bucket CMA with the profile's bucket set (no JPM numbers)."""
    er = dict(zip(_PROFILE_BUCKETS, [0.08, 0.049, 0.088, 0.119, 0.055, 0.031], strict=True))
    vol = dict(zip(_PROFILE_BUCKETS, [0.16, 0.048, 0.114, 0.198, 0.058, 0.007], strict=True))
    corr = {a: {b: (1.0 if a == b else 0.2) for b in _PROFILE_BUCKETS} for a in _PROFILE_BUCKETS}
    liq = {
        "equity": "liquid",
        "fixed_income": "liquid",
        "real_estate": "illiquid",
        "pe_buyout": "illiquid",
        "absolute_return": "semi_liquid",
        "cash": "liquid",
    }
    return CMAConfig(expected_returns_annual=er, vol_annual=vol, correlations=corr, liquidity=liq)


def _profile_study_config() -> StudyConfig:
    base = load_base_config(_ROOT / "configs" / "base_jpm.yaml")
    return StudyConfig(
        base=base,
        allocation=load_public_allocation_config(_ROOT / base.allocation.config),
        cma=_synthetic_cma(),
        spending=load_spending_config(_ROOT / base.spending.config),
        pe_pacing=load_pe_pacing_config(_ROOT / base.pe_pacing.config),
        scenarios=load_scenarios_config(_ROOT / base.scenarios.config),
        fixture_scenario=load_fixture_scenario(_ROOT / base.fixtures.scenario),
    )


def test_profile_configs_are_cross_valid():
    cfg = _profile_study_config()
    validate_study_config(cfg)  # raises on any cross-config mismatch
    assert cfg.base.allocation.engine == "riskfolio"
    assert cfg.allocation.objective == "sharpe"
    assert set(cfg.allocation.stub_weights) == set(_PROFILE_BUCKETS)
    assert set(cfg.fixture_scenario.nav_initial) == set(_PROFILE_BUCKETS)


def test_profile_excludes_re_opco_stabilized():
    cfg = _profile_study_config()
    assert "re_opco_stabilized" not in cfg.allocation.stub_weights
    assert "cash_and_cash_alts" not in cfg.allocation.stub_weights
    assert "cash" in cfg.allocation.stub_weights  # renamed for the orchestrator


def test_pe_target_matches_sleeve_weight():
    cfg = _profile_study_config()
    pe_weight = sum(w for b, w in cfg.allocation.stub_weights.items() if b.startswith("pe_"))
    assert abs(pe_weight - cfg.base.pe.sleeve_target_pct) < 1e-9


def test_objective_threads_to_riskfolio_sharpe():
    cfg = _profile_study_config()
    alloc = make_allocator(cfg.allocation, engine="riskfolio")
    assert isinstance(alloc, RiskfolioAdapter)
    assert alloc.diagnostics()["objective"] == "Sharpe"


def test_profile_sets_cash_as_risk_free_bucket():
    cfg = _profile_study_config()
    assert cfg.allocation.risk_free_bucket == "cash"


def test_risk_free_bucket_must_be_a_real_bucket():
    with pytest.raises(ValueError, match="risk_free_bucket"):
        PublicAllocationConfig(
            stub_weights={"equity": 0.6, "cash": 0.4},
            objective="sharpe",
            risk_free_bucket="tbills",  # not in stub_weights
        )


def test_rf_sourced_from_cash_and_cash_not_dominant():
    cfg = _profile_study_config()
    alloc = make_allocator(cfg.allocation, engine="riskfolio")
    cma = CMA.from_config(cfg.cma)
    alloc.fit(returns=pd.DataFrame(), cma=cma, constraints=Constraints())
    w = alloc.weights()
    # rf is read from the cash bucket's CMA expected return
    assert alloc.diagnostics()["rf"] == cfg.cma.expected_returns_annual["cash"]
    # with a T-bill rf, cash no longer dominates the max-Sharpe solution
    assert w["cash"] < 0.5
    assert abs(float(w.sum()) - 1.0) < 1e-6


def test_default_objective_preserved_for_existing_model():
    # The existing 4-bucket allocation config has no `objective` field, so it
    # must default to min_risk -> riskfolio "MinRisk" (behavior unchanged).
    base = load_base_config(_ROOT / "configs" / "base.yaml")
    alloc_cfg = load_public_allocation_config(_ROOT / base.allocation.config)
    assert alloc_cfg.objective == "min_risk"
    alloc = make_allocator(alloc_cfg, engine="riskfolio")
    assert alloc.diagnostics()["objective"] == "MinRisk"
