"""Phase 24 — entity dimension for the Wake Robin study.

Deterministic entity fixtures: perimeter, account scope, balance-sheet
segmentation, and PE commitment exposure — plus the core allocation lenses
(balance-sheet, allocation-vs-target, liquidity). See
``docs/phase_24_entity_study_design_lock.md``.
"""

from aa_model.entity.fixture import (
    PEExposureTotals,
    SegmentTotals,
    canonical_dict,
    canonical_json,
    content_hash,
    load_entity_fixture,
    load_entity_policy,
    pe_exposure_totals,
    segment_totals,
)
from aa_model.entity.lenses import (
    AllocationVsTarget,
    AllocationVsTargetRow,
    BalanceSheetLens,
    LiquidityLens,
    allocation_vs_target_lens,
    balance_sheet_lens,
    liquidity_lens,
)
from aa_model.entity.schemas import (
    BalanceSheetSegmentRecord,
    EntityFixture,
    EntityPolicyConfig,
    PECommitmentExposureRecord,
)

__all__ = [
    "AllocationVsTarget",
    "AllocationVsTargetRow",
    "BalanceSheetLens",
    "BalanceSheetSegmentRecord",
    "EntityFixture",
    "EntityPolicyConfig",
    "LiquidityLens",
    "PECommitmentExposureRecord",
    "PEExposureTotals",
    "SegmentTotals",
    "allocation_vs_target_lens",
    "balance_sheet_lens",
    "canonical_dict",
    "canonical_json",
    "content_hash",
    "liquidity_lens",
    "load_entity_fixture",
    "load_entity_policy",
    "pe_exposure_totals",
    "segment_totals",
]
