"""Stub allocator: returns ``stub_weights`` from config verbatim.

Reference implementation of ``AllocationAdapter``. Ignores returns / CMA /
constraints inputs (records their shape in diagnostics). External optimizer
adapters in Phase 3 must conform to this same surface.
"""

from __future__ import annotations

import pandas as pd

from aa_model.allocation.base import AllocationAdapter
from aa_model.allocation.constraints import Constraints
from aa_model.assumptions.cma import CMA
from aa_model.io.schemas import PublicAllocationConfig


class StubAllocator(AllocationAdapter):
    def __init__(self, config: PublicAllocationConfig) -> None:
        self._weights = pd.Series(config.stub_weights, dtype=float).sort_index()
        self._diagnostics: dict = {"engine": "stub"}

    def fit(self, returns: pd.DataFrame, cma: CMA, constraints: Constraints) -> None:
        self._diagnostics["fit_inputs"] = {
            "returns_shape": tuple(returns.shape) if returns is not None else None,
            "n_constraints": (
                (len(constraints.min_weights) + len(constraints.max_weights))
                if constraints is not None
                else 0
            ),
        }

    def weights(self) -> pd.Series:
        return self._weights.copy()

    def diagnostics(self) -> dict:
        return dict(self._diagnostics)
