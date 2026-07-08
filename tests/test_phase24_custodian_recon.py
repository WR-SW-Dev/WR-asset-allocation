"""Phase 24 — custodian statement reconciliation lens. Synthetic only."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest
from aa_model.entity import (
    EntityFixture,
    custodian_reconciliation_lens,
    load_entity_fixture,
)
from pydantic import ValidationError

_FIXTURE_REL = "data/fixtures/entities/entity_synth_a.yaml"


@pytest.fixture
def synth_fixture(repo_root: Path) -> EntityFixture:
    return load_entity_fixture(repo_root / _FIXTURE_REL)


def test_custodian_recon_lens(synth_fixture: EntityFixture) -> None:
    results = custodian_reconciliation_lens(synth_fixture)
    assert len(results) == 1
    r = results[0]
    assert r.account_id == "acct_synth_brokerage"
    assert r.beginning_value_usd == Decimal("10000000.00")
    assert r.ending_value_usd == Decimal("11000000.00")
    assert r.net_flow_usd == Decimal("200000.00")  # 500k additions - 300k subtractions
    assert r.change_in_value_usd == Decimal("800000.00")
    assert r.holdings_total_usd == Decimal("11000000.00")
    assert r.holdings_reconciles  # by-type sum == ending
    assert r.holdings_delta_usd == Decimal("0.00")
    assert list(r.holdings_by_type_usd) == [
        "core_cash",
        "fixed_income_etp",
        "mutual_funds_stock",
    ]  # sorted
    assert r.statement_pending is False


def test_pending_statement_ending_and_holdings_only() -> None:
    # Statement not yet loaded: no beginning/flows, only ending + holdings.
    fx = EntityFixture.model_validate(
        {
            "fixture_version": "t",
            "entity_id": "e1",
            "as_of_date": "2026-04-30",
            "custodian_reconciliations": [
                {
                    "account_id": "acct_1423",
                    "ending_value_usd": "5000000",
                    "holdings_by_type_usd": {"core_cash": "1000000", "equity_etp": "4000000"},
                }
            ],
        }
    )
    r = custodian_reconciliation_lens(fx)[0]
    assert r.statement_pending is True
    assert r.beginning_value_usd is None
    assert r.net_flow_usd is None
    assert r.holdings_total_usd == Decimal("5000000")
    assert r.holdings_reconciles  # ties to ending


def _base() -> dict:
    return {"fixture_version": "t", "entity_id": "e1", "as_of_date": "2026-04-30"}


def test_roll_forward_violation_raises() -> None:
    with pytest.raises(ValidationError, match="beginning \\+ additions"):
        EntityFixture.model_validate(
            {
                **_base(),
                "custodian_reconciliations": [
                    {
                        "account_id": "a1",
                        "beginning_value_usd": "100",
                        "additions_usd": "10",
                        "subtractions_usd": "5",
                        "change_in_value_usd": "0",
                        "ending_value_usd": "200",  # should be 105
                    }
                ],
            }
        )


def test_holdings_mismatch_flagged_not_raised() -> None:
    fx = EntityFixture.model_validate(
        {
            **_base(),
            "custodian_reconciliations": [
                {
                    "account_id": "a1",
                    "beginning_value_usd": "1000",
                    "ending_value_usd": "1000",  # roll-forward ok (no flows/change)
                    "holdings_by_type_usd": {"core_cash": "900"},  # != 1000
                }
            ],
        }
    )
    r = custodian_reconciliation_lens(fx)[0]
    assert r.holdings_reconciles is False
    assert r.holdings_delta_usd == Decimal("-100")


def test_duplicate_recon_account_raises() -> None:
    with pytest.raises(ValidationError, match="Duplicate custodian reconciliation account"):
        EntityFixture.model_validate(
            {
                **_base(),
                "custodian_reconciliations": [
                    {"account_id": "a1", "beginning_value_usd": "0", "ending_value_usd": "0"},
                    {"account_id": "a1", "beginning_value_usd": "0", "ending_value_usd": "0"},
                ],
            }
        )


def test_negative_additions_raises() -> None:
    with pytest.raises(ValidationError):
        EntityFixture.model_validate(
            {
                **_base(),
                "custodian_reconciliations": [
                    {
                        "account_id": "a1",
                        "beginning_value_usd": "100",
                        "additions_usd": "-10",
                        "ending_value_usd": "90",
                    }
                ],
            }
        )
