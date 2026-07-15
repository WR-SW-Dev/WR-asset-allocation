"""Phase 24 — Entity fixture schemas.

Pydantic v2 models that capture a single entity deterministically along the
four dimensions that must be stable before the Wake Robin study scales
across entities:

1. **Entity perimeter** — `EntityFixture` identity: `entity_id`, `as_of_date`,
   `fixture_version`, plus an optional reconciliation control total.
2. **Account scope** — the set of accounts in scope (reuses the Phase 15
   `AccountRecord`; every account must carry this fixture's `entity_id`).
3. **Balance-sheet segmentation** — total NAV split into investable financial
   assets (by Wake Robin policy class) and personal-use / structural segments.
   Encodes the load-bearing `NAV ≠ liquidity` principle: structural NAV is
   never counted in the investable base.
4. **PE commitment exposure** — per-fund commitment / called / distributed /
   NAV / unfunded (an aligned subset of the Phase 23 commitment book).

Money is `Decimal` so balance-sheet reconciliation is exact (no float drift).
Conversion to `float` happens only at adapter boundaries into existing
engines — not here. Follows the Phase 12–23 discipline: URL-safe ids,
finite non-negative amounts, explicit classification, fail-loud validation.

Privacy: this module is methodology only. Real entity fixtures (values,
names, real `entity_id`s) live in gitignored local files; committed
fixtures are synthetic.
"""

from __future__ import annotations

import re as _re
from datetime import date
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Reuse the Phase 15 normalized account record + asset-class taxonomy —
# account scope and holdings are the same concepts; no duplicate models.
from aa_model.ingestion.schemas_position import _ASSET_CLASS_LITERAL, AccountRecord

_STRICT = ConfigDict(extra="forbid")
_URL_SAFE_RE = _re.compile(r"^[A-Za-z0-9_\-\.]+$")
_QUARTER_RE = _re.compile(r"^\d{4}Q[1-4]$")

# Reconciliation tolerance for Decimal control-total checks (1 cent).
_RECON_TOLERANCE = Decimal("0.01")


# The seven Wake Robin strategic policy classes. Committed methodology, not
# client data. Only investable segments carry a policy_class.
_POLICY_CLASS_LITERAL = Literal[
    "re_opco_stabilized",
    "real_estate",
    "equity",
    "private_equity",
    "absolute_return",
    "fixed_income",
    "cash_and_cash_alts",
]

# Balance-sheet segment kinds. `investable` rolls into the investable base;
# every other kind is personal-use / structural NAV (never investable).
_SEGMENT_LITERAL = Literal[
    "investable",  # investable financial asset (carries a policy_class)
    "personal_use",  # homes, land, art, autos, boats
    "note_receivable",  # promissory notes receivable
    "nested_opco_equity",  # operating-company equity held by the entity
    "life_insurance_csv",  # life insurance cash surrender value
    "other_structural",  # any other non-investable structural asset
]

_INVESTABLE_SEGMENT = "investable"

# Canonical display/iteration order of the seven policy classes. Used by the
# allocation-vs-target lens so class ordering is deterministic.
_POLICY_CLASS_ORDER: tuple[str, ...] = (
    "re_opco_stabilized",
    "real_estate",
    "equity",
    "private_equity",
    "absolute_return",
    "fixed_income",
    "cash_and_cash_alts",
)

# Redemption-tier presentation axis for the liquidity lens. Distinct from the
# Phase-12 liquid/semi_liquid/illiquid tiers and the Phase-15 buckets; this is
# the study's client-facing tier vocabulary. Only investable segments carry it.
_LIQUIDITY_TIER_LITERAL = Literal["daily", "monthly", "quarterly", "at_maturity"]


