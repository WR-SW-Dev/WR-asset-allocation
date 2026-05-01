"""Allocation constraint container.

The stub allocator ignores constraints; this type exists to satisfy the
``AllocationAdapter.fit`` contract in SPEC §9 so Phase 3 adapters can consume it.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class Constraints:
    """Box bounds on allocation weights.

    Attributes:
        min_weights: per-bucket lower bound.
        max_weights: per-bucket upper bound.
    """

    min_weights: dict[str, float] = field(default_factory=dict)
    max_weights: dict[str, float] = field(default_factory=dict)
