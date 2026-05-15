# Phase MC-0 — Design Lock — Monte Carlo Liquidity Stress Architecture

> **Status: LOCKED, pre-implementation.** Monte Carlo framework design
> complete 2026-05-15. Implementation (MC-1/MC-2/MC-3) proceeds in four
> phases with synthetic / scrubbed fixtures. No live client data consumed
> in Monte Carlo stochastic path generation. Outputs remain advisory until
> deterministic spine (L19 row classification, L20 workbook reconciliation,
> Phase 23 PE commitment data) validated.

## Standing constraint inheritance

This phase inherits from `docs/wake_robin_liquidity_architecture.png` —
the seven-layer SFO model and liquidity-coverage principles:

```
NAV is not liquidity.
Appraisal value is not spending capacity.
Semi-liquid availability depends on gates, notice periods, and fund
conditions the model cannot assert.
```

Phase MC-0 also inherits Phase 21 reconciliation-gate semantics: Monte
Carlo scenarios respect deterministic policy thresholds but do not promote
stochastic outputs to hard family-unit decisions until live data validates.

## One-line goal

Build a deterministic, reproducible, seeded Monte Carlo engine that
stresses the existing deterministic liquidity-coverage model using
synthetic and parameterized spending/return/call/distribution paths,
producing advisory breach-probability and reserve-requirement reports that
remain explicitly advisory until the cash-flow, entity, and PE commitment
data are reconciled on real positions.

## Where Monte Carlo slots

```
Existing (Phases 15–22):  deterministic liquidity coverage
                           ├─ positions → tier NAV
                           ├─ obligations → coverage ratios
                           ├─ manager terms → semi-liquid advisory
                           ├─ PE pacing → next-12m capital calls
                           └─ reconciliation gates → breach/warning

Phase MC (new):           stochastic liquidity stress
                           ├─ deterministic input snapshot
                           ├─ synthetic return paths (CMA assumptions)
                           ├─ spending-shock scenarios
                           ├─ PE call timing / distribution multipliers
                           ├─ liquidity haircuts
                           └─ per-path breach & reserve metrics

Optional (Phase 23 ready): swap synthetic fixtures → client actuals
```

Monte Carlo is **opt-in** from the orchestrator. The deterministic layer
remains the operating spine.

## Architecture: stochastic vs deterministic boundary

### What stays deterministic (no change)

- **Position tier NAV** — as-of snapshot, unchanged
- **Spending base** — distributable_income or net-flow, from Phase 12
- **Manager terms** — lockup, notice, gates from Phase 22
- **PE capital-call obligation** — deterministic next-12m window (Phase 19/20)
- **Reconciliation gates** — policy thresholds, breach/warning rules (Phase 21)

### What becomes stochastic (Phase MC)

- **Public market returns** — paths per asset class (cash, public_bond, ...)
- **PE call timing** — hazard-rate multipliers applied to next-12m calls
- **PE distribution delays** — lag scenarios on committed / NAV distributions
- **Spending shocks** — annual spend rate volatility + inflation stress
- **Liquidity haircuts** — realized vs marked values on semi-liquid / illiquid tiers

### What is synthetic now, real later

| Driver | Scope now | Deferred until |
|---|---|---|
| Public returns | CMA long-term expected return / vol / correlation | (benchmarking only; no real prices) |
| PE calls | Baseline from Phase 19 + timing hazard | Phase 23 actuals + call history |
| Spending shocks | ±X% annual spend variation | client distributable income rules (L19) |
| Liquidity haircuts | fixed % per tier | real manager terms + notice periods |
| Distribution delay | fixed lags per fund status | Phase 23 commitment actuals |
| RE / OpCo shocks | placeholder distributions | entity-specific cash-flow rules (L19) |
| Entity cash-flow gaps | absent (zero by design) | L19 row classifications |
| Capital-call coverage | deterministic from Phase 19 | L20 workbook validation |

## Input specification

### `MonteCarloConfig`

```python
@dataclass(frozen=True)
class MonteCarloConfig:
    num_paths: int                        # [100, 10_000]
    horizon_quarters: int                 # [4, 40]; matches ledger horizon
    random_seed: int | None               # None → no replay; int → reproducible
    
    return_scenarios: dict[str, ReturnScenario]     # by asset class
    spending_scenarios: dict[str, SpendingScenario] # by driver
    call_scenarios: dict[str, CallTimingScenario]   # by PE sleeve
    
    config_hash: str                      # SHA256 of all above
    fixture_hash: str                     # SHA256 of all synthetic inputs
```

