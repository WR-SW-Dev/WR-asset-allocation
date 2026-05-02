"""Takahashi–Alexander PE adapter (Phase 7).

A thin wrapper around the existing ``pe.pacing.project_horizon`` function
that conforms to the ``PEAdapter`` ABC. Behavior is unchanged from the
pre-Phase-7 single-function path; the wrapper only exists so the
orchestrator can dispatch through ``make_pe_adapter`` uniformly.

``cma`` and ``public_equity_path`` are accepted to satisfy the abstract
signature but are not consumed — TA's NAV growth is the constant
``ta_defaults.growth_pct``. See MODEL_DOCUMENTATION.md §Phase 7 design.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd

from aa_model.pe.base import PEAdapter
from aa_model.pe.pacing import project_horizon as _ta_project_horizon

if TYPE_CHECKING:
    from aa_model.assumptions.cma import CMA
    from aa_model.io.schemas import PEPacingConfig


class TAAdapter(PEAdapter):
    """Default engine. Identical to the pre-Phase-7 projection."""

    def project_horizon(
        self,
        pacing: PEPacingConfig,
        horizon_start: pd.Period,
        num_quarters: int,
        *,
        cma: CMA,
        public_equity_path: pd.Series,
    ) -> pd.DataFrame:
        # cma + public_equity_path are intentionally unused — TA growth
        # is config-driven (``ta_defaults.growth_pct``).
        del cma, public_equity_path
        return _ta_project_horizon(pacing, horizon_start, num_quarters)
