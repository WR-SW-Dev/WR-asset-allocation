"""PEAdapter ABC (Phase 7).

The PE projection layer was a single function (``pacing.project_horizon``)
through Phase 6. Phase 7 introduces an adapter pattern so the
deterministic Takahashi–Alexander model (``ta``) and the new
public-equity-coupled STAIRS variant (``stairs``) can be selected via
``base.pe.engine``. The output schema (``PROJECTION_COLUMNS``) is
unchanged; the orchestrator's per-quarter ledger emission code does not
branch on engine.

Both adapters take the same call signature. The TA adapter ignores
``cma`` and ``public_equity_path``; the STAIRS adapter requires both.
See MODEL_DOCUMENTATION.md §Phase 7 design.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    from aa_model.assumptions.cma import CMA
    from aa_model.io.schemas import PEPacingConfig


class PEAdapter(ABC):
    @abstractmethod
    def project_horizon(
        self,
        pacing: PEPacingConfig,
        horizon_start: pd.Period,
        num_quarters: int,
        *,
        cma: CMA,
        public_equity_path: pd.Series,
    ) -> pd.DataFrame:
        """Return PE projections (``pe.ta_model.PROJECTION_COLUMNS``
        schema) for the configured funds, filtered to the run horizon.

        Args:
          pacing: fund schedule + ta_defaults + (for STAIRS)
            stairs_defaults. Re-used by both engines.
          horizon_start, num_quarters: same horizon contract as the
            pre-Phase-7 ``project_horizon`` function.
          cma: validated capital market assumptions (Phase 5). TA
            ignores; STAIRS reads ``expected_returns_annual``.
          public_equity_path: realized quarterly public_equity returns
            indexed by quarter (``pd.Period`` index). TA ignores;
            STAIRS reads it for the coupling term. Quarters not in
            the index are treated as ``excess = 0``
            (CMA-expectation default).

        Returns:
          Tidy frame with the canonical ``PROJECTION_COLUMNS`` schema,
          one row per (fund, quarter) within the run horizon, plus the
          ``sleeve`` column derived from each fund's config.
        """

    def diagnostics(self) -> dict:
        """Optional. Adapter-specific diagnostics surfaced on report.md.
        Defaults to ``{"engine": <class name>}``; STAIRS overrides to
        include the growth-clip activation count.
        """
        return {"engine": type(self).__name__}
