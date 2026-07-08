"""Phase 24 — build an entity fixture from curated (policy-classed) position
rows, e.g. the firm's Investment Summary workbook.

Unlike the Phase-15 bridge (which maps the finer `asset_class` taxonomy), a
curated source is already authored at policy-class grain: each row carries a
policy-class label, a market value, an optional liquidity label, and optional
commitment / unfunded amounts. This module turns such rows — filtered to one
entity — into a deterministic `EntityFixture`:

- **holdings**: one per position (policy class via `policy_class_from_label`,
  tier via `tier_from_label`), keys sanitized + de-duped.
- **segments**: investable, aggregated by (policy class × tier); they sum to
  the investable base and reconcile to holdings per class by construction.
- **pe_exposure**: for positions with a commitment > 0.

The transform is pure and testable; `read_investment_summary_positions`
is a thin column-mapped xlsx reader around it. Real (client) workbooks stay
in gitignored paths — this module only takes a path/rows.
"""

from __future__ import annotations

import re as _re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from pathlib import Path

from aa_model.entity.crosswalk import policy_class_from_label, tier_from_label
from aa_model.entity.schemas import EntityFixture

_NON_URL_SAFE = _re.compile(r"[^A-Za-z0-9_\-.]+")


@dataclass(frozen=True)
class CuratedPosition:
    """One curated position row (already policy-classed by the source)."""

    name: str
    policy_class_label: str
    market_value_usd: Decimal
    liquidity_label: str | None = None
    commitment_usd: Decimal | None = None
    unfunded_usd: Decimal | None = None


def _safe_key(raw: str, seen: set[str]) -> str:
    base = _NON_URL_SAFE.sub("_", str(raw)).strip("_")[:50] or "pos"
    key = base
    n = 1
    while key in seen:
        n += 1
        key = f"{base}_{n}"
    seen.add(key)
    return key


def fixture_from_curated_positions(
    positions: list[CuratedPosition],
    *,
    entity_id: str,
    as_of_date: date | str,
    fixture_version: str,
    account_id: str = "portfolio",
) -> EntityFixture:
    """Build an `EntityFixture` (investable holdings + segments + PE exposure)
    from curated positions for a single entity. Deterministic; segments
    reconcile to the investable base and to holdings per class."""
    seen: set[str] = set()
    holdings: list[dict] = []
    pe: list[dict] = []
    seg_by: dict[tuple[str, str | None], Decimal] = {}

    for pos in positions:
        pc = policy_class_from_label(pos.policy_class_label)
        tier = tier_from_label(pos.liquidity_label)
        key = _safe_key(pos.name, seen)
        h: dict = {
            "holding_key": key,
            "account_id": account_id,
            "policy_class": pc,
            "asset_class": "other",
            "market_value_usd": str(pos.market_value_usd),
        }
        if tier:
            h["liquidity_tier"] = tier
        holdings.append(h)
        seg_by[(pc, tier)] = seg_by.get((pc, tier), Decimal("0")) + pos.market_value_usd
        if pos.commitment_usd is not None and pos.commitment_usd > 0:
            rec: dict = {
                "fund_key": f"fund_{key}",
                "entity_id": entity_id,
                "policy_class": pc,
                "commitment_usd": str(pos.commitment_usd),
                "nav_usd": str(pos.market_value_usd),
            }
            if pos.unfunded_usd is not None and pos.unfunded_usd >= 0:
                rec["unfunded_usd"] = str(pos.unfunded_usd)
            pe.append(rec)

    segments: list[dict] = []
    for (pc, tier), amt in seg_by.items():
        seg: dict = {
            "segment_key": f"inv_{pc}" + (f"_{tier}" if tier else "_untiered"),
            "segment": "investable",
            "policy_class": pc,
            "amount_usd": str(amt),
        }
        if tier:
            seg["liquidity_tier"] = tier
        segments.append(seg)

    total = sum(seg_by.values(), Decimal("0"))
    return EntityFixture.model_validate(
        {
            "fixture_version": fixture_version,
            "entity_id": entity_id,
            "as_of_date": as_of_date if isinstance(as_of_date, str) else as_of_date.isoformat(),
            "segments": segments,
            "holdings": holdings,
            "pe_exposure": pe,
            "expected_total_nav_usd": str(total),
        }
    )


def read_investment_summary_positions(
    workbook_path: str | Path,
    entity: str,
    *,
    sheet: str = "Data",
    header_row: int = 1,
    entity_col: int = 10,
    policy_label_col: int = 4,
    market_value_col: int = 9,
    liquidity_col: int = 15,
    commitment_col: int = 7,
    unfunded_col: int = 8,
    name_cols: tuple[int, ...] = (2, 0, 5),
) -> list[CuratedPosition]:
    """Read the Investment Summary workbook (read-only) and return the curated
    positions for ``entity`` (matched on the ``entity_col`` value). Column
    indices are 0-based and default to the known 'Data' sheet layout. Never
    mutates the workbook."""
    import openpyxl

    def _dec(v: object) -> Decimal | None:
        return Decimal(str(v)) if isinstance(v, int | float) else None

    wb = openpyxl.load_workbook(workbook_path, data_only=True, read_only=True, keep_links=False)
    try:
        ws = wb[sheet]
        out: list[CuratedPosition] = []
        for row in ws.iter_rows(min_row=header_row + 1, values_only=True):
            if entity_col >= len(row) or row[entity_col] != entity:
                continue
            mv = _dec(row[market_value_col]) if market_value_col < len(row) else None
            if mv is None:
                continue
            label = row[policy_label_col] if policy_label_col < len(row) else None
            if not (isinstance(label, str) and label.strip()):
                continue
            name = next(
                (
                    str(row[c])
                    for c in name_cols
                    if c < len(row) and isinstance(row[c], str) and row[c].strip()
                ),
                "position",
            )
            liq = row[liquidity_col] if liquidity_col < len(row) else None
            out.append(
                CuratedPosition(
                    name=name,
                    policy_class_label=label.strip(),
                    market_value_usd=mv,
                    liquidity_label=liq if isinstance(liq, str) else None,
                    commitment_usd=_dec(row[commitment_col]) if commitment_col < len(row) else None,
                    unfunded_usd=_dec(row[unfunded_col]) if unfunded_col < len(row) else None,
                )
            )
        return out
    finally:
        wb.close()
