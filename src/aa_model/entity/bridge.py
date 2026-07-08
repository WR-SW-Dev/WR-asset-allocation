"""Phase 24 — bridge Phase-15 position ingestion into entity holdings.

Turns the normalized `PositionRecord`s from `ingest_investment_summary`
(the Investment Summary workbook) into entity `HoldingRecord`s the
holdings-detail lens consumes: maps `asset_class` -> Wake Robin policy class
and `liquidity_bucket` -> redemption tier via the committed crosswalks, and
converts `market_value_usd` from float to `Decimal` at this boundary
(`Decimal(str(v))`, so no binary-float artifacts enter the exact-reconciling
entity layer).

`holding_key` is derived from `position_id` (sanitized URL-safe, de-duped) so
the bridge is deterministic and the fixture's uniqueness invariant holds.
"""

from __future__ import annotations

import re as _re
from decimal import Decimal

from aa_model.entity.crosswalk import liquidity_tier_for, policy_class_for
from aa_model.entity.schemas import HoldingRecord
from aa_model.ingestion.schemas_position import PositionRecord

_NON_URL_SAFE = _re.compile(r"[^A-Za-z0-9_\-.]+")


def _safe_key(raw: str, seen: set[str]) -> str:
    base = _NON_URL_SAFE.sub("_", raw).strip("_") or "pos"
    key = base
    n = 1
    while key in seen:
        n += 1
        key = f"{base}_{n}"
    seen.add(key)
    return key


def holdings_from_positions(
    positions: list[PositionRecord],
    *,
    with_liquidity_tier: bool = True,
) -> list[HoldingRecord]:
    """Map ingested positions to entity holdings.

    `with_liquidity_tier=False` leaves the tier unset (use when the ingestion
    bucket vocabulary should not drive the study's tier axis). Order follows
    the input; keys are stable and de-duped.
    """
    seen: set[str] = set()
    holdings: list[HoldingRecord] = []
    for p in positions:
        policy = policy_class_for(p.asset_class, p.liquidity_bucket)
        tier = liquidity_tier_for(p.liquidity_bucket) if with_liquidity_tier else None
        holdings.append(
            HoldingRecord(
                holding_key=_safe_key(p.position_id, seen),
                account_id=p.account_id,
                policy_class=policy,
                asset_class=p.asset_class,
                market_value_usd=Decimal(str(p.market_value_usd)),
                manager_id=p.manager_id,
                liquidity_tier=tier,
            )
        )
    return holdings
