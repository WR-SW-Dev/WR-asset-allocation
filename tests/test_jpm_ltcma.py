"""Tests for the JPM LTCMA CMA source adapter (synthetic data only)."""

from __future__ import annotations

import textwrap

import pytest
import yaml
from aa_model.assumptions.jpm_ltcma import (
    build_cma_dict,
    compound_returns,
    load_jpm_source,
)
from aa_model.io.schemas import CMAConfig

# Small synthetic JPM capture: 3 buckets, symmetric 3x3 correlations.
_SYNTH = textwrap.dedent(
    """
    provider: Synthetic AM
    edition: "2026"
    as_of: "2025-09-30"
    currency: USD
    buckets:
      equity:
        jpm_class: "Test Equity"
        expected_return_arithmetic: 0.0800
        expected_return_compound: 0.0670
        vol_annual: 0.1600
      fixed_income:
        jpm_class: "Test Bonds"
        expected_return_arithmetic: 0.0490
        expected_return_compound: 0.0460
        vol_annual: 0.0480
      real_estate:
        jpm_class: "Test Real Estate"
        expected_return_arithmetic: 0.0880
        expected_return_compound: 0.0810
        vol_annual: 0.1140
    correlations:
      order: [equity, fixed_income, real_estate]
      matrix:
        - [1.00, 0.30, 0.35]
        - [0.30, 1.00, -0.15]
        - [0.35, -0.15, 1.00]
    """
)


@pytest.fixture
def source_path(tmp_path):
    p = tmp_path / "jpm_ltcma_synth.yaml"
    p.write_text(_SYNTH, encoding="utf-8")
    return p


def test_load_parses_buckets_and_matrix(source_path):
    src = load_jpm_source(source_path)
    assert src.provider == "Synthetic AM"
    assert set(src.buckets) == {"equity", "fixed_income", "real_estate"}
    assert src.buckets["equity"].expected_return_arithmetic == 0.08
    assert src.correlation("equity", "real_estate") == 0.35
    # symmetric lookup
    assert src.correlation("real_estate", "equity") == 0.35


def test_load_rejects_order_bucket_mismatch(tmp_path):
    bad = yaml.safe_load(_SYNTH)
    bad["correlations"]["order"] = ["equity", "fixed_income"]  # drop one
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="order does not match buckets"):
        load_jpm_source(p)


def test_load_rejects_non_square_matrix(tmp_path):
    bad = yaml.safe_load(_SYNTH)
    bad["correlations"]["matrix"][0] = [1.0, 0.3]  # wrong width
    p = tmp_path / "bad.yaml"
    p.write_text(yaml.safe_dump(bad), encoding="utf-8")
    with pytest.raises(ValueError, match="not 3x3"):
        load_jpm_source(p)


def test_build_arithmetic_is_active_basis(source_path):
    cma = build_cma_dict(load_jpm_source(source_path), return_basis="arithmetic")
    assert cma["expected_returns_annual"]["equity"] == 0.08
    assert cma["vol_annual"]["equity"] == 0.16


def test_build_compound_basis(source_path):
    cma = build_cma_dict(load_jpm_source(source_path), return_basis="compound")
    assert cma["expected_returns_annual"]["equity"] == 0.067
    assert cma["expected_returns_annual"]["real_estate"] == 0.081


def test_alias_borrows_values_and_is_perfectly_correlated(source_path):
    src = load_jpm_source(source_path)
    cma = build_cma_dict(src, aliases={"re_opco_stabilized": "real_estate"})
    # derived bucket borrows real_estate's return/vol
    assert cma["expected_returns_annual"]["re_opco_stabilized"] == 0.088
    assert cma["vol_annual"]["re_opco_stabilized"] == 0.114
    # proxy is perfectly correlated with its base and itself
    assert cma["correlations"]["re_opco_stabilized"]["real_estate"] == 1.0
    assert cma["correlations"]["re_opco_stabilized"]["re_opco_stabilized"] == 1.0
    # and inherits real_estate's correlation with everything else
    assert (
        cma["correlations"]["re_opco_stabilized"]["equity"]
        == cma["correlations"]["real_estate"]["equity"]
    )


def test_alias_rejects_unknown_target(source_path):
    with pytest.raises(ValueError, match="not a source bucket"):
        build_cma_dict(load_jpm_source(source_path), aliases={"x": "nonexistent"})


def test_alias_rejects_collision(source_path):
    with pytest.raises(ValueError, match="collides"):
        build_cma_dict(load_jpm_source(source_path), aliases={"equity": "real_estate"})


def test_liquidity_coverage_enforced(source_path):
    with pytest.raises(ValueError, match="liquidity map missing"):
        build_cma_dict(load_jpm_source(source_path), liquidity={"equity": "liquid"})


def test_output_validates_as_cma_config(source_path):
    cma = build_cma_dict(
        load_jpm_source(source_path),
        aliases={"re_opco_stabilized": "real_estate"},
        liquidity={
            "equity": "liquid",
            "fixed_income": "liquid",
            "real_estate": "illiquid",
            "re_opco_stabilized": "illiquid",
        },
    )
    cfg = CMAConfig.model_validate(cma)
    assert set(cfg.expected_returns_annual) == {
        "equity",
        "fixed_income",
        "real_estate",
        "re_opco_stabilized",
    }


def test_correlations_symmetric_with_unit_diagonal(source_path):
    cma = build_cma_dict(
        load_jpm_source(source_path), aliases={"re_opco_stabilized": "real_estate"}
    )
    corr = cma["correlations"]
    for a in corr:
        assert corr[a][a] == 1.0
        for b in corr:
            assert corr[a][b] == corr[b][a]


def test_compound_companion_series(source_path):
    comp = compound_returns(
        load_jpm_source(source_path), aliases={"re_opco_stabilized": "real_estate"}
    )
    assert comp["equity"] == 0.067
    assert comp["re_opco_stabilized"] == 0.081  # borrowed from real_estate
