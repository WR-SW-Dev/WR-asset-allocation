"""Allocation engine factory.

Resolves ``allocation.engine`` (from base config) into an
:class:`AllocationAdapter` instance. Each non-stub adapter is imported
lazily so the package can run without optional optimizer dependencies.
"""

from __future__ import annotations

from aa_model.allocation.base import AllocationAdapter
from aa_model.allocation.stub import StubAllocator
from aa_model.io.schemas import PublicAllocationConfig


def make_allocator(config: PublicAllocationConfig, *, engine: str) -> AllocationAdapter:
    if engine == "stub":
        return StubAllocator(config)
    if engine == "riskfolio":
        # Lazy import: keeps riskfolio-lib optional unless explicitly enabled.
        from aa_model.allocation.riskfolio_adapter import RiskfolioAdapter

        return RiskfolioAdapter(config)
    if engine == "cvxportfolio":
        # Lazy import: keeps cvxpy / cvxportfolio optional. Phase 4b.
        from aa_model.allocation.cvxportfolio_adapter import CvxportfolioAllocator

        return CvxportfolioAllocator(config)
    raise ValueError(f"unknown allocation engine: {engine!r}")
