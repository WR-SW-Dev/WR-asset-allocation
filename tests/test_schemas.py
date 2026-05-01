"""Schema-level validation tests."""

from __future__ import annotations

import pytest
from aa_model.io.loaders import load_base_config, load_study_config
from aa_model.io.schemas import (
    PublicAllocationConfig,
    SmoothingConfig,
    SpendingConfig,
    TADefaultsConfig,
)
from aa_model.io.validation import validate_study_config
from pydantic import ValidationError


def test_base_config_loads(base_config_path):
    cfg = load_base_config(base_config_path)
    assert cfg.governance.size_usd == 100_000_000
    assert cfg.allocation.engine == "stub"
    assert cfg.horizon.start_quarter == "2026Q1"
    assert cfg.horizon.num_quarters == 20


def test_study_config_validates_end_to_end(base_config_path):
    study = load_study_config(base_config_path)
    validate_study_config(study)


def test_extra_keys_rejected():
    with pytest.raises(ValidationError):
        PublicAllocationConfig.model_validate({"stub_weights": {"a": 0.5, "b": 0.5}, "unknown": 1})


def test_stub_weights_must_sum_to_one():
    with pytest.raises(ValidationError):
        PublicAllocationConfig.model_validate({"stub_weights": {"a": 0.5, "b": 0.4}})


def test_negative_weight_rejected():
    with pytest.raises(ValidationError):
        PublicAllocationConfig.model_validate({"stub_weights": {"a": -0.1, "b": 1.1}})


def test_floor_above_ceiling_rejected():
    with pytest.raises(ValidationError):
        SpendingConfig.model_validate(
            {
                "rule": "flat_real",
                "annual_spend_usd": 1000,
                "inflation_pct": 0.0,
                "smoothing": SmoothingConfig(window_quarters=12, weight=0).model_dump(),
                "floor_usd": 100,
                "ceiling_usd": 50,
            }
        )


def test_ta_defaults_rate_length_must_match_period():
    with pytest.raises(ValidationError):
        TADefaultsConfig.model_validate(
            {
                "lifetime_years": 12,
                "commitment_period_years": 4,
                "rate_of_contribution": [0.5, 0.5],  # length 2, not 4
                "bow": 2.5,
                "yield_pct": 0.0,
                "growth_pct": 0.13,
            }
        )


def test_ta_defaults_rates_must_sum_to_one():
    with pytest.raises(ValidationError):
        TADefaultsConfig.model_validate(
            {
                "lifetime_years": 12,
                "commitment_period_years": 4,
                "rate_of_contribution": [0.25, 0.25, 0.25, 0.10],
                "bow": 2.5,
                "yield_pct": 0.0,
                "growth_pct": 0.13,
            }
        )


def test_quarter_format_validated():
    with pytest.raises(ValidationError):
        # Wrong format: "2026 Q1" not "2026Q1"
        from aa_model.io.schemas import HorizonConfig

        HorizonConfig.model_validate({"start_quarter": "2026 Q1", "num_quarters": 4})
