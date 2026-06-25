"""Phase MC-1 — Monte Carlo configuration schemas.

Deterministic, frozen, hashable. Same config + same seed = same paths.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

_STRICT_CONFIG = {"extra": "forbid"}


@dataclass(frozen=True)
class ReturnScenario:
    """Asset-class return assumption for stochastic paths.

    Parameters
    ----------
    asset_class : str
        One of: cash, public_bond, public_equity, pe_buyout, pe_venture,
        pe_growth, pe_credit, pe_re, pe_infra, pe_secondary.
    mean_annual_return : float
        Long-term expected annual return (e.g., 0.07 for 7%).
    annual_vol : float
        Annualized standard deviation (e.g., 0.15 for 15%).
    shock_percentile : float | None
        Percentile for downside scenario (e.g., 0.05 for worst-5%).
        None means no shock; paths use mean_annual_return only.
    """

    asset_class: str
    mean_annual_return: float
    annual_vol: float
    shock_percentile: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.asset_class, str) or not self.asset_class.strip():
            raise ValueError("asset_class must be non-empty string")
        if self.mean_annual_return <= -1.0:
            raise ValueError("mean_annual_return must be > -1.0")
        if self.annual_vol < 0.0:
            raise ValueError("annual_vol must be >= 0.0")
        if self.shock_percentile is not None and not (0.0 <= self.shock_percentile <= 1.0):
            raise ValueError("shock_percentile must be in [0, 1] or None")


@dataclass(frozen=True)
class SpendingScenario:
    """Spending shock scenario for stochastic paths.

    Parameters
    ----------
    driver : str
        Scenario label (e.g., "inflation", "discretionary", "stress").
    mean_annual_growth : float
        Base annual growth rate (e.g., 0.03 for 3% inflation).
    annual_vol : float
        Volatility around base (e.g., 0.01 for ±1%).
    shock_multiplier : float | None
        Spending multiplier in stress case (e.g., 1.5× base spend).
        None means no stress multiplier.
    """

    driver: str
    mean_annual_growth: float
    annual_vol: float
    shock_multiplier: float | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.driver, str) or not self.driver.strip():
            raise ValueError("driver must be non-empty string")
        if self.mean_annual_growth <= -1.0:
            raise ValueError("mean_annual_growth must be > -1.0")
        if self.annual_vol < 0.0:
            raise ValueError("annual_vol must be >= 0.0")
        if self.shock_multiplier is not None and self.shock_multiplier <= 0.0:
            raise ValueError("shock_multiplier must be > 0 or None")


@dataclass(frozen=True)
class CallTimingScenario:
    """PE capital-call timing hazard scenario.

    Parameters
    ----------
    pe_sleeve : str
        PE sleeve (pe_buyout, pe_venture, pe_growth, pe_credit, pe_re,
        pe_infra, pe_secondary).
    base_called_pct_by_quarter : list[float]
        Baseline cumulative call % by quarter [0, 1]. Length must match
        horizon_quarters. E.g., [0.2, 0.4, 0.6, 0.8, 1.0, ...].
    hazard_rate_median_years : float
        Median time-to-full-call (years). Used to compute call timing
        volatility around baseline. E.g., 2.5 for mid-market buyout.
    early_call_probability : float
        Probability of accelerated call schedule (e.g., 0.1 for 10%).
    """

    pe_sleeve: str
    base_called_pct_by_quarter: list[float]
    hazard_rate_median_years: float
    early_call_probability: float

    def __post_init__(self) -> None:
        if not isinstance(self.pe_sleeve, str) or not self.pe_sleeve.strip():
            raise ValueError("pe_sleeve must be non-empty string")
        if not isinstance(self.base_called_pct_by_quarter, list) or not self.base_called_pct_by_quarter:
            raise ValueError("base_called_pct_by_quarter must be non-empty list")
        for pct in self.base_called_pct_by_quarter:
            if not (0.0 <= pct <= 1.0):
                raise ValueError("all percentages must be in [0, 1]")
        if not all(self.base_called_pct_by_quarter[i] <= self.base_called_pct_by_quarter[i + 1]
                   for i in range(len(self.base_called_pct_by_quarter) - 1)):
            raise ValueError("base_called_pct_by_quarter must be monotonically non-decreasing")
        if self.hazard_rate_median_years <= 0.0:
            raise ValueError("hazard_rate_median_years must be > 0")
        if not (0.0 <= self.early_call_probability <= 1.0):
            raise ValueError("early_call_probability must be in [0, 1]")


@dataclass(frozen=True)
class MonteCarloConfig:
    """Master Monte Carlo configuration.

    All fields are frozen (immutable). Hash is computed from canonical
    representation for audit trail and reproducibility.

    Parameters
    ----------
    num_paths : int
        Number of stochastic paths to generate. Must be in [100, 10_000].
    horizon_quarters : int
        Time horizon in quarters. Must match ledger horizon and be in [4, 40].
    random_seed : int | None
        Seed for numpy.default_rng(). If None, no replay guarantee.
        If int, same seed produces identical paths (byte-stable).
    return_scenarios : dict[str, ReturnScenario]
        Asset-class return assumptions keyed by asset_class.
    spending_scenarios : dict[str, SpendingScenario]
        Spending shock scenarios keyed by driver.
    call_scenarios : dict[str, CallTimingScenario]
        PE call timing scenarios keyed by pe_sleeve.
    """

    num_paths: int
    horizon_quarters: int
    random_seed: int | None
    return_scenarios: dict[str, ReturnScenario]
    spending_scenarios: dict[str, SpendingScenario]
    call_scenarios: dict[str, CallTimingScenario]

    def __post_init__(self) -> None:
        if not (10 <= self.num_paths <= 10_000):
            raise ValueError(f"num_paths must be in [10, 10_000]; got {self.num_paths}")
        if not (4 <= self.horizon_quarters <= 40):
            raise ValueError(f"horizon_quarters must be in [4, 40]; got {self.horizon_quarters}")
        if self.random_seed is not None and not isinstance(self.random_seed, int):
            raise ValueError(f"random_seed must be int or None; got {type(self.random_seed)}")
        if not isinstance(self.return_scenarios, dict) or not self.return_scenarios:
            raise ValueError("return_scenarios must be non-empty dict")
        if not all(isinstance(v, ReturnScenario) for v in self.return_scenarios.values()):
            raise ValueError("all return_scenarios values must be ReturnScenario")
        if not isinstance(self.spending_scenarios, dict) or not self.spending_scenarios:
            raise ValueError("spending_scenarios must be non-empty dict")
        if not all(isinstance(v, SpendingScenario) for v in self.spending_scenarios.values()):
            raise ValueError("all spending_scenarios values must be SpendingScenario")
        if not isinstance(self.call_scenarios, dict) or not self.call_scenarios:
            raise ValueError("call_scenarios must be non-empty dict")
        if not all(isinstance(v, CallTimingScenario) for v in self.call_scenarios.values()):
            raise ValueError("all call_scenarios values must be CallTimingScenario")

    @property
    def config_hash(self) -> str:
        """Canonical SHA256 hash of this config (excluding seed).

        Used for audit trail: if hash changes, inputs changed. Excludes
        seed to allow replays with different seeds to share the config hash.
        """
        canonical = (
            f"{self.num_paths}|{self.horizon_quarters}|"
            f"{sorted(self.return_scenarios.keys())}|"
            f"{sorted(self.spending_scenarios.keys())}|"
            f"{sorted(self.call_scenarios.keys())}"
        )
        return hashlib.sha256(canonical.encode()).hexdigest()
