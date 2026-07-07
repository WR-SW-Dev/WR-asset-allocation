"""Schemas + constants for Morningstar Direct index-return ingestion.

Kept in a dedicated module (not ``io.schemas`` or ``ingestion.schemas``) so the
export-based index-return pathway does not tangle with the Phase 14 workbook
(cash-flow) ingestion schemas. Pydantic v2, ``extra='forbid'``, loud validation —
matching the rest of the package (SPEC §2.2).

Contract summary
----------------
* ``IndexUniverseConfig``     parsed ``configs/morningstar_index_universe.yaml``.
* ``AssetClassIndexMapConfig``parsed ``configs/asset_class_index_map.yaml``.
* Module constants define the canonical normalized-store columns, the horizon
  vocabulary, and the quality-flag vocabulary consumed by ``morningstar_returns``.
"""

from __future__ import annotations

import re
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_STRICT = ConfigDict(extra="forbid")

# ---- vocabularies ----------------------------------------------------------

# Trailing-return horizons emitted by the Morningstar "Common Indices" layout.
# ``annualized`` marks windows Morningstar reports on an annualized basis.
HORIZONS: dict[str, bool] = {
    "1M": False,
    "3M": False,
    "6M": False,
    "1Y": False,
    "3Y_ann": True,
    "5Y_ann": True,
    "10Y_ann": True,
    "15Y_ann": True,
    "inception_ann": True,
}

# The single canonical monthly-return horizon. The 1-month trailing return at a
# month-end return date IS that month's total return, so model / CMA consumers
# that want "the monthly return series" read this slice.
CANONICAL_MONTHLY_HORIZON = "1M"

# Exact Morningstar "Common Indices" header -> (horizon, annualized). Matched on
# the exact header string so column reordering does not break the parser; any
# Gross / Load-Adj / Investor / Yield / Rank columns are ignored by omission.
TOTAL_RETURN_HEADER_TO_HORIZON: dict[str, str] = {
    "Total Ret 1 Mo (Mo-End) Base Currency": "1M",
    "Total Ret 3 Mo (Mo-End) Base Currency": "3M",
    "Total Ret 6 Mo (Mo-End) Base Currency": "6M",
    "Total Ret 1 Yr (Mo-End) Base Currency": "1Y",
    "Total Ret Annlzd 3 Yr (Mo-End) Base Currency": "3Y_ann",
    "Total Ret Annlzd 5 Yr (Mo-End) Base Currency": "5Y_ann",
    "Total Ret Annlzd 10 Yr (Mo-End) Base Currency": "10Y_ann",
    "Total Ret Annlzd 15 Yr (Mo-End) Base Currency": "15Y_ann",
    "Total Ret Inception (Mo-End) Base Currency": "inception_ann",
}

NAME_HEADER = "Name"
RETURN_DATE_HEADER = "Return Date (Mo-End)"
BASE_CURRENCY_HEADER = "Base Currency"

# Rows in the "Common Indices" tab that are summary statistics, not indices.
# Matched case-insensitively after stripping; anything at/after "Summary
# Statistics" is also treated as the summary block (belt and suspenders).
SUMMARY_ROW_LABELS: frozenset[str] = frozenset(
    s.lower()
    for s in (
        "Summary Statistics",
        "Eightieth Percentile",
        "Sixtieth Percentile",
        "Fortieth Percentile",
        "Twentieth Percentile",
        "Sum",
        "Average",
        "Count",
        "Maximum",
        "Minimum",
        "Median",
        "Standard Deviation",
    )
)
SUMMARY_BLOCK_SENTINEL = "summary statistics"

# Canonical normalized-store columns (order is stable and part of the contract).
NORMALIZED_COLUMNS: tuple[str, ...] = (
    "date",
    "index_key",
    "horizon",
    "return_decimal",
    "annualized",
    "level",
    "currency",
    "source",
    "source_field",
    "return_type",
    "frequency",
    "asof_date",
    "fetched_at_utc",
    "vendor_id",
    "quality_flag",
    "notes",
)

# Quality-flag vocabulary. A row's ``quality_flag`` is "OK" or a pipe-joined,
# sorted subset of the non-OK flags.
QUALITY_FLAGS: tuple[str, ...] = (
    "OK",
    "MISSING_MONTH",
    "DUPLICATE_DATE",
    "NON_MONTH_END_DATE",
    "EXTREME_RETURN",
    "STALE_SERIES",
    "SHORT_HISTORY",
    "CURRENCY_MISMATCH",
    "RETURN_TYPE_UNKNOWN",
)

