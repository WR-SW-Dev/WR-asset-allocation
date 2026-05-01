"""Phase 2 sequential scenario sweep.

Iterates a list of :class:`~aa_model.assumptions.scenario_builder.Scenario`
objects through ``run_orchestrator`` and aggregates the result. The sweep
itself is pure data-flow — no orchestrator branching on scenario identity.

Per the discipline guardrails:
- The ledger remains the sole state spine: liquidity metrics are derived
  from the ledger DataFrame each scenario emits, not from a sidecar tracker.
- One forward pass per scenario; no shared mutable state between scenarios.
- Phase 2 starts sequential. Parallel sweep (joblib) is a future
  optimization; the exit-gate fixture sweeps in well under 60s sequentially.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from aa_model.assumptions.scenario_builder import Scenario
from aa_model.integration.manifest import make_invocation_id
from aa_model.integration.orchestrator import RunResult, run_orchestrator
from aa_model.io.loaders import hash_study_config, load_study_config, resolve_repo_root
from aa_model.spending.liquidity import (
    LIQUID_BUCKETS_DEFAULT,
    LiquidityMetrics,
    compute_liquidity_metrics,
)


@dataclass(frozen=True)
class ScenarioResult:
    name: str
    description: str
    run: RunResult
    metrics: LiquidityMetrics


@dataclass(frozen=True)
class SweepResult:
    sweep_id: str
    output_dir: Path
    base_config_hash: str
    results: list[ScenarioResult]


def _end_nav_by_quarter(ledger_df: pd.DataFrame) -> pd.DataFrame:
    """Wide form of end-of-quarter NAV per bucket, derived from the long ledger."""
    if ledger_df.empty:
        return pd.DataFrame()
    last = ledger_df.groupby(["quarter", "bucket"], sort=True).tail(1)
    wide = last.pivot(index="quarter", columns="bucket", values="nav_end_usd")
    return wide.sort_index().ffill().fillna(0.0)


def _annual_spend_from_ledger(ledger_df: pd.DataFrame) -> pd.Series:
    """Per-quarter annualized spend rate, derived from the ledger's spend rows.

    Spending rows carry negative amounts (cash outflow); negate and × 4 to
    express the quarter's spend as an annual rate.
    """
    if ledger_df.empty:
        return pd.Series(dtype=float)
    spend = ledger_df[ledger_df["flow_type"] == "spend"]
    if spend.empty:
        # No spending → return zero per quarter so coverage math is well-defined.
        quarters = sorted(ledger_df["quarter"].unique())
        return pd.Series(0.0, index=quarters)
    quarterly = -spend.groupby("quarter")["amount_usd"].sum()
    return (quarterly * 4.0).sort_index()


def _initial_nav_from_ledger(ledger_df: pd.DataFrame) -> float:
    if ledger_df.empty:
        return 0.0
    first_q = ledger_df["quarter"].min()
    sub = ledger_df[ledger_df["quarter"] == first_q]
    first_per_bucket = sub.groupby("bucket")["nav_start_usd"].first()
    return float(first_per_bucket.sum())


def _metrics_for_run(rr: RunResult, *, floor_months: float) -> LiquidityMetrics:
    end_nav = _end_nav_by_quarter(rr.ledger)
    annual_spend = _annual_spend_from_ledger(rr.ledger)
    initial = _initial_nav_from_ledger(rr.ledger)
    return compute_liquidity_metrics(
        end_nav,
        annual_spend,
        floor_months=floor_months,
        initial_nav_usd=initial,
        liquid_buckets=LIQUID_BUCKETS_DEFAULT,
    )


def run_scenario_sweep(
    base_config_path: Path,
    scenarios: list[Scenario],
    *,
    invocation_id: str | None = None,
    dry_run: bool = False,
) -> SweepResult:
    """Run every scenario sequentially and collect results.

    Each scenario's run id is suffixed with ``-{scenario_name}`` so the
    distinct run dirs remain auditable. ``invocation_id`` (if provided)
    becomes the shared timestamp/nonce stem for the sweep.
    """
    base_config_path = Path(base_config_path).resolve()
    repo_root = resolve_repo_root(base_config_path)

    base_cfg = load_study_config(base_config_path)
    base_cfg_hash, _ = hash_study_config(base_cfg)
    floor_months = float(base_cfg.base.liquidity.floor_months)

    stem = invocation_id if invocation_id is not None else make_invocation_id()
    sweep_id = f"sweep-{stem}"
    out_dir = repo_root / "data" / "processed" / "sweeps" / sweep_id

    results: list[ScenarioResult] = []
    for sc in scenarios:
        rr = run_orchestrator(
            base_config_path,
            scenario=sc,
            invocation_id=f"{stem}-{sc.name}",
            dry_run=dry_run,
        )
        metrics = _metrics_for_run(rr, floor_months=floor_months)
        results.append(
            ScenarioResult(
                name=sc.name,
                description=sc.description,
                run=rr,
                metrics=metrics,
            )
        )

    return SweepResult(
        sweep_id=sweep_id,
        output_dir=out_dir,
        base_config_hash=base_cfg_hash,
        results=results,
    )
