"""Phase 22 — manager terms consumer layer diagnostics.

12 tests. Synthetic fixtures only — no live workbook, no real fund data.
See MODEL_DOCUMENTATION.md §Phase 22 design.

Coverage (12 tests):
1.  daily redemption → effective_window_days = notice_days or 0
2.  quarterly redemption → 91 + notice_days
3.  redemption_frequency="none" → effective_window_days=None
4.  confidence="unknown" / no redemption_frequency → terms_unknown bucket, advisory
5.  lockup_end_date in future → max(freq+notice, lockup_remaining)
6.  lockup_end_date in past → no lockup offset applied
7.  gate_pct > 0 + side_pocket=True → both flags present in entry
8.  fee_basis="nav" + bps → correct annual_fee_drag_usd = nav × bps / 10_000
9.  fee_basis="committed" → annual_fee_drag_usd=None + advisory emitted
10. carry advisory: carry > 0 + hurdle known; carry > 0 + hurdle None
11. capital_call_notice: unfunded aggregation split by known / unknown notice
12. default byte-stable: empty positions + empty manager_terms → no crash;
    manager_terms_diag=None when position_ingestion=None
"""

from __future__ import annotations

from datetime import date

import pytest
from aa_model.liquidity.manager_terms_diagnostics import (
    compute_manager_terms_diagnostics,
)

# ---- shared synthetic helpers -----------------------------------------------


def _pos(
    *,
    manager_id: str | None = "mgr_a",
    market_value_usd: float = 1_000_000.0,
    liquidity_bucket: str = "semi_liquid",
    unfunded_commitment_usd: float | None = None,
) -> object:
    from aa_model.ingestion.schemas_position import PositionRecord

    return PositionRecord(
        position_id=f"pos_{manager_id or 'none'}",
        account_id="account_000",
        manager_id=manager_id,
        market_value_usd=market_value_usd,
        liquidity_bucket=liquidity_bucket,  # type: ignore[arg-type]
        valuation_date=date(2026, 3, 31),
        source_row=1,
        unfunded_commitment_usd=unfunded_commitment_usd,
    )


def _terms(
    manager_id: str = "mgr_a",
    *,
    redemption_frequency: str | None = "quarterly",
    notice_days: int | None = None,
    gate_pct: float | None = None,
    side_pocket: bool = False,
    lockup_end_date: date | None = None,
    capital_call_notice_days: int | None = None,
    management_fee_bps: int | None = None,
    carry_pct: float | None = None,
    hurdle_rate: float | None = None,
    fee_basis: str = "unknown",
    confidence: str = "unknown",
) -> object:
    from aa_model.ingestion.schemas_position import ManagerTermsRecord

    kw: dict = dict(
        manager_id=manager_id,
        redemption_frequency=redemption_frequency,  # type: ignore[arg-type]
        notice_days=notice_days,
        gate_pct=gate_pct,
        side_pocket=side_pocket,
        lockup_end_date=lockup_end_date,
        capital_call_notice_days=capital_call_notice_days,
        management_fee_bps=management_fee_bps,
        carry_pct=carry_pct,
        hurdle_rate=hurdle_rate,
        fee_basis=fee_basis,  # type: ignore[arg-type]
        confidence=confidence,  # type: ignore[arg-type]
    )
    return ManagerTermsRecord(**kw)


_AS_OF = date(2026, 3, 31)


# ---- 1. daily redemption ----------------------------------------------------


def test_daily_redemption_window():
    """Phase 22 #1: daily + 5 notice days → window = 5."""
    pos = [_pos(liquidity_bucket="semi_liquid")]
    mgr = [_terms("mgr_a", redemption_frequency="daily", notice_days=5, confidence="unknown")]
    diag = compute_manager_terms_diagnostics(pos, mgr, as_of_date=_AS_OF)
    entry = diag.liquidity_horizon.entries[0]
    assert entry.effective_window_days == 5


# ---- 2. quarterly redemption ------------------------------------------------


def test_quarterly_redemption_window():
    """Phase 22 #2: quarterly + 30 notice days → window = 121."""
    pos = [_pos(liquidity_bucket="semi_liquid")]
    mgr = [_terms("mgr_a", redemption_frequency="quarterly", notice_days=30)]
    diag = compute_manager_terms_diagnostics(pos, mgr, as_of_date=_AS_OF)
    entry = diag.liquidity_horizon.entries[0]
    assert entry.effective_window_days == 121  # 91 + 30


# ---- 3. frequency="none" → None --------------------------------------------


def test_redemption_none_yields_null_window():
    """Phase 22 #3: redemption_frequency='none' → effective_window_days=None."""
    pos = [_pos(liquidity_bucket="semi_liquid")]
    mgr = [_terms("mgr_a", redemption_frequency="none")]
    diag = compute_manager_terms_diagnostics(pos, mgr, as_of_date=_AS_OF)
    entry = diag.liquidity_horizon.entries[0]
    assert entry.effective_window_days is None
    assert diag.liquidity_horizon.by_horizon_bucket["terms_unknown"] == 1_000_000.0


