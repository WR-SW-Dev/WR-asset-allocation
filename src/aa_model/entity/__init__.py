"""Phase 24 — entity dimension for the Wake Robin study.

Deterministic entity fixtures: perimeter, account scope, balance-sheet
segmentation, and PE commitment exposure — plus the core allocation lenses
(balance-sheet, allocation-vs-target, liquidity). See
``docs/phase_24_entity_study_design_lock.md``.
"""

from aa_model.entity.bridge import holdings_from_positions
from aa_model.entity.crosswalk import liquidity_tier_for, policy_class_for
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
    BurnRate,
    CashFlow,
    CustodianReconResult,
    HoldingsClassGroup,
    HoldingsDetail,
    LiquidityLens,
    LiquidityProjectionLens,
    allocation_vs_target_lens,
    balance_sheet_lens,
    burn_rate_lens,
    cash_flow_lens,
    custodian_reconciliation_lens,
    holdings_detail_lens,
    liquidity_lens,
    liquidity_projection_lens,
)
from aa_model.entity.schemas import (
    BalanceSheetSegmentRecord,
    BurnCategoryRecord,
    CashFlowAssumptions,
    CustodianReconciliation,
    EntityFixture,
    EntityPolicyConfig,
    HoldingRecord,
    PECommitmentExposureRecord,
    QuarterProjectionRecord,
)

__all__ = [
    "AllocationVsTarget",
    "AllocationVsTargetRow",
    "BalanceSheetLens",
    "BalanceSheetSegmentRecord",
    "BurnCategoryRecord",
    "BurnRate",
    "CashFlow",
    "CashFlowAssumptions",
    "CustodianReconResult",
    "CustodianReconciliation",
    "EntityFixture",
    "EntityPolicyConfig",
    "HoldingRecord",
    "HoldingsClassGroup",
    "HoldingsDetail",
    "LiquidityLens",
    "LiquidityProjectionLens",
    "PECommitmentExposureRecord",
    "PEExposureTotals",
    "QuarterProjectionRecord",
    "SegmentTotals",
    "allocation_vs_target_lens",
    "balance_sheet_lens",
    "burn_rate_lens",
    "cash_flow_lens",
    "custodian_reconciliation_lens",
    "canonical_dict",
    "canonical_json",
    "content_hash",
    "holdings_detail_lens",
    "holdings_from_positions",
    "liquidity_tier_for",
    "policy_class_for",
    "liquidity_lens",
    "liquidity_projection_lens",
    "load_entity_fixture",
    "load_entity_policy",
    "pe_exposure_totals",
    "segment_totals",
]
