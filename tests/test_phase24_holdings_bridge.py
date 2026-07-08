"""Phase 24 — crosswalk + Phase-15 -> entity holdings bridge. Synthetic only."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest
from aa_model.entity import (
    EntityFixture,
    holdings_detail_lens,
    holdings_from_positions,
    liquidity_tier_for,
    policy_class_for,
    policy_class_from_label,
)
from aa_model.ingestion.schemas_position import PositionRecord


def _pos(
    position_id: str,
    asset_class: str,
    market_value_usd: float,
    *,
    bucket: str = "daily_liquid",
    account_id: str = "acct1",
    manager_id: str | None = None,
    source_row: int = 1,
) -> PositionRecord:
    return PositionRecord(
        position_id=position_id,
        account_id=account_id,
        manager_id=manager_id,
        asset_class=asset_class,
        market_value_usd=market_value_usd,
        liquidity_bucket=bucket,
        valuation_date=date(2026, 4, 30),
        source_row=source_row,
    )


# ---- policy-class crosswalk ------------------------------------------------


@pytest.mark.parametrize(
    "asset_class,expected",
    [
        ("public_equity", "equity"),
        ("private_equity", "private_equity"),
        ("fixed_income_public", "fixed_income"),
        ("private_credit", "fixed_income"),
        ("cash_equivalent", "cash_and_cash_alts"),
        ("hedge_fund", "absolute_return"),
        ("real_estate_debt", "real_estate"),
    ],
)
def test_policy_class_unambiguous(asset_class: str, expected: str) -> None:
    assert policy_class_for(asset_class) == expected


@pytest.mark.parametrize(
    "bucket,expected",
    [
        ("re_stabilized", "re_opco_stabilized"),
        ("opco_strategic", "re_opco_stabilized"),
        ("re_development", "real_estate"),
        ("re_land", "real_estate"),
        ("illiquid", "real_estate"),
        (None, "real_estate"),
    ],
)
def test_real_estate_equity_disambiguated_by_bucket(bucket, expected: str) -> None:
    assert policy_class_for("real_estate_equity", bucket) == expected


@pytest.mark.parametrize("ac", ["infrastructure", "commodity", "direct_operating", "other"])
def test_policy_class_no_home_raises(ac: str) -> None:
    with pytest.raises(ValueError, match="no Wake Robin policy-class mapping"):
        policy_class_for(ac)


# ---- liquidity-tier crosswalk ----------------------------------------------


@pytest.mark.parametrize(
    "bucket,tier",
    [
        ("cash_equivalent", "daily"),
        ("daily_liquid", "daily"),
        ("semi_liquid", "quarterly"),
        ("illiquid", "at_maturity"),
        ("locked_strategic", "at_maturity"),
        ("opco_strategic", "at_maturity"),
    ],
)
def test_liquidity_tier(bucket: str, tier: str) -> None:
    assert liquidity_tier_for(bucket) == tier


def test_liquidity_tier_unknown_raises() -> None:
    with pytest.raises(ValueError, match="unknown liquidity_bucket"):
        liquidity_tier_for("nonsense")


# ---- bridge ----------------------------------------------------------------


def test_bridge_maps_and_converts() -> None:
    positions = [
        _pos("AKRE", "public_equity", 1234.56, bucket="daily_liquid"),
        _pos("Rockwood", "private_equity", 500000.0, bucket="illiquid", manager_id="mgr1"),
    ]
    holdings = holdings_from_positions(positions)
    assert holdings[0].policy_class == "equity"
    assert holdings[0].asset_class == "public_equity"
    assert holdings[0].market_value_usd == Decimal("1234.56")  # float -> Decimal, no drift
    assert holdings[0].liquidity_tier == "daily"
    assert holdings[1].policy_class == "private_equity"
    assert holdings[1].liquidity_tier == "at_maturity"
    assert holdings[1].manager_id == "mgr1"


def test_bridge_without_liquidity_tier() -> None:
    holdings = holdings_from_positions(
        [_pos("p1", "public_equity", 100.0)], with_liquidity_tier=False
    )
    assert holdings[0].liquidity_tier is None


def test_bridge_sanitizes_and_dedupes_keys() -> None:
    positions = [
        _pos(
            "Greens of Wyoming", "real_estate_equity", 10.0, bucket="re_development", source_row=1
        ),
        _pos(
            "Greens of Wyoming", "real_estate_equity", 20.0, bucket="re_development", source_row=2
        ),
    ]
    keys = [h.holding_key for h in holdings_from_positions(positions)]
    assert keys == ["Greens_of_Wyoming", "Greens_of_Wyoming_2"]  # URL-safe + de-duped
    # both are direct RE
    assert {h.policy_class for h in holdings_from_positions(positions)} == {"real_estate"}


def test_bridged_holdings_reconcile_in_lens() -> None:
    positions = [
        _pos("eq1", "public_equity", 600.0),
        _pos("eq2", "public_equity", 400.0),
    ]
    fx = EntityFixture.model_validate(
        {
            "fixture_version": "t",
            "entity_id": "e1",
            "as_of_date": "2026-04-30",
            "segments": [
                {
                    "segment_key": "inv_eq",
                    "segment": "investable",
                    "policy_class": "equity",
                    "amount_usd": "1000",
                }
            ],
        }
    )
    fx = fx.model_copy(update={"holdings": holdings_from_positions(positions)})
    grp = {g.policy_class: g for g in holdings_detail_lens(fx).groups}["equity"]
    assert grp.subtotal_usd == Decimal("1000")
    assert grp.reconciles


# ---- firm policy-class label normalizer ------------------------------------


@pytest.mark.parametrize(
    "label,expected",
    [
        ("Fixed Income", "fixed_income"),
        ("Private Equity", "private_equity"),
        ("Equity", "equity"),
        ("Real Estate", "real_estate"),
        ("Absolute Return", "absolute_return"),
        ("Cash & Cash Alts", "cash_and_cash_alts"),
        ("RE OpCo Stabilized", "re_opco_stabilized"),
        ("  private   equity  ", "private_equity"),  # whitespace-insensitive
        ("CASH AND CASH ALTS", "cash_and_cash_alts"),  # case + '&'/'and'
    ],
)
def test_policy_class_from_label(label: str, expected: str) -> None:
    assert policy_class_from_label(label) == expected


def test_policy_class_from_label_unknown_raises() -> None:
    with pytest.raises(ValueError, match="not one of the seven Wake Robin"):
        policy_class_from_label("Crypto")
