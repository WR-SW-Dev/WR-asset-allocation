"""Phase MC-1 — Monte Carlo liquidity stress framework.

Public API:
  - MonteCarloConfig, ReturnScenario, SpendingScenario, CallTimingScenario
  - RandomPathGenerator
  - MonteCarloResult, MonteCarloPathResult, MonteCarloManifest
  - compute_monte_carlo()
"""

from aa_model.monte_carlo.config import (
    CallTimingScenario,
    MonteCarloConfig,
    ReturnScenario,
    SpendingScenario,
)
from aa_model.monte_carlo.random_paths import RandomPathGenerator, zero_volatility_path
from aa_model.monte_carlo.result import (
    MonteCarloManifest,
    MonteCarloPathResult,
    MonteCarloResult,
)
from aa_model.monte_carlo.runner import compute_monte_carlo

__all__ = [
    "MonteCarloConfig",
    "ReturnScenario",
    "SpendingScenario",
    "CallTimingScenario",
    "RandomPathGenerator",
    "MonteCarloPathResult",
    "MonteCarloResult",
    "MonteCarloManifest",
    "compute_monte_carlo",
    "zero_volatility_path",
]
