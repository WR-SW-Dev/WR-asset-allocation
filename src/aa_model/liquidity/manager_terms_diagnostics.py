"""Phase 22 — Manager terms consumer / diagnostic layer.

Activates ManagerTermsRecord fields that existed from Phase 15 but were
not meaningfully consumed. Phase 15's only consumer was notice_days for
the aggregate semi_liquid_earliest_notice_days advisory in coverage.py.
Phase 22 adds three per-manager diagnostic sub-modules.

Architecture
============

compute_manager_terms_diagnostics() is a pure function. No ledger reads,
no side effects. Same inputs → same output byte-for-byte.

Three sub-diagnostics
---------------------
LiquidityHorizonDiagnostics  — effective redemption window, bucketed by horizon
FeeExposureDiagnostics       — annual fee drag estimate and carry advisory
CapitalCallNoticeDiagnostics — ops-planning notice metadata for PE-class funds

Scope boundary (enforced here)
==============================
* Semi-liquid remains advisory-only: effective_window_days is never used
  to reclassify positions as liquid breach coverage.
* Fee drag is advisory only: total_fee_drag_usd never feeds coverage ratios.
* capital_call_notice_days is ops-planning metadata: does not modify the
  Phase 20/21 reconciliation gate outcome.
* No legal/tax/entity-governance inference at any point.
* No Monte Carlo.

Tightening 1 (design-lock): tier_overrides is threaded from the orchestrator
so that override-sensitive buckets (e.g. stabilized RE reclassified to
semi_liquid) are handled consistently with coverage.py.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from aa_model.ingestion.liquidity_mapping import resolve_phase12_tier
from aa_model.ingestion.schemas_position import ManagerTermsRecord, PositionRecord

_FREQ_BASE_DAYS: dict[str, int] = {
    "daily": 0,
    "monthly": 31,
    "quarterly": 91,
    "semi_annual": 182,
    "annual": 365,
    # "none" → None handled explicitly (not redeemable on demand)
}

_HORIZON_BUCKETS: tuple[str, ...] = (
    "within_90d",
    "90d_to_1y",
    "1y_to_3y",
    "beyond_3y",
    "terms_unknown",
)


# ---- internal helpers -------------------------------------------------------


def _effective_window_days(
    terms: ManagerTermsRecord,
    as_of_date: date,
) -> int | None:
    """Effective redemption window in days from as_of_date.

    Returns None when redemption is not available on demand
    (frequency="none") or cannot be determined (None).
    Lockup offset takes max(freq+notice, lockup_remaining) when
    lockup_end_date is strictly in the future.
    """
    freq = terms.redemption_frequency
    if freq is None or freq == "none":
        return None
    base = _FREQ_BASE_DAYS.get(freq)
    if base is None:
        return None  # unknown literal; defensive
    window = base + (terms.notice_days or 0)
    if terms.lockup_end_date is not None and terms.lockup_end_date > as_of_date:
        lockup_days = (terms.lockup_end_date - as_of_date).days
        window = max(window, lockup_days)
    return window


def _horizon_bucket(window_days: int | None) -> str:
    if window_days is None:
        return "terms_unknown"
    if window_days <= 90:
        return "within_90d"
    if window_days <= 365:
        return "90d_to_1y"
    if window_days <= 1095:
        return "1y_to_3y"
    return "beyond_3y"


def _entry_flags(terms: ManagerTermsRecord, as_of_date: date) -> tuple[str, ...]:
    flags: list[str] = []
    if terms.gate_pct is not None and terms.gate_pct > 0.0:
        flags.append("gate")
    if terms.side_pocket:
        flags.append("side_pocket")
    if terms.lockup_end_date is not None and terms.lockup_end_date > as_of_date:
        flags.append("lockup")
    return tuple(flags)


# ---- data structures -------------------------------------------------------


@dataclass(frozen=True)
class LiquidityHorizonEntry:
    manager_id: str
    nav_usd: float
    effective_window_days: int | None
    redemption_frequency: str | None
    notice_days: int | None
    flags: tuple[str, ...]  # "gate", "side_pocket", "lockup"


@dataclass(frozen=True)
class LiquidityHorizonDiagnostics:
    entries: tuple[LiquidityHorizonEntry, ...]
    by_horizon_bucket: dict[str, float]
    total_semi_liquid_nav: float
    advisories: list[str]


@dataclass(frozen=True)
class FeeExposureEntry:
    manager_id: str
    nav_usd: float
    fee_basis: str
    management_fee_bps: int | None
    annual_fee_drag_usd: float | None
    carry_pct: float | None
    hurdle_rate: float | None
    carry_advisory: str | None


@dataclass(frozen=True)
class FeeExposureDiagnostics:
    entries: tuple[FeeExposureEntry, ...]
    total_estimable_nav_usd: float
    total_fee_drag_usd: float
    fee_unknown_nav_usd: float
    advisories: list[str]


@dataclass(frozen=True)
class CapitalCallNoticeEntry:
    manager_id: str
    nav_usd: float
    unfunded_commitment_usd: float
    capital_call_notice_days: int | None


@dataclass(frozen=True)
class CapitalCallNoticeDiagnostics:
    entries: tuple[CapitalCallNoticeEntry, ...]
    total_unfunded_with_known_notice: float
    total_unfunded_notice_unknown: float
    min_notice_days: int | None
    max_notice_days: int | None
    advisories: list[str]


@dataclass(frozen=True)
class ManagerTermsDiagnostics:
    total_positions: int
    total_nav_usd: float
    managers_with_terms: int  # confidence ≠ "unknown"
    managers_without_terms: int  # confidence == "unknown"
    liquidity_horizon: LiquidityHorizonDiagnostics
    fee_exposure: FeeExposureDiagnostics
    capital_call_notice: CapitalCallNoticeDiagnostics
    coverage_advisories: list[str]


# ---- entry point -----------------------------------------------------------


def compute_manager_terms_diagnostics(
    positions: list[PositionRecord],
    manager_terms: list[ManagerTermsRecord],
    *,
    as_of_date: date,
    tier_overrides: dict[str, str] | None = None,
) -> ManagerTermsDiagnostics:
    """Compute manager terms diagnostics from position records and terms.

    Pure function. No side effects.

    Parameters
    ----------
    positions:
        PositionRecord list from Phase 15 ingestion or synthetic config.
    manager_terms:
        ManagerTermsRecord list from PositionManifestConfig.manager_terms.
    as_of_date:
        Valuation date from PositionManifestConfig.as_of_date.
    tier_overrides:
        Phase 15 → Phase 12 tier overrides from
        PositionManifestConfig.liquidity_tier_overrides. Threading this
        ensures override-sensitive buckets are classified consistently
        with compute_liquidity_coverage (tightening 1).
    """
    manager_by_id: dict[str, ManagerTermsRecord] = {m.manager_id: m for m in manager_terms}

    total_nav = sum(p.market_value_usd for p in positions)
    total_positions = len(positions)
    managers_with_terms = sum(1 for m in manager_terms if m.confidence != "unknown")
    managers_without_terms = len(manager_terms) - managers_with_terms

    # Aggregate per-manager: NAV, unfunded commitment, and semi-liquid NAV.
    # Positions without manager_id cannot be matched to terms; excluded with
    # an advisory.
    nav_by_manager: dict[str, float] = {}
    unfunded_by_manager: dict[str, float] = {}
    semi_liquid_nav_by_manager: dict[str, float] = {}

    for pos in positions:
        mid = pos.manager_id
        if mid is None:
            continue
        nav_by_manager[mid] = nav_by_manager.get(mid, 0.0) + pos.market_value_usd
        if pos.unfunded_commitment_usd is not None:
            unfunded_by_manager[mid] = (
                unfunded_by_manager.get(mid, 0.0) + pos.unfunded_commitment_usd
            )
        tier = resolve_phase12_tier(pos.liquidity_bucket, tier_overrides)
        if tier == "semi_liquid":
            semi_liquid_nav_by_manager[mid] = (
                semi_liquid_nav_by_manager.get(mid, 0.0) + pos.market_value_usd
            )

    # ---- 1. Liquidity horizon -----------------------------------------------

    horizon_entries: list[LiquidityHorizonEntry] = []
    bucket_nav: dict[str, float] = {b: 0.0 for b in _HORIZON_BUCKETS}
    terms_unknown_count = 0
    horizon_advisories: list[str] = []

    for mid, nav in semi_liquid_nav_by_manager.items():
        terms = manager_by_id.get(mid)
        if terms is None:
            window: int | None = None
            freq: str | None = None
            notice: int | None = None
            flags: tuple[str, ...] = ()
        else:
            window = _effective_window_days(terms, as_of_date)
            freq = terms.redemption_frequency
            notice = terms.notice_days
            flags = _entry_flags(terms, as_of_date)

        bucket = _horizon_bucket(window)
        bucket_nav[bucket] = bucket_nav[bucket] + nav
        if window is None:
            terms_unknown_count += 1

        horizon_entries.append(
            LiquidityHorizonEntry(
                manager_id=mid,
                nav_usd=nav,
                effective_window_days=window,
                redemption_frequency=freq,
                notice_days=notice,
                flags=flags,
            )
        )

    if terms_unknown_count > 0:
        horizon_advisories.append(
            f"{terms_unknown_count} semi-liquid manager(s) with unknown redemption terms "
            f"— horizon not estimable"
        )

    liquidity_horizon = LiquidityHorizonDiagnostics(
        entries=tuple(horizon_entries),
        by_horizon_bucket=dict(bucket_nav),
        total_semi_liquid_nav=sum(semi_liquid_nav_by_manager.values()),
        advisories=horizon_advisories,
    )

    # ---- 2. Fee exposure ----------------------------------------------------

    fee_entries: list[FeeExposureEntry] = []
    total_estimable_nav = 0.0
    total_fee_drag = 0.0
    fee_unknown_nav = 0.0
    fee_advisories: list[str] = []

    for mid, nav in nav_by_manager.items():
        terms = manager_by_id.get(mid)
        if terms is None:
            fee_unknown_nav += nav
            fee_entries.append(
                FeeExposureEntry(
                    manager_id=mid,
                    nav_usd=nav,
                    fee_basis="unknown",
                    management_fee_bps=None,
                    annual_fee_drag_usd=None,
                    carry_pct=None,
                    hurdle_rate=None,
                    carry_advisory=None,
                )
            )
            continue

        basis = terms.fee_basis
        bps = terms.management_fee_bps
        carry = terms.carry_pct
        hurdle = terms.hurdle_rate

        drag: float | None
        if basis == "nav" and bps is not None:
            drag = nav * bps / 10_000.0
            total_estimable_nav += nav
            total_fee_drag += drag
        elif basis in ("committed", "invested"):
            drag = None
            fee_advisories.append(
                f"{mid}: management fee on {basis!r} basis — cannot estimate from NAV alone"
            )
        else:
            drag = None
            fee_unknown_nav += nav

        carry_advisory: str | None = None
        if carry is not None and carry > 0.0:
            if hurdle is not None:
                carry_advisory = f"carry {carry:.0%} above {hurdle:.1%} hurdle"
            else:
                carry_advisory = f"carry {carry:.0%} (hurdle unknown)"

        fee_entries.append(
            FeeExposureEntry(
                manager_id=mid,
                nav_usd=nav,
                fee_basis=basis,
                management_fee_bps=bps,
                annual_fee_drag_usd=drag,
                carry_pct=carry,
                hurdle_rate=hurdle,
                carry_advisory=carry_advisory,
            )
        )

    fee_exposure = FeeExposureDiagnostics(
        entries=tuple(fee_entries),
        total_estimable_nav_usd=total_estimable_nav,
        total_fee_drag_usd=total_fee_drag,
        fee_unknown_nav_usd=fee_unknown_nav,
        advisories=fee_advisories,
    )

    # ---- 3. Capital-call notice ---------------------------------------------

    notice_entries: list[CapitalCallNoticeEntry] = []
    total_unfunded_known = 0.0
    total_unfunded_unknown = 0.0
    notice_days_list: list[int] = []
    managers_missing_notice = 0
    notice_advisories: list[str] = []

    # Entries come from managers with capital_call_notice_days set.
    for mid, terms in manager_by_id.items():
        if terms.capital_call_notice_days is None:
            continue
        nav = nav_by_manager.get(mid, 0.0)
        unfunded = unfunded_by_manager.get(mid, 0.0)
        notice_entries.append(
            CapitalCallNoticeEntry(
                manager_id=mid,
                nav_usd=nav,
                unfunded_commitment_usd=unfunded,
                capital_call_notice_days=terms.capital_call_notice_days,
            )
        )
        total_unfunded_known += unfunded
        notice_days_list.append(terms.capital_call_notice_days)

    # Advisory: managers with unfunded but no documented notice days.
    for mid, unfunded in unfunded_by_manager.items():
        if unfunded <= 0.0:
            continue
        terms = manager_by_id.get(mid)
        if terms is None or terms.capital_call_notice_days is None:
            total_unfunded_unknown += unfunded
            managers_missing_notice += 1

    if managers_missing_notice > 0:
        notice_advisories.append(
            f"{managers_missing_notice} manager(s) with unfunded commitments have no "
            f"documented capital_call_notice_days"
        )

    capital_call_notice = CapitalCallNoticeDiagnostics(
        entries=tuple(notice_entries),
        total_unfunded_with_known_notice=total_unfunded_known,
        total_unfunded_notice_unknown=total_unfunded_unknown,
        min_notice_days=min(notice_days_list) if notice_days_list else None,
        max_notice_days=max(notice_days_list) if notice_days_list else None,
        advisories=notice_advisories,
    )

    # ---- top-level coverage advisories --------------------------------------

    coverage_advisories: list[str] = []
    unmatched = sum(1 for p in positions if p.manager_id is None)
    if unmatched > 0:
        coverage_advisories.append(
            f"{unmatched} position(s) have no manager_id — "
            f"excluded from all manager terms diagnostics"
        )

    return ManagerTermsDiagnostics(
        total_positions=total_positions,
        total_nav_usd=total_nav,
        managers_with_terms=managers_with_terms,
        managers_without_terms=managers_without_terms,
        liquidity_horizon=liquidity_horizon,
        fee_exposure=fee_exposure,
        capital_call_notice=capital_call_notice,
        coverage_advisories=coverage_advisories,
    )


# ---- report rendering -------------------------------------------------------


def _fmt_m(usd: float) -> str:
    """Format USD as millions with one decimal, e.g. '$12.5m'."""
    return f"${usd / 1_000_000:.1f}m"


def _fmt_k(usd: float) -> str:
    return f"${usd / 1_000:.1f}k"


def render_manager_terms_section(diag: ManagerTermsDiagnostics) -> str:
    """Render the ## Manager terms report section as a markdown string."""
    lines: list[str] = []
    lines.append("## Manager terms (Phase 22, advisory)")
    lines.append("")
    lines.append(
        f"Coverage: {diag.total_positions} positions, {_fmt_m(diag.total_nav_usd)} total NAV "
        f"| {diag.managers_with_terms} managers with terms, "
        f"{diag.managers_without_terms} with confidence=unknown"
    )
    if diag.coverage_advisories:
        for adv in diag.coverage_advisories:
            lines.append(f"- {adv}")
    lines.append("")

    # ---- Liquidity horizon --------------------------------------------------
    h = diag.liquidity_horizon
    semi_liq_count = len(h.entries)
    lines.append(
        f"### Liquidity horizon (semi-liquid, {semi_liq_count} manager(s), "
        f"{_fmt_m(h.total_semi_liquid_nav)})"
    )
    lines.append("")
    if h.entries:
        lines.append("| Manager | NAV | Window (days) | Flags |")
        lines.append("|---------|-----|---------------|-------|")
        for e in sorted(h.entries, key=lambda x: x.manager_id):
            window_str = (
                str(e.effective_window_days) if e.effective_window_days is not None else "—"
            )
            flags_str = ", ".join(e.flags) if e.flags else ""
            lines.append(f"| {e.manager_id} | {_fmt_m(e.nav_usd)} | {window_str} | {flags_str} |")
        lines.append("")
    bkts = h.by_horizon_bucket
    lines.append(
        "By bucket: "
        f"within_90d {_fmt_m(bkts.get('within_90d', 0.0))} · "
        f"90d_to_1y {_fmt_m(bkts.get('90d_to_1y', 0.0))} · "
        f"1y_to_3y {_fmt_m(bkts.get('1y_to_3y', 0.0))} · "
        f"beyond_3y {_fmt_m(bkts.get('beyond_3y', 0.0))} · "
        f"terms_unknown {_fmt_m(bkts.get('terms_unknown', 0.0))}"
    )
    if h.advisories:
        for adv in h.advisories:
            lines.append(f"- ADVISORY: {adv}")
    lines.append("")

    # ---- Fee exposure -------------------------------------------------------
    f_ = diag.fee_exposure
    lines.append("### Fee exposure (annual drag estimate)")
    lines.append("")
    if f_.entries:
        lines.append("| Manager | NAV | Fee basis | Bps | Annual drag | Carry |")
        lines.append("|---------|-----|-----------|-----|-------------|-------|")
        for e in sorted(f_.entries, key=lambda x: x.manager_id):
            drag_str = _fmt_k(e.annual_fee_drag_usd) if e.annual_fee_drag_usd is not None else "—"
            bps_str = str(e.management_fee_bps) if e.management_fee_bps is not None else "—"
            carry_str = e.carry_advisory or ""
            lines.append(
                f"| {e.manager_id} | {_fmt_m(e.nav_usd)} | {e.fee_basis} "
                f"| {bps_str} | {drag_str} | {carry_str} |"
            )
        lines.append("")
    lines.append(
        f"Estimable drag: {_fmt_k(f_.total_fee_drag_usd)}/yr on "
        f"{_fmt_m(f_.total_estimable_nav_usd)} NAV  |  "
        f"Unknown basis: {_fmt_m(f_.fee_unknown_nav_usd)}"
    )
    if f_.advisories:
        for adv in f_.advisories:
            lines.append(f"- ADVISORY: {adv}")
    lines.append("")

    # ---- Capital-call notice ------------------------------------------------
    n = diag.capital_call_notice
    lines.append("### Capital-call notice (ops planning)")
    lines.append("")
    if n.entries:
        lines.append("| Manager | NAV | Unfunded | Notice (days) |")
        lines.append("|---------|-----|----------|---------------|")
        for e in sorted(n.entries, key=lambda x: x.manager_id):
            notice_str = (
                str(e.capital_call_notice_days) if e.capital_call_notice_days is not None else "—"
            )
            lines.append(
                f"| {e.manager_id} | {_fmt_m(e.nav_usd)} "
                f"| {_fmt_m(e.unfunded_commitment_usd)} | {notice_str} |"
            )
        lines.append("")
    notice_range = (
        f"{n.min_notice_days}–{n.max_notice_days} days" if n.min_notice_days is not None else "n/a"
    )
    lines.append(
        f"Known notice: {_fmt_m(n.total_unfunded_with_known_notice)} unfunded  |  "
        f"Missing notice: {_fmt_m(n.total_unfunded_notice_unknown)} unfunded  |  "
        f"Range: {notice_range}"
    )
    if n.advisories:
        for adv in n.advisories:
            lines.append(f"- ADVISORY: {adv}")
    lines.append("")
    lines.append(
        "_ADVISORY: values are from manifest terms records, not from verified fund documents._"
    )

    return "\n".join(lines)
