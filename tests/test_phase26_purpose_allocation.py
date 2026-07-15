"""Phase 26 — purpose (goals-based) allocation: config validation, holding→
purpose resolution, lens, renderer gating, CLI. Synthetic fixtures only —
per the design lock, the real workbook oracle runs local/gitignored.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from aa_model.entity import (
    EntityPurposePolicyConfig,
    load_entity_purpose_policy,
)
from pydantic import ValidationError

D = Decimal


def _band(purpose: str, target: str, lo: str = "0", hi: str = "0") -> dict:
    return {
        "purpose": purpose,
        "target": target,
        "lower_band_pp": lo,
        "upper_band_pp": hi,
    }


def _config(**overrides) -> dict:
    cfg = {
        "purpose_policy_version": "synth_purpose_v1",
        "entity_id": "entity_synth_a",
        "bands": {
            "liquidity": _band("liquidity", "0.05", "0.03", "0.10"),
            "stability": _band("stability", "0.10", "0.05", "0.05"),
            "income": _band("income", "0.34", "0.10", "0.10"),
            "growth": _band("growth", "0.45", "0.10", "0.10"),
            "aggressive_growth": _band("aggressive_growth", "0.05", "0.05", "0.05"),
            "community": _band("community", "0.01", "0.01", "0.03"),
        },
        "assignments": {},
        "default_by_policy_class": {
            "cash_and_cash_alts": "liquidity",
            "fixed_income": "income",
            "equity": "growth",
            "real_estate": "growth",
            "private_equity": "aggressive_growth",
            "absolute_return": "hedge",
            "re_opco_stabilized": "growth",
        },
    }
    cfg.update(overrides)
    return cfg


# ---- group 1: config validation --------------------------------------------


def test_config_valid_and_derived_bounds() -> None:
    cfg = EntityPurposePolicyConfig.model_validate(_config())
    liq = cfg.bands["liquidity"]
    assert liq.min_pct == D("0.02")
    assert liq.max_pct == D("0.15")
    # floor at zero: community 1% target with 1pp lower band
    com = cfg.bands["community"]
    assert com.min_pct == D("0")
    assert com.max_pct == D("0.04")


def test_config_targets_must_sum_to_one() -> None:
    bad = _config()
    bad["bands"]["growth"] = _band("growth", "0.30", "0.10", "0.10")  # sum 0.85
    with pytest.raises(ValidationError, match="sum to 1.0"):
        EntityPurposePolicyConfig.model_validate(bad)


def test_config_negative_band_rejected() -> None:
    bad = _config()
    bad["bands"]["income"] = _band("income", "0.34", "-0.01", "0.10")
    with pytest.raises(ValidationError, match="finite and >= 0"):
        EntityPurposePolicyConfig.model_validate(bad)


def test_config_band_key_purpose_mismatch_rejected() -> None:
    bad = _config()
    bad["bands"]["income"] = _band("hedge", "0.34")
    with pytest.raises(ValidationError, match="must match its dict key"):
        EntityPurposePolicyConfig.model_validate(bad)


def test_config_unknown_purpose_rejected() -> None:
    bad = _config()
    bad["bands"]["speculation"] = _band("growth", "0.00")
    with pytest.raises(ValidationError):
        EntityPurposePolicyConfig.model_validate(bad)


def test_config_version_must_be_url_safe() -> None:
    with pytest.raises(ValidationError, match="URL-safe"):
        EntityPurposePolicyConfig.model_validate(_config(purpose_policy_version="not ok/version"))


def test_config_strict_extra_keys_rejected() -> None:
    with pytest.raises(ValidationError):
        EntityPurposePolicyConfig.model_validate(_config(unexpected_key=1))


def test_config_empty_bands_rejected() -> None:
    with pytest.raises(ValidationError, match="non-empty"):
        EntityPurposePolicyConfig.model_validate(_config(bands={}))


def test_loader_yaml_roundtrip(tmp_path: Path) -> None:
    import yaml

    path = tmp_path / "purpose_policy.yaml"
    path.write_text(yaml.safe_dump(_config()), encoding="utf-8")
    cfg = load_entity_purpose_policy(path)
    assert cfg.purpose_policy_version == "synth_purpose_v1"
    assert cfg.bands["growth"].target == D("0.45")


def test_loader_rejects_unknown_extension(tmp_path: Path) -> None:
    path = tmp_path / "purpose_policy.txt"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported purpose-policy extension"):
        load_entity_purpose_policy(path)
