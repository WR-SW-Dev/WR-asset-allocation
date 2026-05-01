"""Capital market assumptions. Phase 1: minimal data class.

The stub allocator ignores CMA inputs; this type exists to satisfy the
``AllocationAdapter.fit`` contract in SPEC §9 so Phase 3 adapters can consume it.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass(frozen=True)
class CMA:
    """Annualized capital market assumptions for the public side.

    Attributes:
        expected_returns_annual: index = bucket, values = annual mean return.
        vol_annual: index = bucket, values = annual volatility.
        corr: bucket × bucket correlation matrix.
    """

    expected_returns_annual: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    vol_annual: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    corr: pd.DataFrame = field(default_factory=pd.DataFrame)