### `ReturnScenario` (asset-class returns)

```python
@dataclass(frozen=True)
class ReturnScenario:
    asset_class: str                      # cash | public_bond | public_equity | pe_*
    mean_annual_return: float             # CMA long-term assumption
    annual_vol: float                     # annualized standard deviation
    shock_percentile: float | None        # p5 / p25 downturn; None → no shock
```

Example:

```
asset_class=public_equity
  mean_annual_return = 0.07   # CMA 7% real
  annual_vol = 0.15
  shock_percentile = 0.05     # worst-5% path annual return
```

### `SpendingScenario` (spending shocks)

```python
@dataclass(frozen=True)
class SpendingScenario:
    driver: str                           # inflation | discretionary | other
    mean_annual_growth: float             # base inflation or policy
    annual_vol: float                     # ±volatility around base
    shock_multiplier: float | None        # e.g., 1.5× in stress scenario
```

### `CallTimingScenario` (PE call timing)

```python
@dataclass(frozen=True)
class CallTimingScenario:
    pe_sleeve: str                        # pe_buyout | pe_venture | ...
    base_called_pct_by_quarter: list[float]   # baseline drawdown curve
    hazard_rate_median_years: float       # typical time-to-full-call
    early_call_probability: float         # p(calls compress)
```

## Output specification

### `MonteCarloPathResult`

One per stochastic path (replicated `num_paths` times):

```python
@dataclass(frozen=True)
class MonteCarloPathResult:
    path_id: int                          # [0, num_paths)
    seed: int                             # reproducible seed for this path
    
    # Quarterly time series
    nav_by_quarter: pd.Series             # by quarter_end_date
    liquid_nav_by_quarter: pd.Series
    spending_by_quarter: pd.Series
    call_obligations_by_quarter: pd.Series
    
    # Breach / shortfall tracking
    coverage_months_by_quarter: pd.Series
    breached_quarters: list[int]          # quarter indices where coverage < threshold
    earliest_breach_quarter: int | None
    
    # Terminal state
    final_nav_usd: float
    final_liquid_nav_usd: float
    cumulative_return_pct: float
    
    # Diagnostics
    max_drawdown_pct: float
    drawdown_quarters: int
```

### `MonteCarloResult` (aggregated across paths)

```python
@dataclass(frozen=True)
class MonteCarloResult:
    config_hash: str
    fixture_hash: str
    
    num_paths: int
    horizon_quarters: int
    seed: int | None
    
    # Path collection
    paths: list[MonteCarloPathResult]
    
    # Aggregate metrics (deterministic)
    probability_of_breach: float          # fraction of paths with coverage < threshold
    median_coverage_months: float
    p5_coverage_months: float
    p25_coverage_months: float
    p75_coverage_months: float
    p95_coverage_months: float
    
    worst_5pct_coverage: float            # minimum coverage from p5 paths
    best_5pct_coverage: float
    
    # Reserve requirement (deterministic from paths)
    required_liquid_nav_80pct_confidence: float
    required_liquid_nav_90pct_confidence: float
    required_liquid_nav_95pct_confidence: float
    
    # Return / growth
    median_final_nav: float
    p5_final_nav: float
    p95_final_nav: float
    
    # Diagnostics
    manifest: MonteCarloManifest
```

### `MonteCarloManifest` (audit trail)

```python
@dataclass(frozen=True)
class MonteCarloManifest:
    timestamp_utc: datetime.datetime
    config_hash: str
    fixture_hash: str
    
    num_paths: int
    horizon_quarters: int
    seed: int | None
    
    return_scenarios_count: int
    spending_scenarios_count: int
    call_scenarios_count: int
    
    synthetic_fixture_summary: str        # human-readable description
    advisory_caveat: str                  # standing advisory text
```

## Deterministic reproducibility requirement

**Same config + same seed + same fixtures = identical output, byte-for-byte.**

Every run writes:

```
config_hash (SHA256 of MonteCarloConfig)
fixture_hash (SHA256 of all synthetic inputs)
seed (int or None)
num_paths
horizon_quarters
output artifacts
```

This allows:

1. **Verification** — re-run with same seed, verify byte-identical output
2. **Comparison** — change seed, verify different paths but same aggregate metrics structure
3. **Audit** — compare two runs' hashes to detect input drift
4. **Regression** — commit artifacts with hashes; future changes must justify re-baseline

## Code structure (MC-1/MC-2/MC-3 implement these)

### Phase MC-1: Simulation core

