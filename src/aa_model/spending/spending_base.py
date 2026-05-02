"""Phase 12 / L19 — spending-base computation.

Pure helper that converts an end-of-quarter NAV-by-bucket series and
static CMA tags (liquidity tier, income_producing flag) into the dollar
denominator Owl uses for its withdrawal-rate trigger.

The helper is consumed only by ``OwlRule`` (Owl is the only spending
rule with a rate concept). flat_real and smoothing have no rate concept
and never call into this module.

Phase 4a state-flow contract preservation
=========================================

This module reads no ledger state. The caller (``OwlRule``) passes in
``ledger.end_nav_through(prior_q)`` — the same closed-prior-quarter
view Owl already consumes. CMA tags are static config, not ledger
state, so the closed-prior-quarter contract is unaffected.

Phase 12 ships four modes
=========================

* ``"total_nav"`` (default) — sum of every bucket's NAV. Backward-
  compatible with Phase 11.
* ``"liquid_nav"`` — sum of buckets tagged ``liquidity == "liquid"``.
* ``"liquid_plus_income_producing_nav"`` — buckets tagged ``"liquid"``
  OR ``income_producing == True``. **Includes the NAV of income-
  producing buckets; does NOT measure actual distributable income.**
  Stabilized real estate tagged ``income_producing=True`` contributes
  its appraised NAV — overstating spending capacity vs. true
  distributable yield. The structurally correct fix is Phase 12.5.
* ``"custom_policy"`` — per-bucket inclusion-weight blend. Weights are
  bucket-keyed; unspecified buckets default to weight 0; weights are
  inclusion fractions, not allocation weights, so they do not sum to 1.

``"distributable_income"`` is parked in the Literal but raises
``NotImplementedError`` — Phase 12.5 lands the new
``distribution_inflow`` ledger flow type.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SpendingBaseBreakdown:
    """Pure data carrier surfaced into ``OwlRule.diagnostics()``."""

    base_usd: float
    excluded_by_tier_usd: dict[str, float]
    excluded_by_income_flag_usd: dict[bool, float]


def _rollup_by_tier(
    excluded_per_bucket: pd.Series, cma_liquidity: pd.Series | None
) -> dict[str, float]:
    """Sum excluded dollars by liquidity tier. Drops zero-tier groups."""
    if cma_liquidity is None or cma_liquidity.empty:
        return {}
    aligned = cma_liquidity.reindex(excluded_per_bucket.index)
    grouped = excluded_per_bucket.groupby(aligned, dropna=True).sum()
    return {str(k): float(v) for k, v in grouped.items() if float(v) != 0.0}


def _rollup_by_income_flag(
    excluded_per_bucket: pd.Series, cma_income_producing: pd.Series | None
) -> dict[bool, float]:
    """Sum excluded dollars by income_producing flag. Drops zero-flag groups."""
    if cma_income_producing is None or cma_income_producing.empty:
        return {}
    aligned = cma_income_producing.reindex(excluded_per_bucket.index).fillna(False)
    aligned = aligned.astype(bool)
    grouped = excluded_per_bucket.groupby(aligned).sum()
    return {bool(k): float(v) for k, v in grouped.items() if float(v) != 0.0}


def compute_spending_base(
    nav_by_bucket: pd.Series,
    cma_liquidity: pd.Series | None,
    cma_income_producing: pd.Series | None,
    spending_base: str | None,
    spending_base_weights: dict[str, float] | None,
) -> SpendingBaseBreakdown:
    """Pure function. No ledger reads beyond ``nav_by_bucket``. No
    CMA mutation. No state.

    Args:
        nav_by_bucket: index = bucket, value = USD. Caller passes in
            either ``ledger.end_nav_through(prior_q)`` (current-rate
            denominator) or the initial-NAV series (initial-rate
            denominator).
        cma_liquidity: index = bucket, value = liquidity tier. Required
            for any non-``"total_nav"`` mode.
        cma_income_producing: index = bucket, value = bool. Required
            for ``"liquid_plus_income_producing_nav"``.
        spending_base: GuardrailConfig.spending_base. ``None`` is
            treated as ``"total_nav"``.
        spending_base_weights: bucket-keyed inclusion fractions. Only
            consumed when ``spending_base == "custom_policy"``.

    Returns:
        SpendingBaseBreakdown carrying the dollar base plus the two
        diagnostic exclusion rollups.

    Raises:
        ValueError: on missing required inputs for a non-default mode.
        NotImplementedError: when ``spending_base == "distributable_income"``
            (Phase 12.5).
    """
    if spending_base is None or spending_base == "total_nav":
        return SpendingBaseBreakdown(
            base_usd=float(nav_by_bucket.sum()),
            excluded_by_tier_usd={},
            excluded_by_income_flag_usd={},
        )

    if cma_liquidity is None or cma_liquidity.empty:
        raise ValueError(
            f"spending_base={spending_base!r} requires cma.liquidity to be "
            f"populated; got empty/None"
        )

    if spending_base == "liquid_nav":
        weights_per_bucket = (cma_liquidity == "liquid").astype(float)
    elif spending_base == "liquid_plus_income_producing_nav":
        if cma_income_producing is None or cma_income_producing.empty:
            raise ValueError(
                "spending_base='liquid_plus_income_producing_nav' requires "
                "cma.income_producing to be populated"
            )
        liquid_mask = (cma_liquidity == "liquid").astype(bool)
        income_mask = cma_income_producing.reindex(nav_by_bucket.index).fillna(False)
        income_mask = income_mask.astype(bool)
        liquid_aligned = liquid_mask.reindex(nav_by_bucket.index).fillna(False).astype(bool)
        weights_per_bucket = (liquid_aligned | income_mask).astype(float)
    elif spending_base == "custom_policy":
        if spending_base_weights is None:
            raise ValueError("spending_base='custom_policy' requires weights")
        weights_per_bucket = pd.Series(
            {b: float(spending_base_weights.get(b, 0.0)) for b in nav_by_bucket.index},
            dtype=float,
        )
    elif spending_base == "distributable_income":
        raise NotImplementedError(
            "spending_base='distributable_income' is Phase 12.5 — requires "
            "the new `distribution_inflow` ledger flow type"
        )
    else:
        raise ValueError(f"unknown spending_base {spending_base!r}")

    weights_per_bucket = weights_per_bucket.reindex(nav_by_bucket.index).fillna(0.0)
    included_per_bucket = nav_by_bucket * weights_per_bucket
    excluded_per_bucket = nav_by_bucket * (1.0 - weights_per_bucket)
    return SpendingBaseBreakdown(
        base_usd=float(included_per_bucket.sum()),
        excluded_by_tier_usd=_rollup_by_tier(excluded_per_bucket, cma_liquidity),
        excluded_by_income_flag_usd=_rollup_by_income_flag(
            excluded_per_bucket, cma_income_producing
        ),
    )
