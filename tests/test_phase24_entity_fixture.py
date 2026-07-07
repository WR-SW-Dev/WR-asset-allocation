"""Phase 24 — entity fixture: determinism, reconciliation, and fail-loud
validation across the four dimensions (perimeter, account scope,
balance-sheet segmentation, PE commitment exposure).

Synthetic fixtures only — no client data.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from aa_model.entity import (
    EntityFixture,
    canonical_json,
    content_hash,
    load_entity_fixture,
    pe_exposure_totals,
    segment_totals,
)
from pydantic import ValidationError

_FIXTURE_REL = "data/fixtures/entities/entity_synth_a.yaml"


@pytest.fixture
def synth_fixture(repo_root: Path) -> EntityFixture:
    return load_entity_fixture(repo_root / _FIXTURE_REL)


# ---- load + scope ----------------------------------------------------------


def test_load_synthetic_fixture(synth_fixture: EntityFixture) -> None:
    fx = synth_fixture
    assert fx.entity_id == "entity_synth_a"
    assert fx.fixture_version == "synth_a_v1"
    assert len(fx.accounts) == 2
    assert len(fx.segments) == 11
    assert len(fx.pe_exposure) == 2


def test_account_scope_all_bound_to_entity(synth_fixture: EntityFixture) -> None:
    assert {a.account_id for a in synth_fixture.accounts} == {
        "acct_synth_brokerage",
        "acct_synth_trust",
    }
    assert all(a.entity_id == synth_fixture.entity_id for a in synth_fixture.accounts)


# ---- balance-sheet segmentation -------------------------------------------


def test_segment_reconciliation(synth_fixture: EntityFixture) -> None:
    t = segment_totals(synth_fixture)
    assert t.investable_usd == Decimal("40000000.00")
    assert t.structural_usd == Decimal("60000000.00")
    assert t.total_nav_usd == Decimal("100000000.00")
    # investable + structural == total, exactly
    assert t.investable_usd + t.structural_usd == t.total_nav_usd
    # reconciles to the declared control total
    assert t.total_nav_usd == synth_fixture.expected_total_nav_usd


def test_segment_by_policy_class_covers_seven(synth_fixture: EntityFixture) -> None:
    t = segment_totals(synth_fixture)
    assert set(t.by_policy_class) == {
        "re_opco_stabilized",
        "real_estate",
        "equity",
        "private_equity",
        "absolute_return",
        "fixed_income",
        "cash_and_cash_alts",
    }
    assert t.by_policy_class["fixed_income"] == Decimal("14000000.00")
    assert sum(t.by_policy_class.values()) == t.investable_usd


# ---- PE commitment exposure ------------------------------------------------


def test_pe_exposure_totals(synth_fixture: EntityFixture) -> None:
    p = pe_exposure_totals(synth_fixture)
    assert p.fund_count == 2
    assert p.commitment_usd == Decimal("5000000.00")
    assert p.called_to_date_usd == Decimal("3800000.00")
    assert p.unfunded_usd == Decimal("1200000.00")
    assert p.called_complete and p.unfunded_complete and p.nav_complete
    assert p.by_policy_class_commitment["private_equity"] == Decimal("3000000.00")


def test_pe_exposure_partial_field_flagged_incomplete() -> None:
    fx = EntityFixture.model_validate(
        {
            "fixture_version": "t",
            "entity_id": "e1",
            "as_of_date": "2026-04-30",
            "pe_exposure": [
                {
                    "fund_key": "f1",
                    "entity_id": "e1",
                    "policy_class": "private_equity",
                    "commitment_usd": "1000000",
                    "nav_usd": "900000",
                },
                {
                    "fund_key": "f2",
                    "entity_id": "e1",
                    "policy_class": "private_equity",
                    "commitment_usd": "500000",
                },  # no nav
            ],
        }
    )
    p = pe_exposure_totals(fx)
    assert p.commitment_usd == Decimal("1500000")
    assert p.nav_usd == Decimal("900000")  # sum over present only
    assert p.nav_complete is False  # one fund omitted nav


# ---- determinism -----------------------------------------------------------


def test_content_hash_stable_across_reload(repo_root: Path) -> None:
    h1 = content_hash(load_entity_fixture(repo_root / _FIXTURE_REL))
    h2 = content_hash(load_entity_fixture(repo_root / _FIXTURE_REL))
    assert h1 == h2


def test_hash_independent_of_authoring_order(synth_fixture: EntityFixture) -> None:
    reordered = synth_fixture.model_copy(deep=True)
    reordered.accounts.reverse()
    reordered.segments.reverse()
    reordered.pe_exposure.reverse()
    assert content_hash(reordered) == content_hash(synth_fixture)
    assert canonical_json(reordered) == canonical_json(synth_fixture)


def test_hash_sensitive_to_value_change(synth_fixture: EntityFixture) -> None:
    mutated = synth_fixture.model_copy(deep=True)
    mutated.segments[0].amount_usd += Decimal("1")
    assert content_hash(mutated) != content_hash(synth_fixture)


def test_hash_sensitive_to_as_of_date(synth_fixture: EntityFixture) -> None:
    mutated = synth_fixture.model_copy(deep=True)
    mutated.as_of_date = mutated.as_of_date.replace(year=2025)
    assert content_hash(mutated) != content_hash(synth_fixture)


# ---- fail-loud validation --------------------------------------------------


def _base_payload() -> dict:
    return {
        "fixture_version": "t",
        "entity_id": "e1",
        "as_of_date": "2026-04-30",
        "accounts": [],
        "segments": [],
        "pe_exposure": [],
    }


def test_investable_segment_requires_policy_class() -> None:
    payload = _base_payload()
    payload["segments"] = [{"segment_key": "s1", "segment": "investable", "amount_usd": "100"}]
    with pytest.raises(ValidationError, match="must carry a policy_class"):
        EntityFixture.model_validate(payload)


def test_structural_segment_forbids_policy_class() -> None:
    payload = _base_payload()
    payload["segments"] = [
        {
            "segment_key": "s1",
            "segment": "personal_use",
            "policy_class": "equity",
            "amount_usd": "100",
        }
    ]
    with pytest.raises(ValidationError, match="must NOT carry a policy_class"):
        EntityFixture.model_validate(payload)


def test_pe_unfunded_inconsistency_raises() -> None:
    payload = _base_payload()
    payload["pe_exposure"] = [
        {
            "fund_key": "f1",
            "entity_id": "e1",
            "policy_class": "private_equity",
            "commitment_usd": "1000000",
            "called_to_date_usd": "400000",
            "unfunded_usd": "700000",
        },  # should be 600000
    ]
    with pytest.raises(ValidationError, match="unfunded_usd"):
        EntityFixture.model_validate(payload)


def test_pe_over_called_allowed_unfunded_floors_to_zero() -> None:
    # Cumulative called may exceed commitment (recallable capital re-called);
    # unfunded then reconciles to 0, not a negative number.
    payload = _base_payload()
    payload["pe_exposure"] = [
        {
            "fund_key": "f1",
            "entity_id": "e1",
            "policy_class": "private_equity",
            "commitment_usd": "1000000",
            "called_to_date_usd": "1200000",
            "unfunded_usd": "0",
        },
    ]
    fx = EntityFixture.model_validate(payload)
    assert fx.pe_exposure[0].called_to_date_usd == Decimal("1200000")


def test_pe_negative_unfunded_still_rejected() -> None:
    payload = _base_payload()
    payload["pe_exposure"] = [
        {
            "fund_key": "f1",
            "entity_id": "e1",
            "policy_class": "private_equity",
            "commitment_usd": "1000000",
            "called_to_date_usd": "1200000",
            "unfunded_usd": "-200000",
        },
    ]
    with pytest.raises(ValidationError, match="must be >= 0"):
        EntityFixture.model_validate(payload)


def test_account_outside_perimeter_raises() -> None:
    payload = _base_payload()
    payload["accounts"] = [
        {"account_id": "a1", "entity_id": "other_entity", "valuation_date": "2026-04-30"}
    ]
    with pytest.raises(ValidationError, match="outside this fixture's perimeter"):
        EntityFixture.model_validate(payload)


def test_duplicate_fund_key_raises() -> None:
    payload = _base_payload()
    payload["pe_exposure"] = [
        {"fund_key": "f1", "entity_id": "e1", "policy_class": "equity", "commitment_usd": "1"},
        {"fund_key": "f1", "entity_id": "e1", "policy_class": "equity", "commitment_usd": "2"},
    ]
    with pytest.raises(ValidationError, match="Duplicate fund_key"):
        EntityFixture.model_validate(payload)


def test_expected_total_mismatch_raises() -> None:
    payload = _base_payload()
    payload["expected_total_nav_usd"] = "999.00"
    payload["segments"] = [{"segment_key": "s1", "segment": "personal_use", "amount_usd": "100.00"}]
    with pytest.raises(ValidationError, match="does not reconcile"):
        EntityFixture.model_validate(payload)
