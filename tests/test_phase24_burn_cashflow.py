"""Phase 24 — burn-rate + cash-flow/runway lenses. Synthetic fixtures only."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from aa_model.entity import (
    EntityFixture,
    burn_rate_lens,
    cash_flow_lens,
    load_entity_fixture,
)
from pydantic import ValidationError

_FIXTURE_REL = "data/fixtures/entities/entity_synth_a.yaml"


@pytest.fixture
def synth_fixture(repo_root: Path) -> EntityFixture:
    return load_entity_fixture(repo_root / _FIXTURE_REL)


# ---- burn rate -------------------------------------------------------------


def test_burn_rate_lens(synth_fixture: EntityFixture) -> None:
    b = burn_rate_lens(synth_fixture)
    assert b.years == [2023, 2024, 2025]
    assert b.total_by_year == {
        2023: Decimal("700000.00"),
        2024: Decimal("750000.00"),
        2025: Decimal("650000.00"),
    }
    assert b.without_taxes_by_year[2024] == Decimal("430000.00")  # 750k - 320k taxes
    assert b.without_charitable_by_year[2023] == Decimal("650000.00")  # 700k - 50k
    assert b.avg_annual_total == Decimal("700000.00")  # (700+750+650)/3
    assert b.avg_annual_without_taxes == Decimal("400000.00")
    assert b.avg_quarterly_without_taxes == Decimal("100000.00")
    assert b.lightest_year == 2025
    assert b.lightest_year_total == Decimal("650000.00")
    assert b.by_category_total["travel"] == Decimal("300000.00")


def test_burn_rate_empty() -> None:
    fx = EntityFixture.model_validate(
        {"fixture_version": "t", "entity_id": "e1", "as_of_date": "2026-04-30"}
    )
    b = burn_rate_lens(fx)
    assert b.years == []
    assert b.avg_annual_total == Decimal("0")


def test_duplicate_burn_category_raises() -> None:
    with pytest.raises(ValidationError, match="Duplicate burn_rate category"):
        EntityFixture.model_validate(
            {
                "fixture_version": "t",
                "entity_id": "e1",
                "as_of_date": "2026-04-30",
                "burn_rate": [
                    {"category": "travel", "amounts_by_year": {2025: "1"}},
                    {"category": "travel", "amounts_by_year": {2025: "2"}},
                ],
            }
        )


def test_burn_negative_amount_raises() -> None:
    with pytest.raises(ValidationError, match=">= 0"):
        EntityFixture.model_validate(
            {
                "fixture_version": "t",
                "entity_id": "e1",
                "as_of_date": "2026-04-30",
                "burn_rate": [{"category": "travel", "amounts_by_year": {2025: "-5"}}],
            }
        )


# ---- cash flow / runway ----------------------------------------------------


def test_cash_flow_lens_base(synth_fixture: EntityFixture) -> None:
    c = cash_flow_lens(synth_fixture)
    assert c.investable_base_usd == Decimal("40000000.00")
    assert c.policy_target_cash_usd == Decimal("40000000.00") * Decimal("0.10")
    assert c.net_annual_draw_usd == Decimal("300000.00")  # 400k - 100k CRUT
    assert c.monthly_living_usd == Decimal("400000.00") / Decimal("12")
    assert c.cash_overweight_usd == Decimal("7000000.00")  # 11M - 4M policy
    assert c.reserve_amount_usd == Decimal("600000.00")  # 2yr * 300k
    assert c.deployable_after_reserve_usd == Decimal("10400000.00")  # 11M - 600k
    assert c.runway_current_years == Decimal("11000000.00") / Decimal("300000.00")
    assert c.runway_policy_years == Decimal("4000000.00") / Decimal("300000.00")
    # scenario is OFF in the fixture: add-ons summed but not applied
    assert c.scenario_addon_total_usd == Decimal("80000.00")
    assert c.net_annual_draw_scenario_usd == c.net_annual_draw_usd
    assert c.runway_current_scenario_years == c.runway_current_years


def test_cash_flow_scenario_applied() -> None:
    fx = EntityFixture.model_validate(
        {
            "fixture_version": "t",
            "entity_id": "e1",
            "as_of_date": "2026-04-30",
            "segments": [
                {
                    "segment_key": "eq",
                    "segment": "investable",
                    "policy_class": "equity",
                    "amount_usd": "1000000",
                }
            ],
            "cash_flow": {
                "living_expenses_annual_usd": "500000",
                "crut_distribution_annual_usd": "100000",
                "managed_cash_usd": "2000000",
                "policy_cash_pct": "0.05",
                "reserve_years": "1",
                "scenario_enabled": True,
                "scenario_addons_usd": {"increased_travel": "100000"},
            },
        }
    )
    c = cash_flow_lens(fx)
    assert c.net_annual_draw_usd == Decimal("400000")  # base 500k - 100k
    assert c.net_annual_draw_scenario_usd == Decimal("500000")  # + 100k add-on
    assert c.runway_current_years == Decimal("2000000") / Decimal("400000")  # 5
    assert c.runway_current_scenario_years == Decimal("2000000") / Decimal("500000")  # 4
    assert c.deployable_after_reserve_scenario_usd == Decimal("1500000")  # 2M - 1yr*500k


def test_cash_flow_net_inflow_runway_none() -> None:
    # CRUT exceeds living expenses → no net draw → unbounded runway, no reserve
    fx = EntityFixture.model_validate(
        {
            "fixture_version": "t",
            "entity_id": "e1",
            "as_of_date": "2026-04-30",
            "cash_flow": {
                "living_expenses_annual_usd": "100000",
                "crut_distribution_annual_usd": "300000",
                "managed_cash_usd": "500000",
                "policy_cash_pct": "0.10",
            },
        }
    )
    c = cash_flow_lens(fx)
    assert c.net_annual_draw_usd == Decimal("-200000")
    assert c.runway_current_years is None
    assert c.reserve_amount_usd == Decimal("0")
    assert c.deployable_after_reserve_usd == Decimal("500000")


def test_cash_flow_missing_raises(synth_fixture: EntityFixture) -> None:
    fx = EntityFixture.model_validate(
        {"fixture_version": "t", "entity_id": "e1", "as_of_date": "2026-04-30"}
    )
    with pytest.raises(ValueError, match="no cash_flow assumptions"):
        cash_flow_lens(fx)


def test_policy_cash_pct_over_one_raises() -> None:
    with pytest.raises(ValidationError, match="fraction in"):
        EntityFixture.model_validate(
            {
                "fixture_version": "t",
                "entity_id": "e1",
                "as_of_date": "2026-04-30",
                "cash_flow": {
                    "living_expenses_annual_usd": "1",
                    "managed_cash_usd": "1",
                    "policy_cash_pct": "1.5",
                },
            }
        )
