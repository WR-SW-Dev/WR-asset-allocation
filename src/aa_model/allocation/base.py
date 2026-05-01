"""AllocationAdapter ABC — the Phase 1 stub is the reference implementation.

External optimizer adapters (riskfolio, cvxportfolio, skfolio, …) added in
Phase 3 conform to this same surface and run parity tests against the stub.
SPEC §9.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

import pandas as pd

from aa_model.allocation.constraints import Constraints
from aa_model.assumptions.cma import CMA


class AllocationAdapter(ABC):
    @abstractmethod
    def fit(self, returns: pd.DataFrame, cma: CMA, constraints: Constraints) -> None:
        """Fit the allocator to historical/forward returns + assumptions + constraints."""

    @abstractmethod
    def weights(self) -> pd.Series:
        """Return the fitted weights. Index = bucket; values sum to 1.0."""

    @abstractmethod
    def diagnostics(self) -> dict:
        """Solver status, dual values, etc. Free-form for now."""
