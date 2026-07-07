"""Phase MC-1 — Stochastic path generation.

RandomPathGenerator: no global random state, seeded per-generator instance.
Uses numpy.default_rng(seed) for reproducibility.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

import numpy as np

from aa_model.monte_carlo.config import MonteCarloConfig


@dataclass
class RandomPathGenerator:
    """Generate stochastic return, spending, and call paths.

    Parameters
    ----------
    config : MonteCarloConfig
        Configuration including scenarios and seed.
    """

    config: MonteCarloConfig

    def __post_init__(self) -> None:
        if not isinstance(self.config, MonteCarloConfig):
            raise TypeError("config must be MonteCarloConfig")

    def generate_return_path(self, asset_class: str, path_id: int) -> np.ndarray:
        """Generate quarterly returns for one asset class, one path.

        Parameters
        ----------
        asset_class : str
            Key into config.return_scenarios.
        path_id : int
            Path index (0 to num_paths-1).

        Returns
        -------
        np.ndarray
            Array of length horizon_quarters. Each element is the quarterly
            return (e.g., 0.01 = +1% that quarter).

        Raises
        ------
        KeyError
            If asset_class not in return_scenarios.
        """
        if asset_class not in self.config.return_scenarios:
            raise KeyError(f"asset_class '{asset_class}' not in return_scenarios")

        scenario = self.config.return_scenarios[asset_class]
        rng = np.random.default_rng(self._seed_for_path(path_id, asset_class))

        # Quarterly return: annualized / 4
        quarterly_mean = scenario.mean_annual_return / 4.0
        quarterly_vol = scenario.annual_vol / 2.0  # sqrt(4) = 2

        returns = rng.normal(quarterly_mean, quarterly_vol, self.config.horizon_quarters)
        return returns

    def generate_spending_path(
        self, driver: str, base_annual_spend: float, path_id: int
    ) -> np.ndarray:
        """Generate quarterly spending amounts, one path.

        Parameters
        ----------
        driver : str
            Spending scenario label (key into config.spending_scenarios).
        base_annual_spend : float
            Starting annual spending level.
        path_id : int
            Path index.

        Returns
        -------
        np.ndarray
            Quarterly spending amounts (absolute USD, not growth rates).
        """
        if driver not in self.config.spending_scenarios:
            raise KeyError(f"driver '{driver}' not in spending_scenarios")

        scenario = self.config.spending_scenarios[driver]
        rng = np.random.default_rng(self._seed_for_path(path_id, driver))

        # Quarterly growth: annualized / 4
        quarterly_growth_mean = scenario.mean_annual_growth / 4.0
        quarterly_growth_vol = scenario.annual_vol / 2.0

        growth_rates = rng.normal(
            quarterly_growth_mean, quarterly_growth_vol, self.config.horizon_quarters
        )

        # Cumulative inflation/growth on base spend
        spending = np.empty(self.config.horizon_quarters, dtype=float)
        current_spend = base_annual_spend / 4.0  # quarterly starting point
        for q in range(self.config.horizon_quarters):
            spending[q] = current_spend
            current_spend *= 1.0 + growth_rates[q]

        return spending

    def generate_call_path(
        self, pe_sleeve: str, base_commitment: float, path_id: int
    ) -> np.ndarray:
        """Generate quarterly PE capital-call amounts, one path.

        Parameters
        ----------
        pe_sleeve : str
            PE sleeve (key into config.call_scenarios).
        base_commitment : float
            Total commitment to this fund.
        path_id : int
            Path index.

        Returns
        -------
        np.ndarray
            Quarterly call amounts (cumulative % applied to commitment).
        """
        if pe_sleeve not in self.config.call_scenarios:
            raise KeyError(f"pe_sleeve '{pe_sleeve}' not in call_scenarios")

        scenario = self.config.call_scenarios[pe_sleeve]
        rng = np.random.default_rng(self._seed_for_path(path_id, pe_sleeve))

        # Baseline cumulative call % by quarter (from config)
        baseline = np.array(scenario.base_called_pct_by_quarter[: self.config.horizon_quarters])

        # Apply early-call hazard: shift baseline forward with probability
        if scenario.early_call_probability > 0:
            if rng.uniform() < scenario.early_call_probability:
                # Accelerate calls: shift baseline by 1 quarter and cap at 1.0
                baseline = np.concatenate([[baseline[0]], baseline[:-1]])
                baseline = np.minimum(baseline, 1.0)

        # Convert cumulative % to quarterly calls
        calls = np.zeros(self.config.horizon_quarters, dtype=float)
        calls[0] = baseline[0] * base_commitment
        for q in range(1, self.config.horizon_quarters):
            calls[q] = max(0.0, (baseline[q] - baseline[q - 1]) * base_commitment)

        return calls

    def _seed_for_path(self, path_id: int, scenario_name: str) -> int:
        """Derive reproducible seed for (path_id, scenario_name) pair.

        Same base seed + same path_id + same scenario → same sequence,
        byte-stable across processes and machines. Different path_id or
        scenario → different sequence.

        Uses SHA256 rather than the builtin ``hash()`` because CPython
        salts string hashing per process (``PYTHONHASHSEED``), which would
        make seeded replays diverge across runs and break the audit trail.

        Parameters
        ----------
        path_id : int
            Path index.
        scenario_name : str
            Scenario identifier.

        Returns
        -------
        int
            Derived seed in [0, 2^32).
        """
        if self.config.random_seed is None:
            # No replay: use hash of (path_id, scenario) → non-deterministic
            import random

            return random.randint(0, 2**31 - 1)

        # Deterministic and cross-process stable: SHA256 of the combined key.
        combined = f"{self.config.random_seed}|{path_id}|{scenario_name}"
        digest = hashlib.sha256(combined.encode()).digest()
        return int.from_bytes(digest[:4], "big")  # 32-bit seed in [0, 2^32)


def zero_volatility_path(
    annual_return: float, annual_spend: float, horizon_quarters: int
) -> dict[str, np.ndarray]:
    """Generate deterministic baseline path (zero volatility).

    Used to verify that Monte Carlo with vol=0 collapses to deterministic.

    Parameters
    ----------
    annual_return : float
        Annual return (e.g., 0.05 for 5%).
    annual_spend : float
        Annual spending.
    horizon_quarters : int
        Number of quarters.

    Returns
    -------
    dict[str, np.ndarray]
        Keys: "returns", "spending". Both constant across quarters.
    """
    quarterly_return = annual_return / 4.0
    quarterly_spend = annual_spend / 4.0

    returns = np.full(horizon_quarters, quarterly_return, dtype=float)
    spending = np.full(horizon_quarters, quarterly_spend, dtype=float)

    return {"returns": returns, "spending": spending}
