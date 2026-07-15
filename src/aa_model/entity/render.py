"""Phase 24 — study renderers (the deliverable layer).

Turn a validated `EntityFixture` (+ optional `EntityPolicyConfig`) into the
Wake Robin study deliverable, in two forms that read from the same lenses:

- `render_study_markdown()` — a markdown report (the study, section per lens).
- `export_study_xlsx()` — a fresh workbook mirroring the study tabs. It never
  opens or mutates any source workbook; it writes a new file.

Both are deterministic: every value comes from the fixture via the lenses;
no wall-clock reads. Sections are emitted only when the fixture carries the
data. Money is formatted for display only — the underlying reconciliation is
`Decimal`-exact in the lenses.
"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

from aa_model.entity.fixture import pe_exposure_totals, segment_totals
from aa_model.entity.lenses import (
    allocation_vs_target_lens,
    balance_sheet_lens,
    burn_rate_lens,
    cash_flow_lens,
    custodian_reconciliation_lens,
    holdings_detail_lens,
    liquidity_lens,
    liquidity_projection_lens,
    purpose_allocation_lens,
)
from aa_model.entity.schemas import EntityFixture, EntityPolicyConfig, EntityPurposePolicyConfig

_DASH = "—"


def _usd(v: Decimal | None) -> str:
    if v is None:
        return _DASH
    return f"${v:,.2f}"


def _pct(frac: Decimal | None) -> str:
    if frac is None:
        return _DASH
    return f"{frac * 100:,.1f}%"


def _yrs(v: Decimal | None) -> str:
    return _DASH if v is None else f"{v:,.1f} yr"


# ---- markdown --------------------------------------------------------------


def render_study_markdown(
    fixture: EntityFixture,
    *,
    policy: EntityPolicyConfig | None = None,
    purpose_policy: EntityPurposePolicyConfig | None = None,
) -> str:
    """Render the study as markdown. Sections present only when the fixture
    carries the underlying data; allocation-vs-target requires `policy`."""
    L: list[str] = []
    L.append(f"# Asset Allocation Study — {fixture.entity_id}")
    L.append(f"As of {fixture.as_of_date.isoformat()} · fixture `{fixture.fixture_version}` · USD")

    # Summary — three lenses at a glance
    bs = balance_sheet_lens(fixture)
    L.append("\n## Summary — portfolio at a glance")
    L.append(f"- Total balance-sheet NAV: **{_usd(bs.total_nav_usd)}**")
    L.append(
        f"- Investable financial assets: **{_usd(bs.investable_usd)}** "
        f"({_pct(bs.investable_pct_of_nav)} of NAV)"
    )
    L.append(f"- Personal-use / structural NAV: {_usd(bs.structural_usd)}")

    # Balance-sheet segmentation
    L.append("\n## Balance-sheet segmentation")
    L.append("| Segment | Amount |")
    L.append("|---|---:|")
    for cls, amt in bs.by_policy_class_usd.items():
        L.append(f"| investable · {cls} | {_usd(amt)} |")
    for seg, amt in bs.by_segment_usd.items():
        if seg != "investable":
            L.append(f"| {seg} | {_usd(amt)} |")
    L.append(f"| **Total NAV** | **{_usd(bs.total_nav_usd)}** |")

    # Allocation vs target
    if policy is not None:
        a = allocation_vs_target_lens(fixture, policy)
        L.append("\n## Allocation vs. strategic target (investable)")
        L.append("| Class | Current | Current % | Target % | Gap (pp) | $ to target | Action |")
        L.append("|---|---:|---:|---:|---:|---:|---|")
        for r in a.rows:
            L.append(
                f"| {r.policy_class} | {_usd(r.current_usd)} | {_pct(r.current_pct)} | "
                f"{_pct(r.target_pct)} | {r.gap_pp:,.1f} | {_usd(r.to_target_usd)} | {r.action} |"
            )

    # Purpose allocation (goals-based)
    if purpose_policy is not None:
        pa = purpose_allocation_lens(fixture, purpose_policy)
        L.append("\n## Purpose allocation (goals-based)")
        L.append(
            "| Purpose | Current | Current % | Target % | Band | Variance (pp) "
            "| $ to target | Status |"
        )
        L.append("|---|---:|---:|---:|---:|---:|---:|---|")
        for r in pa.rows:
            band = f"{_pct(r.min_pct)}–{_pct(r.max_pct)}"
            L.append(
                f"| {r.purpose} | {_usd(r.current_usd)} | {_pct(r.current_pct)} | "
                f"{_pct(r.target_pct)} | {band} | {r.variance_pp:,.1f} | "
                f"{_usd(r.to_target_usd)} | {r.status} |"
            )

    # Holdings detail
    if fixture.holdings:
        hd = holdings_detail_lens(fixture)
        L.append("\n## Holdings detail")
        for g in hd.groups:
            if not g.holdings:
                continue
            recon = "reconciles" if g.reconciles else f"Δ {_usd(g.delta_usd)}"
            L.append(
                f"### {g.policy_class} — {len(g.holdings)} position(s), "
                f"{_usd(g.subtotal_usd)} ({recon})"
            )

    # PE & alternatives
    if fixture.pe_exposure:
        p = pe_exposure_totals(fixture)
        L.append("\n## Private equity & alternatives")
        L.append(f"- Funds: {p.fund_count}")
        L.append(f"- Commitment: {_usd(p.commitment_usd)}")
        L.append(f"- Called to date: {_usd(p.called_to_date_usd)}")
        L.append(f"- Distributed: {_usd(p.distributed_to_date_usd)}")
        L.append(f"- NAV: {_usd(p.nav_usd)}")
        L.append(f"- Unfunded (floored): {_usd(p.unfunded_usd)}")

    # Liquidity lens
    seg_inv = segment_totals(fixture).investable_usd
    if seg_inv and any(s.segment == "investable" for s in fixture.segments):
        liq = liquidity_lens(fixture)
        L.append("\n## Liquidity by redemption tier (investable)")
        L.append("| Tier | Amount | Share |")
        L.append("|---|---:|---:|")
        for tier, amt in liq.by_tier_usd.items():
            L.append(f"| {tier} | {_usd(amt)} | {_pct(liq.by_tier_pct[tier])} |")
        L.append(
            f"| **Liquid within 30 days** | **{_usd(liq.liquid_within_30d_usd)}** | "
            f"**{_pct(liq.liquid_within_30d_pct)}** |"
        )

    # Burn rate
    if fixture.burn_rate:
        b = burn_rate_lens(fixture)
        L.append("\n## Burn rate")
        L.append("| Year | Total | w/o taxes | w/o charitable |")
        L.append("|---|---:|---:|---:|")
        for y in b.years:
            L.append(
                f"| {y} | {_usd(b.total_by_year[y])} | "
                f"{_usd(b.without_taxes_by_year[y])} | {_usd(b.without_charitable_by_year[y])} |"
            )
        L.append(
            f"- Avg annual (w/o taxes): {_usd(b.avg_annual_without_taxes)}; "
            f"quarterly: {_usd(b.avg_quarterly_without_taxes)}; "
            f"lightest year: {b.lightest_year}"
        )

    # Cash flow / runway
    if fixture.cash_flow is not None:
        c = cash_flow_lens(fixture)
        L.append("\n## Cash flow & runway")
        L.append(
            f"- Net annual draw: {_usd(c.net_annual_draw_usd)} "
            f"(monthly living {_usd(c.monthly_living_usd)})"
        )
        L.append(
            f"- Policy target cash: {_usd(c.policy_target_cash_usd)}; "
            f"overweight: {_usd(c.cash_overweight_usd)}"
        )
        L.append(
            f"- Reserve: {_usd(c.reserve_amount_usd)}; "
            f"deployable after reserve: {_usd(c.deployable_after_reserve_usd)}"
        )
        L.append(
            f"- Runway on current cash: {_yrs(c.runway_current_years)}; "
            f"on policy cash: {_yrs(c.runway_policy_years)}"
        )
        if c.scenario_enabled:
            L.append(
                f"- Scenario draw: {_usd(c.net_annual_draw_scenario_usd)}; "
                f"runway: {_yrs(c.runway_current_scenario_years)}"
            )

    # Liquidity projection
    if fixture.liquidity_projection:
        lp = liquidity_projection_lens(fixture)
        L.append("\n## Liquidity projection")
        L.append(f"- {lp.quarters} quarters ({lp.period_first} … {lp.period_last})")
        L.append(f"- Begins {_usd(lp.beginning_usd)} → ends {_usd(lp.ending_usd)}")
        L.append(
            f"- Min ending balance: {_usd(lp.min_ending_usd)} at {lp.min_ending_period}; "
            f"runway breach: {'YES' if lp.goes_negative else 'no'}"
        )

    # Custodian reconciliation
    if fixture.custodian_reconciliations:
        L.append("\n## Custodian reconciliation")
        for cr in custodian_reconciliation_lens(fixture):
            status = "pending statement" if cr.statement_pending else "statement loaded"
            recon = "reconciles" if cr.holdings_reconciles else f"Δ {_usd(cr.holdings_delta_usd)}"
            L.append(
                f"- {cr.account_id}: ending {_usd(cr.ending_value_usd)} · "
                f"holdings {_usd(cr.holdings_total_usd)} ({recon}) · {status}"
            )

    # Notes
    L.append("\n## Notes & sources")
    L.append(
        "- NAV ≠ liquidity: personal-use / structural assets are excluded "
        "from the investable base."
    )
    L.append("- Figures are Decimal-exact in the model; displayed values are formatted.")
    return "\n".join(L) + "\n"


# ---- xlsx ------------------------------------------------------------------


def export_study_xlsx(
    fixture: EntityFixture,
    path: str | Path,
    *,
    policy: EntityPolicyConfig | None = None,
    purpose_policy: EntityPurposePolicyConfig | None = None,
) -> Path:
    """Write the study to a fresh .xlsx (one sheet per section). Never opens
    or mutates any source workbook. Returns the written path."""
    import openpyxl  # local import keeps openpyxl optional for markdown-only use

    wb = openpyxl.Workbook()
    wb.remove(wb.active)  # drop the default sheet; we add our own

    def _sheet(name: str, header: list[str], rows: list[list]) -> None:
        ws = wb.create_sheet(title=name[:31])
        ws.append(header)
        for r in rows:
            ws.append(r)

    def _f(v: Decimal | None) -> float | str:
        return "" if v is None else float(v)

    bs = balance_sheet_lens(fixture)
    _sheet(
        "Summary",
        ["Lens", "Value"],
        [
            ["Total balance-sheet NAV", _f(bs.total_nav_usd)],
            ["Investable financial assets", _f(bs.investable_usd)],
            ["Investable % of NAV", _f(bs.investable_pct_of_nav)],
            ["Personal-use / structural NAV", _f(bs.structural_usd)],
        ],
    )
    _sheet(
        "Balance Sheet",
        ["Segment", "Amount"],
        [[f"investable · {c}", _f(a)] for c, a in bs.by_policy_class_usd.items()]
        + [[s, _f(a)] for s, a in bs.by_segment_usd.items() if s != "investable"]
        + [["Total NAV", _f(bs.total_nav_usd)]],
    )

    if policy is not None:
        a = allocation_vs_target_lens(fixture, policy)
        _sheet(
            "Allocation vs Target",
            ["Class", "Current", "Current %", "Target %", "Gap (pp)", "$ to target", "Action"],
            [
                [
                    r.policy_class,
                    _f(r.current_usd),
                    _f(r.current_pct),
                    _f(r.target_pct),
                    _f(r.gap_pp),
                    _f(r.to_target_usd),
                    r.action,
                ]
                for r in a.rows
            ],
        )

    if purpose_policy is not None:
        pa = purpose_allocation_lens(fixture, purpose_policy)
        _sheet(
            "Purpose Allocation",
            [
                "Purpose",
                "Current",
                "Current %",
                "Target %",
                "Min %",
                "Max %",
                "Variance (pp)",
                "$ to target",
                "Status",
            ],
            [
                [
                    r.purpose,
                    _f(r.current_usd),
                    _f(r.current_pct),
                    _f(r.target_pct),
                    _f(r.min_pct),
                    _f(r.max_pct),
                    _f(r.variance_pp),
                    _f(r.to_target_usd),
                    r.status,
                ]
                for r in pa.rows
            ],
        )

    if fixture.holdings:
        hd = holdings_detail_lens(fixture)
        rows = []
        for g in hd.groups:
            for h in g.holdings:
                rows.append(
                    [
                        g.policy_class,
                        h.holding_key,
                        h.asset_class,
                        _f(h.market_value_usd),
                        h.liquidity_tier or "",
                    ]
                )
        _sheet("Holdings", ["Class", "Holding", "Asset class", "Market value", "Tier"], rows)

    if fixture.pe_exposure:
        p = pe_exposure_totals(fixture)
        _sheet(
            "PE & Alternatives",
            ["Metric", "Value"],
            [
                ["Fund count", p.fund_count],
                ["Commitment", _f(p.commitment_usd)],
                ["Called to date", _f(p.called_to_date_usd)],
                ["Distributed", _f(p.distributed_to_date_usd)],
                ["NAV", _f(p.nav_usd)],
                ["Unfunded (floored)", _f(p.unfunded_usd)],
            ],
        )

    if any(s.segment == "investable" for s in fixture.segments):
        liq = liquidity_lens(fixture)
        _sheet(
            "Liquidity",
            ["Tier", "Amount", "Share"],
            [[t, _f(amt), _f(liq.by_tier_pct[t])] for t, amt in liq.by_tier_usd.items()]
            + [["Liquid within 30d", _f(liq.liquid_within_30d_usd), _f(liq.liquid_within_30d_pct)]],
        )

    if fixture.burn_rate:
        b = burn_rate_lens(fixture)
        _sheet(
            "Burn Rate",
            ["Year", "Total", "w/o taxes", "w/o charitable"],
            [
                [
                    y,
                    _f(b.total_by_year[y]),
                    _f(b.without_taxes_by_year[y]),
                    _f(b.without_charitable_by_year[y]),
                ]
                for y in b.years
            ],
        )

    if fixture.cash_flow is not None:
        c = cash_flow_lens(fixture)
        _sheet(
            "Cash Flow",
            ["Metric", "Value"],
            [
                ["Net annual draw", _f(c.net_annual_draw_usd)],
                ["Monthly living", _f(c.monthly_living_usd)],
                ["Policy target cash", _f(c.policy_target_cash_usd)],
                ["Cash overweight", _f(c.cash_overweight_usd)],
                ["Reserve amount", _f(c.reserve_amount_usd)],
                ["Deployable after reserve", _f(c.deployable_after_reserve_usd)],
                ["Runway current (yrs)", _f(c.runway_current_years)],
                ["Runway policy (yrs)", _f(c.runway_policy_years)],
            ],
        )

    if fixture.liquidity_projection:
        lp = liquidity_projection_lens(fixture)
        _sheet("Liquidity Projection", ["Period", "Ending"], [[p, _f(e)] for p, e in lp.trajectory])

    if fixture.custodian_reconciliations:
        rows = []
        for cr in custodian_reconciliation_lens(fixture):
            rows.append(
                [
                    cr.account_id,
                    _f(cr.ending_value_usd),
                    _f(cr.holdings_total_usd),
                    cr.holdings_reconciles,
                    cr.statement_pending,
                ]
            )
        _sheet(
            "Custodian Recon",
            ["Account", "Ending value", "Holdings total", "Reconciles", "Pending"],
            rows,
        )

    _sheet(
        "Notes",
        ["Note"],
        [
            ["NAV != liquidity: personal-use / structural excluded from investable base."],
            ["Values are Decimal-exact in the model; this export is a display rendering."],
        ],
    )

    out = Path(path)
    wb.save(out)
    return out