# ---- 4. unknown confidence / no redemption_frequency → terms_unknown --------


def test_unknown_confidence_terms_unknown_bucket():
    """Phase 22 #4: confidence=unknown + no redemption_frequency → advisory + terms_unknown."""
    pos = [_pos(liquidity_bucket="semi_liquid")]
    mgr = [_terms("mgr_a", redemption_frequency=None, confidence="unknown")]
    diag = compute_manager_terms_diagnostics(pos, mgr, as_of_date=_AS_OF)
    entry = diag.liquidity_horizon.entries[0]
    assert entry.effective_window_days is None
    assert diag.liquidity_horizon.by_horizon_bucket["terms_unknown"] == pytest.approx(1_000_000.0)
    assert any("unknown" in adv.lower() for adv in diag.liquidity_horizon.advisories)


# ---- 5. lockup in future → max(freq+notice, lockup_remaining) ---------------


def test_lockup_future_extends_window():
    """Phase 22 #5: lockup_end_date in future overrides freq+notice when larger."""
    # quarterly + 0 notice = 91 days; lockup ends 2027-03-31 = 365 days out
    lockup_date = date(2027, 3, 31)
    pos = [_pos(liquidity_bucket="semi_liquid")]
    mgr = [_terms("mgr_a", redemption_frequency="quarterly", lockup_end_date=lockup_date)]
    diag = compute_manager_terms_diagnostics(pos, mgr, as_of_date=_AS_OF)
    entry = diag.liquidity_horizon.entries[0]
    assert entry.effective_window_days == 365
    assert "lockup" in entry.flags


def test_lockup_future_no_override_when_freq_larger():
    """Phase 22 #5b: lockup shorter than freq+notice → freq+notice wins."""
    # annual + 30 notice = 395 days; lockup ends in 30 days
    lockup_date = date(2026, 4, 30)
    pos = [_pos(liquidity_bucket="semi_liquid")]
    mgr = [
        _terms("mgr_a", redemption_frequency="annual", notice_days=30, lockup_end_date=lockup_date)
    ]
    diag = compute_manager_terms_diagnostics(pos, mgr, as_of_date=_AS_OF)
    entry = diag.liquidity_horizon.entries[0]
    assert entry.effective_window_days == 395  # max(365+30, 30) = 395


# ---- 6. lockup in past → no offset ------------------------------------------


def test_lockup_past_no_offset():
    """Phase 22 #6: lockup_end_date in past → no lockup extension."""
    lockup_date = date(2025, 12, 31)  # before as_of_date
    pos = [_pos(liquidity_bucket="semi_liquid")]
    mgr = [
        _terms(
            "mgr_a", redemption_frequency="quarterly", notice_days=0, lockup_end_date=lockup_date
        )
    ]
    diag = compute_manager_terms_diagnostics(pos, mgr, as_of_date=_AS_OF)
    entry = diag.liquidity_horizon.entries[0]
    assert entry.effective_window_days == 91
    assert "lockup" not in entry.flags


# ---- 7. gate + side_pocket flags -------------------------------------------


def test_gate_and_side_pocket_flags():
    """Phase 22 #7: gate_pct > 0 + side_pocket=True → both flags in entry."""
    pos = [_pos(liquidity_bucket="semi_liquid")]
    mgr = [_terms("mgr_a", redemption_frequency="quarterly", gate_pct=0.25, side_pocket=True)]
    diag = compute_manager_terms_diagnostics(pos, mgr, as_of_date=_AS_OF)
    entry = diag.liquidity_horizon.entries[0]
    assert "gate" in entry.flags
    assert "side_pocket" in entry.flags
    # Window is still computed (flags are non-blocking)
    assert entry.effective_window_days == 91


# ---- 8. fee drag nav basis --------------------------------------------------


def test_fee_drag_nav_basis():
    """Phase 22 #8: fee_basis='nav', 150 bps on $1m → drag = $15k."""
    pos = [_pos(liquidity_bucket="illiquid", market_value_usd=1_000_000.0)]
    mgr = [
        _terms(
            "mgr_a",
            redemption_frequency=None,
            fee_basis="nav",
            management_fee_bps=150,
            confidence="unknown",
        )
    ]
    diag = compute_manager_terms_diagnostics(pos, mgr, as_of_date=_AS_OF)
    entry = diag.fee_exposure.entries[0]
    assert entry.annual_fee_drag_usd == pytest.approx(15_000.0)
    assert diag.fee_exposure.total_fee_drag_usd == pytest.approx(15_000.0)
    assert diag.fee_exposure.total_estimable_nav_usd == pytest.approx(1_000_000.0)


