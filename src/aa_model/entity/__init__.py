"""Phase 24 — entity dimension for the Wake Robin study.

Deterministic entity fixtures: perimeter, account scope, balance-sheet
segmentation, and PE commitment exposure. See
``docs/phase_24_entity_study_design_lock.md``.
"""

from aa_model.entity.fixture import (
    PEExposureTotals,
    SegmentTotals,
    canonical_dict,
    canonical_json,
    content_hash,
    load_entity_fixture,
    pe_exposure_totals,
    segment_totals,
)
from aa_model.entity.schemas import (
    BalanceSheetSegmentRecord,
    EntityFixture,
    PECommitmentExposureRecord,
)

__all__ = [
    "BalanceSheetSegmentRecord",
    "EntityFixture",
    "PECommitmentExposureRecord",
    "PEExposureTotals",
    "SegmentTotals",
    "canonical_dict",
    "canonical_json",
    "content_hash",
    "load_entity_fixture",
    "pe_exposure_totals",
    "segment_totals",
]