```
src/aa_model/monte_carlo/
  __init__.py
  config.py              # MonteCarloConfig, ReturnScenario, etc.
  random_paths.py        # RandomPathGenerator class
  runner.py              # MonteCarloRunner class
  result.py              # MonteCarloPathResult, MonteCarloResult
```

### Phase MC-2: Liquidity stress integration

```
src/aa_model/monte_carlo/
  liquidity_stress.py    # apply paths to deterministic coverage
```

New orchestrator field:

```python
cfg.monte_carlo_config: MonteCarloConfig | None = None
```

### Phase MC-3: Reporting

```
src/aa_model/monte_carlo/
  reporting.py           # CSV, parquet, markdown outputs
```

## Testing discipline

### Phase MC-1 tests (6 required)

- Seed stability: same seed → identical paths
- Seed difference: different seed → different paths
- Schema validation: all fields present and typed
- Config validation: bounds and cross-field rules enforced
- Path count: num_paths honored in output
- Zero volatility: zero vol scenario collapses to deterministic baseline

### Phase MC-2 tests (4 required)

- Deterministic unchanged: existing coverage results stable
- Opt-in works: Monte Carlo produces output when enabled
- Zero volatility: with vol=0, Monte Carlo matches deterministic
- Breach detection: paths with coverage < threshold detected correctly

### Phase MC-3 tests (3 required)

- CSV structure: correct headers, all paths included
- Parquet schema: matching MonteCarloPathResult fields
- Report metrics: breach probability, percentiles computed correctly

All tests use **synthetic-only fixtures**. No real workbook data, no live
client numbers, no entity names. Fixtures are committed to `tests/fixtures/`.

## Standing output advisories (locked language)

When any Monte Carlo output is reported:

```
These Monte Carlo results are stochastic stress-test simulations using
synthetic assumptions for return volatility, spending shocks, and call
timing. They do not represent financial forecasts and are not actionable
policy until:

1. Row-level cash-flow classifications are completed (L19).
2. Workbook capital-call reconciliation is validated (L20).
3. Real PE commitment plan and actuals are integrated (Phase 23).

Current outputs reflect CMA long-term return assumptions and generic
PE call hazard rates. Entity-specific cash flows are not yet modeled.

Recommended use: sensitivity analysis, scenario comparison, and
reserve-adequacy planning. Not suitable for final family-unit liquidity
decisions until deterministic spine is validated against live data.
```

This language is **non-negotiable** in all reports until L19/L20/Phase-23
completion.

## Tightening statements (reviewer discipline enforced here)

**T1: No global randomness.**
The `random.seed()` global state is never modified. All randomness is
seeded through explicit `MonteCarloConfig.random_seed` and passed into
generators. Tests verify no call to `random.seed()`.

**T2: No mutation.**
`MonteCarloPathResult` and `MonteCarloResult` are frozen dataclasses.
Once computed, they cannot be modified. Comparison is byte-stable.

**T3: Fixture-aware auditing.**
Every call to `compute_monte_carlo()` writes `config_hash` and
`fixture_hash` to the manifest. CI can compare hashes across commits to
detect unintended drift.

**T4: Optional orchestration.**
`cfg.monte_carlo_config` defaults to `None`. Monte Carlo is never invoked
unless explicitly configured. Existing deterministic studies are unaffected.

**T5: Advisory-only outputs.**
No Monte Carlo metric becomes a hard gate, hard fail, or policy decision
until explicit user and reviewer sign-off following Phase-23 live-data
integration.

## Integration checklist (pre-implementation)

- [ ] `docs/phase_mc0_design_lock.md` committed
- [ ] MC-1 phase boundary approved (config, paths, runner)
- [ ] MC-2 phase boundary approved (liquidity stress)
- [ ] MC-3 phase boundary approved (reporting)
- [ ] Synthetic fixture fixtures committed (no real data)
- [ ] Test acceptance criteria documented
- [ ] CI gates configured (config_hash / fixture_hash validation)

## What Phase MC-0 does NOT include

1. **Real client data** — no live workbooks, no fund names, no dollar values
2. **Hard policy gates** — all outputs marked advisory
3. **RE / OpCo shock calibration** — placeholder fixtures only
4. **Entity-specific rules** — awaits L19 row classification
5. **Projection anchoring** — awaits Phase 23 monthly actuals
6. **Fee modeling** — out of scope for Phase MC
7. **Stochastic STAIRS** — deferred, Phase MC uses deterministic PE adapter

## Next phase: MC-1 (Phase MC-1 design will inherit this lock)

When ready, file a new `docs/phase_mc1_simulation_core_design.md` with
detailed API design, fixture examples, and test acceptance criteria.
