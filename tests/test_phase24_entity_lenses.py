"""Phase 24 — core allocation lens reducers (sub-step 2): balance-sheet,
allocation-vs-target, liquidity. Synthetic fixtures only.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from aa_model.entity import (
    EntityFixture,
    EntityPolicyConfig,
    allocation_vs_target_lens,
    balance_sheet_lens,
    liquidity_lens,
    load_entity_fixture,
    load_entity_policy,
)
from pydantic import ValidationError

_FIXTURE_REL = "data/fixtures/entities/entity_synth_a.yaml"
_POLICY_REL = "data/fixtures/entities/entity_synth_a_policy.yaml"


@pytest.fixture
def synth_fixture(repo_root: Path) -> EntityFixture:
    return load_entity_fixture(repo_root / _FIXTURE_REL)


@pytest.fixture
def synth_policy(repo_root: Path) -> EntityPolicyConfig:
    return load_entity_policy(repo_root / _POLICY_REL)


# ---- balance-sheet lens ----------------------------------------------------


def test_balance_sheet_lens(synth_fixture: EntityFixture) -> None:
    lens = balance_sheet_lens(synth_fixture)
    assert lens.total_nav_usd == Decimal("100000000.00")
    assert lens.investable_usd == Decimal("40000000.00")
    assert lens.structural_usd == Decimal("60000000.00")
    assert lens.investable_pct_of_nav == Decimal("0.4")
    assert lens.by_policy_class_usd["equity"] == Decimal("4000000.00")


# ---- allocation vs target --------------------------------------------------


def test_allocation_vs_target_rows_in_policy_order(
    synth_fixture: EntityFixture, synth_policy: EntityPolicyConfig
) -> None:
    a = allocation_vs_target_lens(synth_fixture, synth_policy)
    assert a.investable_base_usd == Decimal("40000000.00")
    assert [r.policy_class for r in a.rows] == [
        "re_opco_stabilized",
        "real_estate",
        "equity",
        "private_equity",
        "absolute_return",
        "fixed_income",
        "cash_and_cash_alts",
    ]


def test_allocation_vs_target_values(
    synth_fixture: EntityFixture, synth_policy: EntityPolicyConfig
) -> None:
    a = allocation_vs_target_lens(synth_fixture, synth_policy)
    rows = {r.policy_class: r for r in a.rows}

    equity = rows["equity"]
    assert equity.current_pct == Decimal("0.1")
    assert equity.target_pct == Decimal("0.40")
    assert equity.gap_pp == Decimal("-30")  # 10% vs 40%
    assert equity.to_target_usd == Decimal("12000000.00")  # buy $12M
    assert equity.action == "underweight"

    cash = rows["cash_and_cash_alts"]
    assert cash.gap_pp == Decimal("22.5")  # 27.5% vs 5%
    assert cash.to_target_usd == Decimal("-9000000.00")  # trim $9M
    assert cash.action == "overweight"

    # in-band: current == target within the default 2pp band
    assert rows["re_opco_stabilized"].action == "in_band"
    assert rows["real_estate"].action == "in_band"
    # small miss beyond band
    assert rows["private_equity"].gap_pp == Decimal("-2.5")
    assert rows["private_equity"].action == "underweight"


def test_allocation_band_widens_in_band(
    synth_fixture: EntityFixture, synth_policy: EntityPolicyConfig
) -> None:
    a = allocation_vs_target_lens(synth_fixture, synth_policy, band_pp=Decimal("3"))
    rows = {r.policy_class: r for r in a.rows}
    # PE gap is 2.5pp — inside a 3pp band now
    assert rows["private_equity"].action == "in_band"


def test_allocation_entity_mismatch_raises(synth_fixture: EntityFixture) -> None:
    other = EntityPolicyConfig.model_validate(
        {
            "policy_version": "p",
            "entity_id": "other_entity",
            "targets": {"equity": "1.0"},
        }
    )
    with pytest.raises(ValueError, match="does not match"):
        allocation_vs_target_lens(synth_fixture, other)


def test_class_held_without_target_is_overweight() -> None:
    # entity holds fixed_income but policy only targets equity → fixed_income
    # shows against a 0% target (overweight), equity underweight.
    fx = EntityFixture.model_validate(
        {
            "fixture_version": "t",
            "entity_id": "e1",
            "as_of_date": "2026-04-30",
            "segments": [
                {
                    "segment_key": "s1",
                    "segment": "investable",
                    "policy_class": "equity",
                    "amount_usd": "500000",
                },
                {
                    "segment_key": "s2",
                    "segment": "investable",
                    "policy_class": "fixed_income",
                    "amount_usd": "500000",
                },
            ],
        }
    )
    policy = EntityPolicyConfig.model_validate(
        {"policy_version": "p", "entity_id": "e1", "targets": {"equity": "1.0"}}
    )
    rows = {r.policy_class: r for r in allocation_vs_target_lens(fx, policy).rows}
    assert rows["fixed_income"].target_pct == Decimal("0")
    assert rows["fixed_income"].action == "overweight"
    assert rows["equity"].action == "underweight"


# ---- liquidity lens --------------------------------------------------------


def test_liquidity_lens(synth_fixture: EntityFixture) -> None:
    lens = liquidity_lens(synth_fixture)
    assert lens.investable_usd == Decimal("40000000.00")
    assert list(lens.by_tier_usd) == ["daily", "monthly", "quarterly", "at_maturity"]
    assert lens.by_tier_usd["daily"] == Decimal("15000000.00")  # equity + cash
    assert lens.by_tier_usd["at_maturity"] == Decimal("9000000.00")  # re_opco + re + pe
    assert lens.by_tier_pct["daily"] == Decimal("0.375")
    assert lens.liquid_within_30d_usd == Decimal("29000000.00")  # daily + monthly
    assert lens.liquid_within_30d_pct == Decimal("0.725")


# ---- policy + schema validation --------------------------------------------


def test_policy_targets_must_sum_to_one() -> None:
    with pytest.raises(ValidationError, match="sum to 1.0"):
        EntityPolicyConfig.model_validate(
            {
                "policy_version": "p",
                "entity_id": "e1",
                "targets": {"equity": "0.5", "fixed_income": "0.2"},  # 0.7
            }
        )


def test_policy_negative_target_raises() -> None:
    with pytest.raises(ValidationError, match=">= 0"):
        EntityPolicyConfig.model_validate(
            {
                "policy_version": "p",
                "entity_id": "e1",
                "targets": {"equity": "1.2", "fixed_income": "-0.2"},
            }
        )


def test_structural_segment_forbids_liquidity_tier() -> None:
    with pytest.raises(ValidationError, match="must NOT carry a liquidity_tier"):
        EntityFixture.model_validate(
            {
                "fixture_version": "t",
                "entity_id": "e1",
                "as_of_date": "2026-04-30",
                "segments": [
                    {
                        "segment_key": "s1",
                        "segment": "personal_use",
                        "amount_usd": "100",
                        "liquidity_tier": "daily",
                    }
                ],
            }
        )
