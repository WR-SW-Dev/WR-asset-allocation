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

# Reuse the Phase 15 normalized account record — account scope is the same
# concept; no duplicate model.
from aa_model.ingestion.schemas_position import AccountRecord

_STRICT = ConfigDict(extra="forbid")
_URL_SAFE_RE = _re.compile(r"^[A-Za-z0-9_\-\.]+$")

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
    lifecycle amounts. `unfunded_usd`, when supplied, must equal
    `commitment_usd - called_to_date_usd`; it is never synthesized when the
    inputs are missing.
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
        if self.called_to_date_usd is not None and self.called_to_date_usd > self.commitment_usd:
            raise ValueError(
                f"fund_key={self.fund_key!r}: called_to_date_usd "
                f"({self.called_to_date_usd}) exceeds commitment_usd "
                f"({self.commitment_usd})"
            )
        # unfunded, when both it and called are present, must reconcile exactly.
        if self.unfunded_usd is not None and self.called_to_date_usd is not None:
            implied = self.commitment_usd - self.called_to_date_usd
            if abs(self.unfunded_usd - implied) > _RECON_TOLERANCE:
                raise ValueError(
                    f"fund_key={self.fund_key!r}: unfunded_usd "
                    f"({self.unfunded_usd}) != commitment - called ({implied})"
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
