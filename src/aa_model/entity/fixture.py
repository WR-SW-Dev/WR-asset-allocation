"""Phase 24 — Entity fixture: deterministic serialization, hashing, loading,
and balance-sheet / PE-exposure reducers.

The whole point of this module is *reproducibility*: an `EntityFixture`
serializes to a byte-stable canonical form regardless of input ordering,
and `content_hash` produces the digest that folds into the study's
`config_hash`. Two fixtures with the same content — even if their accounts,
segments, or funds were authored in a different order — hash identically.
Changing any value, id, or date changes the hash.

No wall-clock reads: the only time anchor is the fixture's `as_of_date`.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml

from aa_model.entity.schemas import EntityFixture

_ZERO = Decimal("0")


def _canon_scalar(v: Any) -> Any:
    """Canonicalize a leaf value for hashing: Decimal → plain-decimal string
    (no scientific notation), everything else via its JSON-native form.
    `date` is already isoformat-serialized by pydantic's json dump path, so
    only Decimal needs special handling here."""
    if isinstance(v, Decimal):
        return format(v, "f")
    return v


def _canon(obj: Any) -> Any:
    if isinstance(obj, dict):
        return {k: _canon(obj[k]) for k in sorted(obj)}
    if isinstance(obj, list):
        return [_canon(x) for x in obj]
    return _canon_scalar(obj)


def canonical_dict(fixture: EntityFixture) -> dict[str, Any]:
    """Order-independent canonical view of a fixture.

    Record lists are sorted by their stable key so authoring order never
    affects the serialization. Decimals become plain strings.
    """
    fx = fixture.model_copy(deep=True)
    fx.accounts.sort(key=lambda a: a.account_id)
    fx.segments.sort(key=lambda s: s.segment_key)
    fx.pe_exposure.sort(key=lambda f: f.fund_key)
    # mode="python" keeps Decimal/date as objects; _canon handles Decimal,
    # and dates are converted below via the json default hook.
    raw = fx.model_dump(mode="python")
    return _canon(raw)


def _json_default(o: Any) -> str:
    # dates (and any date-like) → isoformat; Decimals handled pre-dump.
    if hasattr(o, "isoformat"):
        return o.isoformat()
    raise TypeError(f"not JSON-serializable: {type(o)!r}")


def canonical_json(fixture: EntityFixture) -> str:
    return json.dumps(
        canonical_dict(fixture),
        sort_keys=True,
        separators=(",", ":"),
        default=_json_default,
    )


def content_hash(fixture: EntityFixture) -> str:
    """SHA-256 of the canonical JSON. Stable across authoring order;
    sensitive to any content change. Folds into `config_hash`."""
    return hashlib.sha256(canonical_json(fixture).encode("utf-8")).hexdigest()


def load_entity_fixture(path: str | Path) -> EntityFixture:
    """Load and validate an entity fixture from YAML or JSON.

    Committed fixtures are synthetic (`data/fixtures/entities/`). Real
    entity fixtures live in gitignored local paths. Author monetary amounts
    as strings so they coerce to `Decimal` without float imprecision.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if p.suffix.lower() in (".yaml", ".yml"):
        data = yaml.safe_load(text)
    elif p.suffix.lower() == ".json":
        data = json.loads(text)
    else:
        raise ValueError(f"unsupported fixture extension: {p.suffix!r} (use .yaml/.yml/.json)")
    if not isinstance(data, dict):
        raise ValueError(f"fixture root must be a mapping; got {type(data)!r}")
    return EntityFixture.model_validate(data)


# ---- reducers --------------------------------------------------------------


@dataclass(frozen=True)
class SegmentTotals:
    """Balance-sheet segmentation totals. `investable + structural = total`."""

    investable_usd: Decimal
    structural_usd: Decimal
    total_nav_usd: Decimal
    by_policy_class: dict[str, Decimal] = field(default_factory=dict)
    by_segment: dict[str, Decimal] = field(default_factory=dict)


def segment_totals(fixture: EntityFixture) -> SegmentTotals:
    """Deterministic balance-sheet roll-up. Investable segments (which carry
    a policy_class) form the investable base; everything else is structural
    NAV. `investable + structural == total` exactly (Decimal)."""
    investable = _ZERO
    structural = _ZERO
    by_class: dict[str, Decimal] = {}
    by_segment: dict[str, Decimal] = {}
    for seg in fixture.segments:
        by_segment[seg.segment] = by_segment.get(seg.segment, _ZERO) + seg.amount_usd
        if seg.segment == "investable":
            investable += seg.amount_usd
            assert seg.policy_class is not None  # enforced by schema
            by_class[seg.policy_class] = by_class.get(seg.policy_class, _ZERO) + seg.amount_usd
        else:
            structural += seg.amount_usd
    return SegmentTotals(
        investable_usd=investable,
        structural_usd=structural,
        total_nav_usd=investable + structural,
        by_policy_class=dict(sorted(by_class.items())),
        by_segment=dict(sorted(by_segment.items())),
    )


@dataclass(frozen=True)
class PEExposureTotals:
    """PE / alternatives commitment-exposure roll-up.

    Sums are over the funds where a given field is present. `*_complete`
    flags whether every fund supplied that field — a sum over a partial set
    is reported but flagged so it is never mistaken for a full total.
    """

    fund_count: int
    commitment_usd: Decimal
    called_to_date_usd: Decimal
    distributed_to_date_usd: Decimal
    nav_usd: Decimal
    unfunded_usd: Decimal
    called_complete: bool
    distributed_complete: bool
    nav_complete: bool
    unfunded_complete: bool
    by_policy_class_commitment: dict[str, Decimal] = field(default_factory=dict)


def pe_exposure_totals(fixture: EntityFixture) -> PEExposureTotals:
    """Deterministic PE commitment-exposure roll-up. Commitment is always
    present (schema-enforced gt 0); the other lifecycle amounts are optional
    and summed only where supplied, with per-field completeness flags."""
    funds = fixture.pe_exposure
    commitment = sum((f.commitment_usd for f in funds), _ZERO)
    by_class: dict[str, Decimal] = {}
    for f in funds:
        by_class[f.policy_class] = by_class.get(f.policy_class, _ZERO) + f.commitment_usd

    def _sum(attr: str) -> tuple[Decimal, bool]:
        vals = [getattr(f, attr) for f in funds]
        present = [v for v in vals if v is not None]
        complete = len(present) == len(funds) and len(funds) > 0
        return sum(present, _ZERO), complete

    called, called_complete = _sum("called_to_date_usd")
    distributed, distributed_complete = _sum("distributed_to_date_usd")
    nav, nav_complete = _sum("nav_usd")
    unfunded, unfunded_complete = _sum("unfunded_usd")

    return PEExposureTotals(
        fund_count=len(funds),
        commitment_usd=commitment,
        called_to_date_usd=called,
        distributed_to_date_usd=distributed,
        nav_usd=nav,
        unfunded_usd=unfunded,
        called_complete=called_complete,
        distributed_complete=distributed_complete,
        nav_complete=nav_complete,
        unfunded_complete=unfunded_complete,
        by_policy_class_commitment=dict(sorted(by_class.items())),
    )
