"""AllocationAdapter ABC — the Phase 1 stub is the reference implementation.

External optimizer adapters (riskfolio, cvxportfolio, skfolio, …) added in
Phase 3 conform to this same surface and run parity tests against the stub.
SPEC §9.

Phase 4b extends the surface with a per-quarter ``target_at`` method
that lets a cost-aware allocator observe the realized pre-rebalance
state. The default implementation returns ``self.weights()`` — i.e. the
cost-blind policy weights — so existing adapters (stub, riskfolio)
inherit the new method without modification. Only the cost-aware
``cvxportfolio`` engine overrides ``target_at``. See
MODEL_DOCUMENTATION.md §Phase 4b design.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

import pandas as pd

from aa_model.allocation.constraints import Constraints
from aa_model.assumptions.cma import CMA

if TYPE_CHECKING:
    from aa_model.implementation.base import CostModel
    from aa_model.integration.ledger import QuarterlyLedger
    from aa_model.io.schemas import PublicAllocationConfig


@dataclass(frozen=True)
class AllocationParams:
    """Inputs the per-quarter ``target_at`` call needs beyond the ledger
    and current state. Mirrors :class:`SpendingParams`.
    """

    config: PublicAllocationConfig
    start_quarter: pd.Period
    num_quarters: int


class AllocationAdapter(ABC):
    @abstractmethod
    def fit(self, returns: pd.DataFrame, cma: CMA, constraints: Constraints) -> None:
        """Fit the allocator to historical/forward returns + assumptions + constraints."""

    @abstractmethod
    def weights(self) -> pd.Series:
        """Return the fitted weights. Index = bucket; values sum to 1.0.

        This is the **cost-blind policy reference**. Phase 1–3 callers
        consume this directly; Phase 4b orchestrator uses it only as the
        ``w_policy`` input to :meth:`target_at`.
        """

    @abstractmethod
    def diagnostics(self) -> dict:
        """Solver status, dual values, etc. Free-form for now."""

    def target_at(
        self,
        ledger: QuarterlyLedger,
        params: AllocationParams,
        quarter: pd.Period,
        current_dollars: pd.Series,
        cost_model: CostModel,
    ) -> pd.Series:
        """Per-quarter target weights (Phase 4b).

        Default: returns :meth:`weights` (cost-blind passthrough). Adapters
        that introduce cost-aware behavior override this method; stub /
        riskfolio inherit the default and produce the same target every
        quarter, matching their pre-Phase-4b behavior.

        Contract for cost-aware overrides (see MODEL_DOCUMENTATION.md
        §Phase 4b design):

        * Reads only ``current_dollars``, ``self.weights()`` (policy),
          ``cost_model``, and the ``params.config.policy_loss_lambda``
          field. Does **not** read ``ledger`` (path-blindness anchor).
        * Returns canonicalized weights (rounded, sum-to-1, ≥ 0) so the
          ledger sees deterministic bytes regardless of solver
          implementation.
        * At ``quarter == params.start_quarter`` returns
          :meth:`weights` (no current-state context to reason about).
        """
        return self.weights()