SOURCE_NAME = "Morningstar Direct"

_INDEX_KEY_RE = re.compile(r"^[a-z0-9_]+$")

ReturnType = Literal["total_return", "net_return", "price_return", "unknown"]
Frequency = Literal["monthly", "quarterly_or_monthly_source"]
ModelRole = Literal[
    "benchmark",
    "capital_market_assumption",
    "stress_proxy",
    "reporting_only",
    "sector_proxy",
    "credit_proxy",
    "cash_proxy",
    "muni_credit_proxy",
    "private_real_estate_proxy",
    "custom_proxy",
]
ModelUsage = Literal[
    "benchmark",
    "capital_market_assumption",
    "stress_proxy",
    "reporting_only",
]


# ---- index universe --------------------------------------------------------


class IndexUniverseEntry(BaseModel):
    model_config = _STRICT
    index_key: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    provider: str = "Morningstar Direct"
    morningstar_id: str | None = None
    morningstar_symbol: str | None = None
    asset_class: str = Field(min_length=1)
    sub_asset_class: str = Field(min_length=1)
    region: str = Field(min_length=1)
    currency: str = Field(min_length=1)
    return_type: ReturnType
    frequency: Frequency
    preferred_start_date: str | None = None
    model_role: ModelRole
    notes: str = ""

    @field_validator("index_key")
    @classmethod
    def _slug(cls, v: str) -> str:
        if not _INDEX_KEY_RE.match(v):
            raise ValueError(f"index_key must be snake_case [a-z0-9_]; got {v!r}")
        return v


class IndexUniverseConfig(BaseModel):
    model_config = _STRICT
    provider_default: str = "Morningstar Direct"
    source_workbook: str | None = None
    source_sheet: str = "Common Indices"
    indices: list[IndexUniverseEntry]

    @model_validator(mode="after")
    def _unique(self) -> IndexUniverseConfig:
        if not self.indices:
            raise ValueError("morningstar_index_universe.yaml has no indices")
        keys = [e.index_key for e in self.indices]
        if len(keys) != len(set(keys)):
            dups = sorted({k for k in keys if keys.count(k) > 1})
            raise ValueError(f"duplicate index_key(s): {dups}")
        names = [e.display_name for e in self.indices]
        if len(names) != len(set(names)):
            dups = sorted({n for n in names if names.count(n) > 1})
            raise ValueError(f"duplicate display_name(s): {dups}")
        return self

    def by_display_name(self) -> dict[str, IndexUniverseEntry]:
        return {e.display_name: e for e in self.indices}

    def by_index_key(self) -> dict[str, IndexUniverseEntry]:
        return {e.index_key: e for e in self.indices}


# ---- asset-class -> index map ----------------------------------------------


class AssetClassIndexMapEntry(BaseModel):
    model_config = _STRICT
    asset_class: str = Field(min_length=1)
    sub_asset_class: str = Field(min_length=1)
    primary_index_key: str = Field(min_length=1)
    secondary_index_keys: list[str] = Field(default_factory=list)
    fallback_index_key: str | None = None
    model_usage: ModelUsage
    min_history_months: int = Field(ge=0, default=0)
    requires_approval: bool = False
    notes: str = ""

    def all_index_keys(self) -> list[str]:
        keys = [self.primary_index_key, *self.secondary_index_keys]
        if self.fallback_index_key:
            keys.append(self.fallback_index_key)
        return keys


class AssetClassIndexMapConfig(BaseModel):
    model_config = _STRICT
    asset_classes: list[AssetClassIndexMapEntry]

    @model_validator(mode="after")
    def _unique(self) -> AssetClassIndexMapConfig:
        if not self.asset_classes:
            raise ValueError("asset_class_index_map.yaml has no asset_classes")
        pairs = [(e.asset_class, e.sub_asset_class) for e in self.asset_classes]
        if len(pairs) != len(set(pairs)):
            dups = sorted({p for p in pairs if pairs.count(p) > 1})
            raise ValueError(f"duplicate (asset_class, sub_asset_class): {dups}")
        return self

    def referenced_index_keys(self) -> set[str]:
        out: set[str] = set()
        for e in self.asset_classes:
            out.update(e.all_index_keys())
        return out
