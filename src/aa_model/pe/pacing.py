"""Fixed-commitment PE pacing for Phase 1.

Phase 1 has no recommitment optimizer. The configured ``funds`` list is the
full commitment schedule. This module projects every fund via the TA model
and filters the projection to the run horizon, attaching the sleeve each
fund maps to. The orchestrator consumes the result and emits the ledger
rows itself so that PE flows interleave with returns / spending / rebalance
in canonical order within each quarter.
"""

from __future__ import annotations

import pandas as pd

from aa_model.io.schemas import PEPacingConfig
from aa_model.pe.ta_model import project_funds


def project_horizon(
    pacing: PEPacingConfig,
    horizon_start: pd.Period,
    num_quarters: int,
) -> pd.DataFrame:
    """Return TA projections for configured funds, filtered to the horizon.

    Adds a ``sleeve`` column from each fund's config. Empty input returns
    an empty frame with the projection schema.
    """
    proj = project_funds(pacing.funds, pacing.ta_defaults)
    if proj.empty:
        return proj

    horizon_strs = {str(horizon_start + i) for i in range(num_quarters)}
    proj = proj[proj["quarter"].isin(horizon_strs)].copy()
    fund_to_sleeve = {f.name: f.sleeve for f in pacing.funds}
    proj["sleeve"] = proj["fund_name"].map(fund_to_sleeve)
    return proj.reset_index(drop=True)