class BalanceSheetSegmentRecord(BaseModel):
    """One balance-sheet segment amount.

    `investable` segments carry a `policy_class` (one of the seven Wake
    Robin classes) and roll into the investable base. All other segment
    kinds are personal-use / structural NAV and must NOT carry a
    `policy_class`.
    """

    model_config = _STRICT

    segment_key: str  # URL-safe, unique within a fixture
    segment: _SEGMENT_LITERAL
    policy_class: _POLICY_CLASS_LITERAL | None = None
    amount_usd: Decimal
    # Optional redemption tier for the liquidity lens. Only meaningful for
    # investable segments; structural NAV must leave it None.
    liquidity_tier: _LIQUIDITY_TIER_LITERAL | None = None

    @field_validator("segment_key")
    @classmethod
    def _key_url_safe(cls, v: str) -> str:
        if not _URL_SAFE_RE.match(v):
            raise ValueError(f"segment_key must be URL-safe (alphanumeric, _, -, .); got {v!r}")
        return v

    @field_validator("amount_usd")
    @classmethod
    def _amount_non_negative_finite(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError(f"amount_usd must be finite; got {v}")
        if v < 0:
            raise ValueError(
                f"amount_usd must be >= 0 (balance-sheet segments are stocks "
                f"of value, not flows); got {v}"
            )
        return v

    @model_validator(mode="after")
    def _policy_class_iff_investable(self) -> BalanceSheetSegmentRecord:
        is_investable = self.segment == _INVESTABLE_SEGMENT
        if is_investable and self.policy_class is None:
            raise ValueError(
                f"segment_key={self.segment_key!r}: investable segments must "
                f"carry a policy_class (one of the seven Wake Robin classes)"
            )
        if not is_investable and self.policy_class is not None:
            raise ValueError(
                f"segment_key={self.segment_key!r}: non-investable segment "
                f"{self.segment!r} must NOT carry a policy_class "
                f"(structural NAV is never in the investable base)"
            )
        if not is_investable and self.liquidity_tier is not None:
            raise ValueError(
                f"segment_key={self.segment_key!r}: non-investable segment "
                f"{self.segment!r} must NOT carry a liquidity_tier "
                f"(the liquidity lens covers the investable portfolio only)"
            )
        return self


class PECommitmentExposureRecord(BaseModel):
    """Per-fund PE / alternatives commitment exposure at `as_of_date`.

    Aligned subset of the Phase 23 commitment book: identity + the four
    lifecycle amounts. Cumulative `called_to_date_usd` may exceed
    `commitment_usd` (recallable capital re-called). `unfunded_usd` is a
    floor-0 quantity: when supplied it must equal
    `max(0, commitment_usd - called_to_date_usd)`; it is never synthesized
    when the inputs are missing.
    """

    model_config = _STRICT

    fund_key: str  # URL-safe, unique within a fixture
    entity_id: str
    policy_class: _POLICY_CLASS_LITERAL
    commitment_usd: Decimal = Field(gt=0)
    called_to_date_usd: Decimal | None = None
    distributed_to_date_usd: Decimal | None = None
    nav_usd: Decimal | None = None
    unfunded_usd: Decimal | None = None

    @field_validator("fund_key")
    @classmethod
    def _fund_key_url_safe(cls, v: str) -> str:
        if not _URL_SAFE_RE.match(v):
            raise ValueError(f"fund_key must be URL-safe (alphanumeric, _, -, .); got {v!r}")
        return v

    @field_validator("entity_id")
    @classmethod
    def _entity_id_no_colons(cls, v: str) -> str:
        if ":" in v:
            raise ValueError(f"entity_id must not contain colons; got {v!r}")
        return v

    @field_validator("called_to_date_usd", "distributed_to_date_usd", "nav_usd", "unfunded_usd")
    @classmethod
    def _non_negative_finite(cls, v: Decimal | None) -> Decimal | None:
        if v is None:
            return v
        if not v.is_finite():
            raise ValueError(f"amount must be finite; got {v}")
        if v < 0:
            raise ValueError(f"amount must be >= 0; got {v}")
        return v

    @model_validator(mode="after")
    def _lifecycle_consistency(self) -> PECommitmentExposureRecord:
        # Cumulative called (paid-in) MAY exceed commitment when distributions
        # are recallable and subsequently re-called — a real PE condition
        # (surfaced by the J&D oracle). So there is no `called <= commitment`
        # rule. Unfunded commitment is a floor-0 quantity, so when both it and
        # called are present it reconciles to max(0, commitment - called).
        if self.unfunded_usd is not None and self.called_to_date_usd is not None:
            implied = max(Decimal("0"), self.commitment_usd - self.called_to_date_usd)
            if abs(self.unfunded_usd - implied) > _RECON_TOLERANCE:
                raise ValueError(
                    f"fund_key={self.fund_key!r}: unfunded_usd "
                    f"({self.unfunded_usd}) != max(0, commitment - called) ({implied})"
                )
        return self


class HoldingRecord(BaseModel):
    """One position-level holding backing the investable base.

    Holdings roll up to the investable balance-sheet segments by
    `policy_class`; the holdings-detail lens reconciles Σ holding value per
    class to the corresponding investable segment. `asset_class` (the finer
    Phase-15 taxonomy) is carried for grouping/reporting.
    """

    model_config = _STRICT

    holding_key: str  # URL-safe, unique within a fixture
    account_id: str
    policy_class: _POLICY_CLASS_LITERAL
    asset_class: _ASSET_CLASS_LITERAL = "other"
    market_value_usd: Decimal
    manager_id: str | None = None
    liquidity_tier: _LIQUIDITY_TIER_LITERAL | None = None

    @field_validator("holding_key")
    @classmethod
    def _key_url_safe(cls, v: str) -> str:
        if not _URL_SAFE_RE.match(v):
            raise ValueError(f"holding_key must be URL-safe; got {v!r}")
        return v

    @field_validator("market_value_usd")
    @classmethod
    def _mv_non_negative_finite(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError(f"market_value_usd must be finite; got {v}")
        if v < 0:
            raise ValueError(
                f"market_value_usd must be >= 0 (holdings are stocks of value); got {v}"
            )
        return v


class QuarterProjectionRecord(BaseModel):
    """One quarter of the liquidity projection.

    Roll-forward invariant: `ending == beginning + inflows - outflows` within
    tolerance. `period` is a `YYYYQ[1-4]` label. Chain continuity (ending_q ==
    beginning_{q+1}) is enforced at the fixture level.
    """

    model_config = _STRICT

    period: str
    beginning_usd: Decimal
    total_inflows_usd: Decimal = Decimal("0")
    total_outflows_usd: Decimal = Decimal("0")
    ending_usd: Decimal

    @field_validator("period")
    @classmethod
    def _period_well_formed(cls, v: str) -> str:
        if not _QUARTER_RE.match(v):
            raise ValueError(f"period must match YYYYQ[1-4]; got {v!r}")
        return v

    @field_validator("total_inflows_usd", "total_outflows_usd")
    @classmethod
    def _flow_non_negative_finite(cls, v: Decimal) -> Decimal:
        if not v.is_finite():
            raise ValueError(f"flow must be finite; got {v}")
        if v < 0:
            raise ValueError(f"flow must be >= 0 (use the other side for sign); got {v}")
        return v

    @model_validator(mode="after")
    def _roll_forward(self) -> QuarterProjectionRecord:
        implied = self.beginning_usd + self.total_inflows_usd - self.total_outflows_usd
        if abs(self.ending_usd - implied) > _RECON_TOLERANCE:
            raise ValueError(
                f"period={self.period!r}: ending_usd ({self.ending_usd}) != "
                f"beginning + inflows - outflows ({implied})"
            )
        return self


# Household spending categories for the burn-rate lens (committed taxonomy).
_BURN_CATEGORY_LITERAL = Literal[
    "home_related",
    "travel",
    "vehicle_boat",
    "lifestyle",
    "health",
    "charitable",
    "insurance",
    "taxes",
    "gifts",
    "education",
    "non_cash",
    "other",
]


class BurnCategoryRecord(BaseModel):
    """Annual household spend for one category across one or more years."""

    model_config = _STRICT

    category: _BURN_CATEGORY_LITERAL
    amounts_by_year: dict[int, Decimal]  # {year: annual spend}

    @field_validator("amounts_by_year")
    @classmethod
    def _amounts_well_formed(cls, v: dict[int, Decimal]) -> dict[int, Decimal]:
        if not v:
            raise ValueError("amounts_by_year must be non-empty")
        for year, amt in v.items():
            if not (1990 <= year <= 2100):
                raise ValueError(f"year {year} out of range (1990-2100)")
            # Amounts may be negative: the "non_cash" category (and occasional
            # adjustments/refunds) carry credits. Only non-finite is invalid.
            if not amt.is_finite():
                raise ValueError(f"amount for {year} must be finite; got {amt}")
        return v


class CashFlowAssumptions(BaseModel):
    """Inputs for the cash-flow / runway lens.

    Living expenses are the burn-without-taxes basis. `policy_cash_pct` is a
    fraction of the investable base (the lens pulls the base from segments).
    The what-if overlay adds `scenario_addons_usd` to the draw when enabled.
    """

    model_config = _STRICT

    living_expenses_annual_usd: Decimal = Field(ge=0)
    crut_distribution_annual_usd: Decimal = Field(default=Decimal("0"), ge=0)
    managed_cash_usd: Decimal = Field(ge=0)
    policy_cash_pct: Decimal = Field(ge=0)
    reserve_years: Decimal = Field(default=Decimal("2"), ge=0)
    scenario_enabled: bool = False
    scenario_addons_usd: dict[str, Decimal] = Field(default_factory=dict)

    @field_validator("policy_cash_pct")
    @classmethod
    def _pct_range(cls, v: Decimal) -> Decimal:
        if v > 1:
            raise ValueError(f"policy_cash_pct is a fraction in [0,1]; got {v}")
        return v

    @field_validator("scenario_addons_usd")
    @classmethod
    def _addons_non_negative(cls, v: dict[str, Decimal]) -> dict[str, Decimal]:
        for k, amt in v.items():
            if not amt.is_finite() or amt < 0:
                raise ValueError(f"scenario add-on {k!r} must be finite and >= 0; got {amt}")
        return v


class CustodianReconciliation(BaseModel):
    """A custodian statement reconciliation for one account.

    `ending_value_usd` is always required (the anchor). The roll-forward
    inputs (`beginning_value_usd` + flows) are optional — a statement may be
    *pending*, leaving only the ending value and holdings known. When
    `beginning_value_usd` is present the roll-forward is enforced fail-loud:
    `ending == beginning + additions - subtractions + change` within
    tolerance. `additions` / `subtractions` are magnitudes (>= 0).
    `holdings_by_type_usd` is the statement's by-type breakdown; the lens
    reconciles its sum to the ending value (advisory — accruals may differ).
    """

    model_config = _STRICT

    account_id: str
    beginning_value_usd: Decimal | None = None
    additions_usd: Decimal = Field(default=Decimal("0"), ge=0)
    subtractions_usd: Decimal = Field(default=Decimal("0"), ge=0)
    change_in_value_usd: Decimal = Decimal("0")  # may be negative (mark-downs)
    ending_value_usd: Decimal
    holdings_by_type_usd: dict[str, Decimal] = Field(default_factory=dict)

    @field_validator("holdings_by_type_usd")
    @classmethod
    def _holdings_finite(cls, v: dict[str, Decimal]) -> dict[str, Decimal]:
        for k, amt in v.items():
            if not amt.is_finite():
                raise ValueError(f"holdings_by_type_usd[{k!r}] must be finite; got {amt}")
        return v

    @model_validator(mode="after")
    def _roll_forward(self) -> CustodianReconciliation:
        # Only when the statement's opening side is available (not pending).
        if self.beginning_value_usd is None:
            return self
        implied = (
            self.beginning_value_usd
            + self.additions_usd
            - self.subtractions_usd
            + self.change_in_value_usd
        )
        if abs(self.ending_value_usd - implied) > _RECON_TOLERANCE:
            raise ValueError(
                f"account {self.account_id!r}: ending_value_usd "
                f"({self.ending_value_usd}) != beginning + additions - "
                f"subtractions + change ({implied})"
            )
        return self


class EntityFixture(BaseModel):
    """Deterministic snapshot of one entity's perimeter, account scope,
    balance-sheet segmentation, and PE commitment exposure.

    Reproducible: `canonical_dict()` / `content_hash()` in
    ``aa_model.entity.fixture`` produce a byte-stable serialization that
    folds into the study's ``config_hash``.
    """

    model_config = _STRICT

    fixture_version: str
    entity_id: str
    as_of_date: date
    accounts: list[AccountRecord] = Field(default_factory=list)
    segments: list[BalanceSheetSegmentRecord] = Field(default_factory=list)
    pe_exposure: list[PECommitmentExposureRecord] = Field(default_factory=list)
    # Optional position-level holdings backing the investable base.
    holdings: list[HoldingRecord] = Field(default_factory=list)
    # Optional quarterly liquidity cash-flow projection (roll-forward chain).
    liquidity_projection: list[QuarterProjectionRecord] = Field(default_factory=list)
    # Optional household burn-rate (annual spend by category, by year).
    burn_rate: list[BurnCategoryRecord] = Field(default_factory=list)
    # Optional cash-flow / runway assumptions.
    cash_flow: CashFlowAssumptions | None = None
    # Optional custodian statement reconciliations (one per account).
    custodian_reconciliations: list[CustodianReconciliation] = Field(default_factory=list)
    # Optional balance-sheet control total (e.g. from the custodian/Archway
    # recon). When set, Σ(segments) must match within tolerance — fail-loud.
    expected_total_nav_usd: Decimal | None = None

    @field_validator("fixture_version")
    @classmethod
    def _version_url_safe(cls, v: str) -> str:
        if not _URL_SAFE_RE.match(v):
            raise ValueError(f"fixture_version must be URL-safe; got {v!r}")
        return v

    @field_validator("entity_id")
    @classmethod
    def _entity_id_no_colons(cls, v: str) -> str:
        if ":" in v:
            raise ValueError(f"entity_id must not contain colons; got {v!r}")
        return v

    @model_validator(mode="after")
    def _perimeter_and_scope_consistent(self) -> EntityFixture:
        # Account scope: unique ids, all bound to this entity's perimeter.
        seen_accounts: set[str] = set()
        for acct in self.accounts:
            if acct.account_id in seen_accounts:
                raise ValueError(f"Duplicate account_id in scope: {acct.account_id!r}")
            seen_accounts.add(acct.account_id)
            if acct.entity_id != self.entity_id:
                raise ValueError(
                    f"account {acct.account_id!r} has entity_id "
                    f"{acct.entity_id!r} outside this fixture's perimeter "
                    f"({self.entity_id!r})"
                )
        # Unique segment keys.
        seen_segments: set[str] = set()
        for seg in self.segments:
            if seg.segment_key in seen_segments:
                raise ValueError(f"Duplicate segment_key: {seg.segment_key!r}")
            seen_segments.add(seg.segment_key)
        # One burn-rate record per category.
        seen_categories: set[str] = set()
        for br in self.burn_rate:
            if br.category in seen_categories:
                raise ValueError(f"Duplicate burn_rate category: {br.category!r}")
            seen_categories.add(br.category)
        # One custodian reconciliation per account.
        seen_recon: set[str] = set()
        for rec in self.custodian_reconciliations:
            if rec.account_id in seen_recon:
                raise ValueError(f"Duplicate custodian reconciliation account: {rec.account_id!r}")
            seen_recon.add(rec.account_id)
        # PE exposure: unique fund keys, all bound to this entity.
        seen_funds: set[str] = set()
        for fund in self.pe_exposure:
            if fund.fund_key in seen_funds:
                raise ValueError(f"Duplicate fund_key: {fund.fund_key!r}")
            seen_funds.add(fund.fund_key)
            if fund.entity_id != self.entity_id:
                raise ValueError(
                    f"PE fund {fund.fund_key!r} has entity_id "
                    f"{fund.entity_id!r} outside this fixture's perimeter "
                    f"({self.entity_id!r})"
                )
        # Holdings: unique keys; every account_id must be in scope (when
        # accounts are enumerated).
        seen_holdings: set[str] = set()
        scoped_accounts = {a.account_id for a in self.accounts}
        for h in self.holdings:
            if h.holding_key in seen_holdings:
                raise ValueError(f"Duplicate holding_key: {h.holding_key!r}")
            seen_holdings.add(h.holding_key)
            if scoped_accounts and h.account_id not in scoped_accounts:
                raise ValueError(
                    f"holding {h.holding_key!r} references account "
                    f"{h.account_id!r} not in account scope"
                )
        # Liquidity projection: unique quarters + roll-forward chain continuity
        # (each quarter's ending == the next quarter's beginning).
        seen_periods: set[str] = set()
        for rec in self.liquidity_projection:
            if rec.period in seen_periods:
                raise ValueError(f"Duplicate projection period: {rec.period!r}")
            seen_periods.add(rec.period)
        ordered = sorted(self.liquidity_projection, key=lambda r: r.period)
        for prev, nxt in zip(ordered, ordered[1:], strict=False):
            if abs(prev.ending_usd - nxt.beginning_usd) > _RECON_TOLERANCE:
                raise ValueError(
                    f"projection chain break at {nxt.period!r}: previous ending "
                    f"({prev.ending_usd}) != beginning ({nxt.beginning_usd})"
                )
        # Balance-sheet reconciliation against the optional control total.
        if self.expected_total_nav_usd is not None:
            total = sum((s.amount_usd for s in self.segments), Decimal("0"))
            if abs(total - self.expected_total_nav_usd) > _RECON_TOLERANCE:
                raise ValueError(
                    f"segment total ({total}) does not reconcile to "
                    f"expected_total_nav_usd ({self.expected_total_nav_usd}) "
                    f"within {_RECON_TOLERANCE}"
                )
        return self


# Strategic-target sums are authored as percentages; allow a small rounding
# tolerance around 1.0 (e.g. targets stated to whole percent).
_TARGET_SUM_TOLERANCE = Decimal("0.005")


class EntityPolicyConfig(BaseModel):
    """An entity's Wake Robin strategic policy targets.

    One target weight per policy class it holds a policy for; weights are
    fractions of the investable base and sum to 1.0 within tolerance. Classes
    omitted here have an implied 0% target (still reported by the
    allocation-vs-target lens if the entity holds them — an over-target hold).
    """

    model_config = _STRICT

    policy_version: str
    entity_id: str
    targets: dict[_POLICY_CLASS_LITERAL, Decimal]

    @field_validator("policy_version")
    @classmethod
    def _version_url_safe(cls, v: str) -> str:
        if not _URL_SAFE_RE.match(v):
            raise ValueError(f"policy_version must be URL-safe; got {v!r}")
        return v

    @field_validator("entity_id")
    @classmethod
    def _entity_id_no_colons(cls, v: str) -> str:
        if ":" in v:
            raise ValueError(f"entity_id must not contain colons; got {v!r}")
        return v

    @model_validator(mode="after")
    def _targets_well_formed(self) -> EntityPolicyConfig:
        if not self.targets:
            raise ValueError("targets must be non-empty")
        for cls_name, w in self.targets.items():
            if not w.is_finite() or w < 0:
                raise ValueError(f"target[{cls_name}] must be finite and >= 0; got {w}")
        total = sum(self.targets.values(), Decimal("0"))
        if abs(total - Decimal("1")) > _TARGET_SUM_TOLERANCE:
            raise ValueError(
                f"policy targets must sum to 1.0 within {_TARGET_SUM_TOLERANCE}; got {total}"
            )
        return self


# ---- Phase 26 — purpose (goals-based) allocation ---------------------------

# The seven canonical purposes of the goals-based policy dimension. Committed
# methodology, not client data. Fixed order below is the canonical
# display/iteration order (mirrors _POLICY_CLASS_ORDER's role).
_PURPOSE_LITERAL = Literal[
    "liquidity",
    "stability",
    "income",
    "growth",
    "aggressive_growth",
    "hedge",
    "community",
]

_PURPOSE_ORDER: tuple[str, ...] = (
    "liquidity",
    "stability",
    "income",
    "growth",
    "aggressive_growth",
    "hedge",
    "community",
)


class PurposeTargetBand(BaseModel):
    """One purpose's target weight plus its asymmetric tolerance band.

    `target`, `lower_band_pp`, and `upper_band_pp` are all fractions of the
    investable base (``Decimal("0.05")`` = 5 percentage points). The band is
    asymmetric: it extends from ``target - lower_band_pp`` (floored at 0) to
    ``target + upper_band_pp``. Bounds are derived, never stored, so
    ``min_pct <= target <= max_pct`` holds by construction.
    """

    model_config = _STRICT

    purpose: _PURPOSE_LITERAL
    target: Decimal
    lower_band_pp: Decimal = Decimal("0")
    upper_band_pp: Decimal = Decimal("0")

    @field_validator("target", "lower_band_pp", "upper_band_pp")
    @classmethod
    def _finite_non_negative(cls, v: Decimal) -> Decimal:
        if not v.is_finite() or v < 0:
            raise ValueError(f"purpose band values must be finite and >= 0; got {v}")
        return v

    @property
    def min_pct(self) -> Decimal:
        return max(Decimal("0"), self.target - self.lower_band_pp)

    @property
    def max_pct(self) -> Decimal:
        return self.target + self.upper_band_pp


class EntityPurposePolicyConfig(BaseModel):
    """An entity's purpose (goals-based) policy: targets + bands + the rules
    that resolve each holding to a purpose.

    Purpose is policy, not an observed fact of a holding, so it lives here —
    the fixture schema carries no purpose field and existing fixture content
    hashes are unaffected. Resolution order per holding (fail loud):

    1. explicit ``assignments[holding_key]``,
    2. ``default_by_policy_class[holding.policy_class]``,
    3. neither → error at lens time.

    ``assignments`` keys are not validated here (the config is
    fixture-independent); a stale key fails loud when the lens runs. Purposes
    omitted from ``bands`` have an implied 0% target with zero bands.
    """

    model_config = _STRICT

    purpose_policy_version: str
    entity_id: str
    bands: dict[_PURPOSE_LITERAL, PurposeTargetBand]
    assignments: dict[str, _PURPOSE_LITERAL] = Field(default_factory=dict)
    default_by_policy_class: dict[_POLICY_CLASS_LITERAL, _PURPOSE_LITERAL] = Field(
        default_factory=dict
    )

    @field_validator("purpose_policy_version")
    @classmethod
    def _version_url_safe(cls, v: str) -> str:
        if not _URL_SAFE_RE.match(v):
            raise ValueError(f"purpose_policy_version must be URL-safe; got {v!r}")
        return v

    @field_validator("entity_id")
    @classmethod
    def _entity_id_no_colons(cls, v: str) -> str:
        if ":" in v:
            raise ValueError(f"entity_id must not contain colons; got {v!r}")
        return v

    @model_validator(mode="after")
    def _bands_well_formed(self) -> EntityPurposePolicyConfig:
        if not self.bands:
            raise ValueError("bands must be non-empty")
        for key, band in self.bands.items():
            if band.purpose != key:
                raise ValueError(
                    f"bands[{key!r}].purpose is {band.purpose!r} — the band's "
                    f"purpose field must match its dict key"
                )
        total = sum((b.target for b in self.bands.values()), Decimal("0"))
        if abs(total - Decimal("1")) > _TARGET_SUM_TOLERANCE:
            raise ValueError(
                f"purpose targets must sum to 1.0 within {_TARGET_SUM_TOLERANCE}; got {total}"
            )
        return self