# ---- 9. fee drag committed basis -------------------------------------------


def test_fee_drag_committed_basis_advisory():
    """Phase 22 #9: fee_basis='committed' → drag=None + advisory emitted."""
    pos = [_pos(liquidity_bucket="illiquid")]
    mgr = [
        _terms(
            "mgr_a",
            redemption_frequency=None,
            fee_basis="committed",
            management_fee_bps=150,
            confidence="unknown",
        )
    ]
    diag = compute_manager_terms_diagnostics(pos, mgr, as_of_date=_AS_OF)
    entry = diag.fee_exposure.entries[0]
    assert entry.annual_fee_drag_usd is None
    assert any("committed" in adv for adv in diag.fee_exposure.advisories)
    assert diag.fee_exposure.total_fee_drag_usd == pytest.approx(0.0)


# ---- 10. carry advisory -----------------------------------------------------


def test_carry_advisory_with_hurdle():
    """Phase 22 #10a: carry_pct + hurdle_rate → carry advisory text."""
    pos = [_pos(liquidity_bucket="illiquid")]
    mgr = [
        _terms(
            "mgr_a",
            redemption_frequency=None,
            fee_basis="nav",
            management_fee_bps=0,
            carry_pct=0.20,
            hurdle_rate=0.08,
            confidence="unknown",
        )
    ]
    diag = compute_manager_terms_diagnostics(pos, mgr, as_of_date=_AS_OF)
    entry = diag.fee_exposure.entries[0]
    assert entry.carry_advisory is not None
    assert "20%" in entry.carry_advisory
    assert "8.0%" in entry.carry_advisory


def test_carry_advisory_no_hurdle():
    """Phase 22 #10b: carry_pct with hurdle_rate=None → 'hurdle unknown' text."""
    pos = [_pos(liquidity_bucket="illiquid")]
    mgr = [
        _terms(
            "mgr_a",
            redemption_frequency=None,
            fee_basis="unknown",
            carry_pct=0.20,
            hurdle_rate=None,
            confidence="unknown",
        )
    ]
    diag = compute_manager_terms_diagnostics(pos, mgr, as_of_date=_AS_OF)
    entry = diag.fee_exposure.entries[0]
    assert entry.carry_advisory is not None
    assert "hurdle unknown" in entry.carry_advisory.lower()


# ---- 11. capital-call notice aggregation ------------------------------------


def test_capital_call_notice_aggregation():
    """Phase 22 #11: unfunded split by known / unknown notice."""
    pos = [
        _pos(manager_id="pe_a", liquidity_bucket="illiquid", unfunded_commitment_usd=500_000.0),
        _pos(manager_id="pe_b", liquidity_bucket="illiquid", unfunded_commitment_usd=300_000.0),
    ]
    mgr = [
        _terms("pe_a", redemption_frequency=None, capital_call_notice_days=30),
        _terms("pe_b", redemption_frequency=None, capital_call_notice_days=None),
    ]
    diag = compute_manager_terms_diagnostics(pos, mgr, as_of_date=_AS_OF)
    n = diag.capital_call_notice
    assert n.total_unfunded_with_known_notice == pytest.approx(500_000.0)
    assert n.total_unfunded_notice_unknown == pytest.approx(300_000.0)
    assert n.min_notice_days == 30
    assert n.max_notice_days == 30
    assert len(n.entries) == 1  # only pe_a has capital_call_notice_days set
    assert any("no documented" in adv.lower() for adv in n.advisories)


# ---- 12. default byte-stable ------------------------------------------------


def test_empty_inputs_no_crash():
    """Phase 22 #12a: empty positions + empty manager_terms → valid empty result."""
    diag = compute_manager_terms_diagnostics([], [], as_of_date=_AS_OF)
    assert diag.total_positions == 0
    assert diag.total_nav_usd == 0.0
    assert diag.managers_with_terms == 0
    assert diag.managers_without_terms == 0
    assert diag.liquidity_horizon.total_semi_liquid_nav == 0.0
    assert diag.fee_exposure.total_fee_drag_usd == 0.0
    assert diag.capital_call_notice.min_notice_days is None


def test_manager_terms_diag_none_when_position_ingestion_none():
    """Phase 22 #12b: manager_terms_diag=None when position_ingestion=None."""
    from pathlib import Path

    from aa_model.integration.orchestrator import _build_ledger
    from aa_model.io.loaders import load_study_config

    config_path = Path(__file__).parents[1] / "configs" / "base.yaml"
    if not config_path.exists():
        pytest.skip("base.yaml fixture not available in this environment")
    cfg = load_study_config(config_path)
    assert cfg.position_ingestion is None

    result_tuple = _build_ledger(cfg, "test-run-p22")
    manager_terms_diag = result_tuple[11]  # 12th element (0-indexed)
    assert manager_terms_diag is None
