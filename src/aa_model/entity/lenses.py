"""Phase 24 — study lens reducers over an entity fixture (sub-step 2).

Deterministic reducers that turn an `EntityFixture` (+ its `EntityPolicyConfig`)
into the study's core allocation lenses:

- **Balance-sheet lens** — the three-lens "at a glance": total NAV, investable
  base, and the investable share of NAV (NAV ≠ liquidity).
- **Allocation-vs-target lens** — per policy class: current $, current %,
  target %, gap (percentage points), $-to-target, and rebalancing direction.
- **Liquidity lens** — investable portfolio by redemption tier + the
  liquid-within-30-days share (daily + monthly).
- **Holdings-detail lens** — position-level holdings grouped by policy class,
  each subtotal reconciled to its investable balance-sheet segment.
- **Liquidity-projection lens** — the quarterly cash-flow projection reduced
  to its ending trajectory, min balance, and runway/breach signal.

All money is `Decimal`; all outputs are ordered deterministically (policy
classes in canonical order, tiers/quarters in a fixed order). No wall-clock
reads.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

from aa_model.entity.fixture import segment_totals
from aa_model.entity.schemas import (
    _POLICY_CLASS_ORDER,
    EntityFixture,
    EntityPolicyConfig,
    HoldingRecord,
)

_ZERO = Decimal("0")
_HUNDRED = Decimal("100")

# Fixed presentation order for redemption tiers; 'untiered' collects investable
# segments that did not declare a tier.
_TIER_ORDER: tuple[str, ...] = ("daily", "monthly", "quarterly", "at_maturity", "untiered")


def _pct(part: Decimal, whole: Decimal) -> Decimal:
    """part / whole as a fraction; 0 when whole is 0 (no div-by-zero)."""
    if whole == _ZERO:
        return _ZERO
    return part / whole


# ---- balance-sheet lens ----------------------------------------------------


@dataclass(frozen=True)
class BalanceSheetLens:
    total_nav_usd: Decimal
    investable_usd: Decimal
    structural_usd: Decimal
    investable_pct_of_nav: Decimal  # fraction in [0, 1]
    by_policy_class_usd: dict[str, Decimal] = field(default_factory=dict)
    by_segment_usd: dict[str, Decimal] = field(default_factory=dict)


def balance_sheet_lens(fixture: EntityFixture) -> BalanceSheetLens:
    t = segment_totals(fixture)
    return BalanceSheetLens(
        total_nav_usd=t.total_nav_usd,
        investable_usd=t.investable_usd,
        structural_usd=t.structural_usd,
        investable_pct_of_nav=_pct(t.investable_usd, t.total_nav_usd),
        by_policy_class_usd=dict(t.by_policy_class),
        by_segment_usd=dict(t.by_segment),
    )


# ---- allocation vs target --------------------------------------------------


@dataclass(frozen=True)
class AllocationVsTargetRow:
    policy_class: str
    current_usd: Decimal
    current_pct: Decimal  # fraction of investable base
    target_pct: Decimal  # fraction of investable base
    gap_pp: Decimal  # (current − target) in percentage points
    to_target_usd: Decimal  # + = buy to reach target; − = trim
    action: Literal["overweight", "underweight", "in_band"]


@dataclass(frozen=True)
class AllocationVsTarget:
    investable_base_usd: Decimal
    band_pp: Decimal
    rows: list[AllocationVsTargetRow] = field(default_factory=list)


def allocation_vs_target_lens(
    fixture: EntityFixture,
    policy: EntityPolicyConfig,
    *,
    band_pp: Decimal = Decimal("2"),
) -> AllocationVsTarget:
    """Policy rebalancing analysis on the investable base.

    Rows cover every class with a target OR a current holding, in canonical
    policy order. A class held with no target shows as overweight against a 0%
    target; a target with no holding shows as underweight.
    """
    if band_pp < _ZERO:
        raise ValueError(f"band_pp must be >= 0; got {band_pp}")
    if policy.entity_id != fixture.entity_id:
        raise ValueError(
            f"policy.entity_id ({policy.entity_id!r}) does not match "
            f"fixture.entity_id ({fixture.entity_id!r})"
        )
    t = segment_totals(fixture)
    base = t.investable_usd
    current_by_class = t.by_policy_class

    classes = [c for c in _POLICY_CLASS_ORDER if c in policy.targets or c in current_by_class]
    rows: list[AllocationVsTargetRow] = []
    for c in classes:
        current_usd = current_by_class.get(c, _ZERO)
        target_pct = policy.targets.get(c, _ZERO)
        current_pct = _pct(current_usd, base)
        gap_pp = (current_pct - target_pct) * _HUNDRED
        to_target_usd = (target_pct - current_pct) * base
        if abs(gap_pp) <= band_pp:
            action: Literal["overweight", "underweight", "in_band"] = "in_band"
        elif gap_pp > _ZERO:
            action = "overweight"
        else:
            action = "underweight"
        rows.append(
            AllocationVsTargetRow(
                policy_class=c,
                current_usd=current_usd,
                current_pct=current_pct,
                target_pct=target_pct,
                gap_pp=gap_pp,
                to_target_usd=to_target_usd,
                action=action,
            )
        )
    return AllocationVsTarget(investable_base_usd=base, band_pp=band_pp, rows=rows)


# ---- liquidity lens --------------------------------------------------------


@dataclass(frozen=True)
class LiquidityLens:
    investable_usd: Decimal
    by_tier_usd: dict[str, Decimal] = field(default_factory=dict)
    by_tier_pct: dict[str, Decimal] = field(default_factory=dict)
    liquid_within_30d_usd: Decimal = _ZERO
    liquid_within_30d_pct: Decimal = _ZERO


def liquidity_lens(fixture: EntityFixture) -> LiquidityLens:
    """Investable portfolio by redemption tier. Only investable segments are
    included; 'untiered' collects investable segments with no declared tier.
    Liquid-within-30-days = daily + monthly."""
    by_tier: dict[str, Decimal] = {}
    investable = _ZERO
    for seg in fixture.segments:
        if seg.segment != "investable":
            continue
        investable += seg.amount_usd
        tier = seg.liquidity_tier or "untiered"
        by_tier[tier] = by_tier.get(tier, _ZERO) + seg.amount_usd

    ordered_usd = {tier: by_tier[tier] for tier in _TIER_ORDER if tier in by_tier}
    ordered_pct = {tier: _pct(amt, investable) for tier, amt in ordered_usd.items()}
    within_30d = by_tier.get("daily", _ZERO) + by_tier.get("monthly", _ZERO)
    return LiquidityLens(
        investable_usd=investable,
        by_tier_usd=ordered_usd,
        by_tier_pct=ordered_pct,
        liquid_within_30d_usd=within_30d,
        liquid_within_30d_pct=_pct(within_30d, investable),
    )


# ---- holdings detail -------------------------------------------------------


@dataclass(frozen=True)
class HoldingsClassGroup:
    policy_class: str
    holdings: list[HoldingRecord]
    subtotal_usd: Decimal
    segment_usd: Decimal  # investable segment total for this class
    reconciles: bool  # subtotal == segment within tolerance
    delta_usd: Decimal


@dataclass(frozen=True)
class HoldingsDetail:
    total_usd: Decimal
    groups: list[HoldingsClassGroup] = field(default_factory=list)


def holdings_detail_lens(
    fixture: EntityFixture, *, recon_tolerance: Decimal = Decimal("1.00")
) -> HoldingsDetail:
    """Position-level holdings grouped by policy class (canonical order), with
    per-class reconciliation to the investable balance-sheet segment. Holdings
    within a class are ordered by holding_key for determinism."""
    seg_by_class = segment_totals(fixture).by_policy_class
    holdings_by_class: dict[str, list[HoldingRecord]] = {}
    for h in fixture.holdings:
        holdings_by_class.setdefault(h.policy_class, []).append(h)

    classes = [c for c in _POLICY_CLASS_ORDER if c in holdings_by_class or c in seg_by_class]
    groups: list[HoldingsClassGroup] = []
    total = _ZERO
    for c in classes:
        hs = sorted(holdings_by_class.get(c, []), key=lambda h: h.holding_key)
        subtotal = sum((h.market_value_usd for h in hs), _ZERO)
        seg_usd = seg_by_class.get(c, _ZERO)
        total += subtotal
        # reconcile only where holdings exist for the class (partial coverage
        # is allowed — a class with a segment but no line items is not a break).
        reconciles = (not hs) or abs(subtotal - seg_usd) <= recon_tolerance
        groups.append(
            HoldingsClassGroup(
                policy_class=c,
                holdings=hs,
                subtotal_usd=subtotal,
                segment_usd=seg_usd,
                reconciles=reconciles,
                delta_usd=subtotal - seg_usd,
            )
        )
    return HoldingsDetail(total_usd=total, groups=groups)


# ---- liquidity projection --------------------------------------------------


@dataclass(frozen=True)
class LiquidityProjectionLens:
    quarters: int
    period_first: str | None
    period_last: str | None
    beginning_usd: Decimal  # first quarter's beginning
    ending_usd: Decimal  # last quarter's ending
    min_ending_usd: Decimal
    min_ending_period: str | None
    goes_negative: bool  # any quarter ends below zero (liquidity breach)
    trajectory: list[tuple[str, Decimal]] = field(default_factory=list)


def liquidity_projection_lens(fixture: EntityFixture) -> LiquidityProjectionLens:
    """Reduce the quarterly liquidity cash-flow projection to its ending
    trajectory + runway signal. Chain continuity is already enforced by the
    fixture; here we surface the min ending balance and any breach below 0."""
    recs = sorted(fixture.liquidity_projection, key=lambda r: r.period)
    if not recs:
        return LiquidityProjectionLens(
            quarters=0,
            period_first=None,
            period_last=None,
            beginning_usd=_ZERO,
            ending_usd=_ZERO,
            min_ending_usd=_ZERO,
            min_ending_period=None,
            goes_negative=False,
            trajectory=[],
        )
    trajectory = [(r.period, r.ending_usd) for r in recs]
    min_period, min_ending = min(trajectory, key=lambda pe: pe[1])
    return LiquidityProjectionLens(
        quarters=len(recs),
        period_first=recs[0].period,
        period_last=recs[-1].period,
        beginning_usd=recs[0].beginning_usd,
        ending_usd=recs[-1].ending_usd,
        min_ending_usd=min_ending,
        min_ending_period=min_period,
        goes_negative=min_ending < _ZERO,
        trajectory=trajectory,
    )
