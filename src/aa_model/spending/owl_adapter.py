"""Owl spending rule (SPEC §6 Phase 3c).

"Owl" is the project codename for a Guyton-Klinger–style guardrail
spending policy — the missing ``guardrail`` rule in `spending/rules.py`'s
type comment, repackaged behind the existing :class:`SpendingRule` ABC for
adapter-discipline parity with the other Phase 3 adapters. There is no
external "Owl" Python library; the file lives at
``spending/owl_adapter.py`` for consistency with §4 layout.

Behavior
========

For each quarter ``t = 0..N-1``:

* ``annual_spend_t`` starts at ``cfg.annual_spend_usd`` and evolves only
  at year boundaries (``t % 4 == 0`` for ``t > 0``) in two steps:
  1. inflation update: ``annual_spend_t = annual_spend_{t-1} · (1+inflation_pct)``
  2. guardrail check, against forecast NAV at ``t``:

         current_rate     = annual_spend_t / forecast_nav_t
         initial_rate     = annual_spend_0 / initial_nav_total
         forecast_nav_t   = initial_nav_total · (1 + forecast_quarterly_return_pct)^t

         if current_rate < initial_rate · (1 - lower_band_pct):
             # portfolio grew faster than spending → ratchet up
             annual_spend_t *= (1 + raise_pct)
         elif current_rate > initial_rate · (1 + upper_band_pct):
             # portfolio shrank vs spending → ratchet down
             annual_spend_t *= (1 - cut_pct)
* Within a year (``t % 4 in (1,2,3)``), spending is constant at
  ``annual_spend_year / 4`` per quarter.
* Floor / ceiling clip the per-quarter value (same as flat_real / smoothing).

Path dependence
===============

Same one-step-back shape as :class:`SmoothingRule`:
``annual_spend_year_n`` depends on ``annual_spend_year_{n-1}``. There is
no NAV feedback from the realized run — Owl computes its own
forward-only NAV forecast from ``forecast_quarterly_return_pct`` and
``initial_nav`` (see L15 for why).

``forecast_quarterly_return_pct`` is an **exogenous assumption** supplied
by config; it does NOT derive from fixture returns, the CMA, or any
scenario perturbation. Two runs with different realized return paths
(e.g. ``base`` vs ``public_drawdown``) but the same forecast assumption
produce identical Owl spending series.

The rule is therefore a **pure function** of
``(initial_nav, SpendingConfig + GuardrailConfig, num_quarters,
start_quarter)``: same inputs → same output series. No randomness, no
caching, no ledger mutation, no lookahead.

Discipline (Phase 3 guardrails)
===============================

* **Pure.** No module-level state, no caches.
* **No ledger mutation.** Reads ``ledger.initial_nav`` only — the same
  read-only access the existing :class:`FlatRealRule` and
  :class:`SmoothingRule` are entitled to via the ABC's ``ledger``
  parameter.
* **No path dependence beyond smoothing-style.** Within-quarter
  computation depends only on the prior year's annual spending;
  the year boundary at index ``i`` uses ``forecast_nav_i`` and
  ``annual_spend_{year-1}``.
* **No external dependency.** This is not an adapter to a third-party
  library; it is the canonical implementation of the missing guardrail
  rule.
"""

from __future__ import annotations

import pandas as pd

from aa_model.integration.ledger import QuarterlyLedger
from aa_model.spending.base import SpendingParams, SpendingRule


class OwlRule(SpendingRule):
    """Guyton-Klinger guardrail spending, deterministic minimum form."""

    def quarterly_outflows(self, ledger: QuarterlyLedger, params: SpendingParams) -> pd.Series:
        cfg = params.config
        if cfg.guardrail is None:
            raise ValueError("OwlRule requires spending.guardrail config")
        gr = cfg.guardrail

        initial_nav_total = float(sum(ledger.initial_nav.values()))
        if initial_nav_total <= 0.0:
            raise ValueError(f"OwlRule requires positive initial NAV; got {initial_nav_total}")

        initial_annual_spend = float(cfg.annual_spend_usd)
        initial_rate = initial_annual_spend / initial_nav_total

        idx = [params.start_quarter + i for i in range(params.num_quarters)]
        out: list[float] = []
        annual_spend = initial_annual_spend

        for i in range(params.num_quarters):
            quarter_in_year = i % 4
            # At each year boundary except t=0: inflate, then check guardrail.
            if i > 0 and quarter_in_year == 0:
                annual_spend *= 1.0 + cfg.inflation_pct
                forecast_nav_i = initial_nav_total * (1.0 + gr.forecast_quarterly_return_pct) ** i
                current_rate = annual_spend / forecast_nav_i
                if current_rate < initial_rate * (1.0 - gr.lower_band_pct):
                    annual_spend *= 1.0 + gr.raise_pct
                elif current_rate > initial_rate * (1.0 + gr.upper_band_pct):
                    annual_spend *= 1.0 - gr.cut_pct

            quarterly = annual_spend / 4.0
            quarterly = max(cfg.floor_usd, min(cfg.ceiling_usd, quarterly))
            out.append(quarterly)

        return pd.Series(out, index=idx, dtype=float, name="quarterly_outflow_usd")
