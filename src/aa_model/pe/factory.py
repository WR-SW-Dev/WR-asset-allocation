"""PE adapter factory (Phase 7).

Resolves ``base.pe.engine`` into a :class:`PEAdapter` instance. Mirrors
``allocation.factory.make_allocator`` and
``implementation.factory.make_implementation``.
"""

from __future__ import annotations

from aa_model.pe.base import PEAdapter
from aa_model.pe.stairs_adapter import STAIRSAdapter
from aa_model.pe.ta_adapter import TAAdapter


def make_pe_adapter(*, engine: str) -> PEAdapter:
    if engine == "ta":
        return TAAdapter()
    if engine == "stairs":
        return STAIRSAdapter()
    raise ValueError(f"unknown pe.engine: {engine!r}")
