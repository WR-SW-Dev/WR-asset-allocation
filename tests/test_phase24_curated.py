"""Phase 24 — curated-source fixture builder + reader + CLI from Investment
Summary. Synthetic fixtures only (a tiny in-memory xlsx for the reader)."""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import openpyxl
import pytest
from aa_model.entity import (
    CuratedPosition,
    fixture_from_curated_positions,
    holdings_detail_lens,
    read_investment_summary_positions,
    segment_totals,
    tier_from_label,
)
from aa_model.entity.cli import main as cli_main

# ---- tier_from_label -------------------------------------------------------


@pytest.mark.parametrize(
    "label,tier",
    [
        ("Daily", "daily"),
        ("Monthly", "monthly"),
        ("Quarterly", "quarterly"),
        ("At Maturity", "at_maturity"),
        ("  at   maturity ", "at_maturity"),
        ("", None),
        (None, None),
    ],
)
def test_tier_from_label(label, tier) -> None:
    assert tier_from_label(label) == tier


def test_tier_from_label_unknown_raises() -> None:
    with pytest.raises(ValueError, match="liquidity label"):
        tier_from_label("Fortnightly")


# ---- builder ---------------------------------------------------------------


def _positions() -> list[CuratedPosition]:
    return [
        CuratedPosition("Fund A", "Equity", Decimal("600"), "Daily"),
        CuratedPosition("Fund B", "Equity", Decimal("400"), "Daily"),
        CuratedPosition(
            "Fund C",
            "Private Equity",
            Decimal("1000"),
            "At Maturity",
            commitment_usd=Decimal("2000"),
            unfunded_usd=Decimal("1000"),
        ),
    ]


def test_fixture_from_curated_positions() -> None:
    fx = fixture_from_curated_positions(
        _positions(), entity_id="e1", as_of_date="2026-03-31", fixture_version="v1"
    )
    assert len(fx.holdings) == 3
    # segments: equity/daily (1000) + private_equity/at_maturity (1000)
    st = segment_totals(fx)
    assert st.investable_usd == Decimal("2000")
    assert st.by_policy_class["equity"] == Decimal("1000")
    assert st.by_policy_class["private_equity"] == Decimal("1000")
    # holdings reconcile to segments per class
    groups = {g.policy_class: g for g in holdings_detail_lens(fx).groups}
    assert groups["equity"].reconciles and groups["private_equity"].reconciles
    # pe_exposure only for the committed position
    assert len(fx.pe_exposure) == 1
    assert fx.pe_exposure[0].commitment_usd == Decimal("2000")
    assert fx.pe_exposure[0].unfunded_usd == Decimal("1000")


def test_builder_dedupes_names() -> None:
    fx = fixture_from_curated_positions(
        [
            CuratedPosition("Same Fund", "Equity", Decimal("1"), "Daily"),
            CuratedPosition("Same Fund", "Equity", Decimal("2"), "Daily"),
        ],
        entity_id="e1",
        as_of_date="2026-03-31",
        fixture_version="v1",
    )
    keys = [h.holding_key for h in fx.holdings]
    assert len(set(keys)) == 2  # de-duped


# ---- xlsx reader -----------------------------------------------------------


def _write_synth_workbook(path: Path) -> None:
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Data"
    header = [""] * 16
    header[4], header[9], header[10], header[15] = (
        "Asset Allocation Class",
        "Current Balance",
        "Invested Entities",
        "Liquidity",
    )
    ws.append(header)

    def _row(name, cls, mv, ent, tier, commit=None, unf=None):
        r = [None] * 16
        r[0] = "Mgr " + name
        r[2] = name
        r[4] = cls
        r[7] = commit
        r[8] = unf
        r[9] = mv
        r[10] = ent
        r[15] = tier
        return r

    ws.append(_row("Fund A", "Equity", 600, "EntityX", "Daily"))
    ws.append(_row("Fund C", "Private Equity", 1000, "EntityX", "At Maturity", 2000, 1000))
    ws.append(_row("Other Fund", "Equity", 999, "EntityY", "Daily"))  # filtered out
    wb.save(path)


def test_reader_filters_by_entity(tmp_path: Path) -> None:
    p = tmp_path / "inv.xlsx"
    _write_synth_workbook(p)
    positions = read_investment_summary_positions(p, "EntityX")
    assert len(positions) == 2  # EntityY excluded
    assert {pos.policy_class_label for pos in positions} == {"Equity", "Private Equity"}
    pe = next(pos for pos in positions if pos.policy_class_label == "Private Equity")
    assert pe.commitment_usd == Decimal("2000")
    assert pe.liquidity_label == "At Maturity"


# ---- CLI end-to-end from Investment Summary --------------------------------


def test_cli_from_investment_summary(tmp_path: Path) -> None:
    wb = tmp_path / "inv.xlsx"
    _write_synth_workbook(wb)
    out = tmp_path / "study"
    rc = cli_main(["--from-investment-summary", str(wb), "--entity", "EntityX", "--out", str(out)])
    assert rc == 0
    assert (out / "study.md").exists()
    assert (out / "manifest.json").exists()


def test_cli_from_investment_summary_no_match_errors(tmp_path: Path) -> None:
    wb = tmp_path / "inv.xlsx"
    _write_synth_workbook(wb)
    with pytest.raises(SystemExit, match="no positions found"):
        cli_main(
            [
                "--from-investment-summary",
                str(wb),
                "--entity",
                "Nobody",
                "--out",
                str(tmp_path / "x"),
            ]
        )


def test_cli_mutually_exclusive_sources(tmp_path: Path) -> None:
    with pytest.raises(SystemExit):
        cli_main(["--fixture", "a.yaml", "--from-investment-summary", "b.xlsx"])
