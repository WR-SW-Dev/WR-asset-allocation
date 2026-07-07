# Session Conventions for asset-allocation

This repo is built per [SPEC.md](SPEC.md). Read it before making changes.
PROJECT_SCOPE.md is authoritative for the Wake Robin reference architecture (locked 2026-05-02).
HERMES_TRACKING.md is the live status snapshot — read it first to know which phase / L# items are open.

## Phase
Phase 23 — PE real-data commitment input layer (design locked f81ff43; implementation pending).
Closed in main: 4a, 4b, 5, 6, 7-locked, 8, 9, 10, 11 (L16), 12 (L19 base-side), 12.5 (L19 flow-side),
13 (distribution_inflow producer), 14 (workbook ingestion), 14.1/14.2 (layout discovery), 15
(investment summary / position ingestion), 16 (liquidity coverage diagnostics — L20), 17
(StudyConfig integration), 18 (SpendingBase → coverage bridge), 19 (PE call-obligation bridge),
20 (workbook capital-call reconciliation), 21 (configurable obligation gates), 22 (manager terms
consumer / diagnostic layer), 14.3 (workbook row_range / data-region scoping).

## Architecture rules
- Quarterly ledger is the spine. Every flow lands on it. New flow types require a Phase doc-lock.
- Schemas first (pydantic v2). Configs are validated; failure is loud.
- Adapter contracts in §9 of SPEC are mandated; stubs are reference implementations.
- Determinism: every run writes `data/processed/runs/<run_id>/manifest.json`. Reruns with identical inputs produce byte-identical `ledger.parquet`.
- Phase gates are real. Each phase ships a `docs(model): lock Phase N` design commit BEFORE any implementation commit.
- MODEL_DOCUMENTATION.md is doc-as-spec — every behavior change updates it in the same series.
- CMA baseline is immutable; scenarios are perturbations.

## Standing design constraint: cash-flow worksheet alignment

The spending / liquidity / PE pacing model must stay closely aligned with the
`Cashflow Modeling v7.xlsx` operating forecast. The worksheet is the operating
forecast spine; the model provides structure, validation, coverage, pacing, and
scenario logic around it. The model must NOT evolve into a separate "theoretical"
engine that drifts from the actual cash-flow worksheet.

Four alignment dimensions for any new spending / liquidity / PE pacing work:

1. **Timing alignment** — quarters, fiscal periods, lookahead windows match the
   worksheet's period structure.
2. **Flow alignment** — spending, distributions, capital calls, taxes, entity
   obligations, operating cash flows map back to worksheet lines or to explicit
   model-generated flows.
3. **Source alignment** — every modeled obligation carries its provenance from
   the canonical taxonomy:
   - `explicit_config`
   - `cashflow_workbook`
   - `pe_pacing_model`
   - `investment_summary`
   - `synthetic_fixture`
4. **Reconciliation alignment** — reports show where model totals reconcile to
   the worksheet, and where they intentionally differ (advisory / warning /
   blocking classification).

**Boundary rules** (the model aligns to the worksheet but does not fuse with it):

- Read the worksheet. Normalize the worksheet. Reconcile to the worksheet.
- Do NOT mutate the worksheet.
- Do NOT commit live workbook data (manifests local; data files gitignored).
- Do NOT infer legal / tax / entity-governance distributability from row labels;
  classification is upstream of ingestion.

When two sources disagree (e.g. workbook capital-call line vs PE pacing forecast),
define precedence in the phase design lock and emit reconciliation diagnostics
by quarter and by source. Default precedence: workbook-classified line wins;
model-derived projection is cross-check unless explicitly configured as the
obligation source. See `docs/phase_19_design_constraints.md` for the worked
example.

## Local commands

```
.venv/bin/pytest -p no:warnings --ignore=tests/test_transaction_cost_summary.py   # 371 passing baseline (post-Phase 22/14.3; 4 cvxportfolio-gated omitted)
.venv/bin/ruff check src tests scripts       # must be clean
.venv/bin/ruff format --check src tests scripts
.venv/bin/python scripts/run_sfo_study.py --config configs/base.yaml
```

Note: `cvxportfolio` and `riskfolio` are optional extras; both are pulled in by
`requirements-dev.txt`. Without them, gated tests skip / `ModuleNotFoundError` at collection.

## Code intelligence (codegraph)

This repo is indexed by codegraph — a SQLite knowledge graph of every symbol,
edge, and file (~127 files / 1700+ nodes). The DB lives at
`.codegraph/codegraph.db` and is **local, gitignored, per-machine** (never
committed). Consult it BEFORE writing or editing model code — it is the
pre-built search index, so a couple of codegraph calls beat a grep/read sweep.

- Query via the codegraph MCP tools. If the MCP's default project is another
  repo (e.g. biotech-screener), pass
  `projectPath="/mnt/c/Projects/asset allocation/asset-allocation"`.
- Typical use on this codebase:
  - `codegraph_context` — orient on a schema / phase / adapter area first.
  - `codegraph_trace` — follow a flow end-to-end (e.g. workbook line → ledger
    quarter → coverage report), including dynamic-dispatch hops grep can't.
  - `codegraph_impact` / `codegraph_callers` — before changing a schema or an
    adapter contract (§9 of SPEC), check what a change would break.
- The index is a point-in-time snapshot and **drifts as code changes**. There
  is **no auto-reindex watcher** (org policy: auto-reload off) — re-index
  manually when the graph is stale (e.g. after a phase lands). Treat a stale
  result as a hint, then confirm the specific detail with Read.

## What NOT to do
- Don't hard-code 60/40 anywhere. Stub allocator reads `configs/public_allocation.yaml::stub_weights`.
- Don't introduce a base class for a single subclass beyond what §9 of SPEC mandates.
- Don't overwrite an existing run directory; reruns create a new `run_id`.
- Don't bypass the design-lock-before-implementation rule.
- Don't ship a behavior change without a matching MODEL_DOCUMENTATION.md edit.
- Don't push red main. WIP commits stay local.
- Don't build a parallel cash-flow forecast that silently conflicts with the
  workbook (see standing design constraint above).
- Don't infer legal/tax/entity-governance meaning from row labels; that's an
  upstream classification responsibility.

## Active limitations (open)
L1, L2, L3, L5, L7, L9, L10, L11, L12, L14 (partial), L17, L19 (partially resolved).
See HERMES_TRACKING.md for the live table; MODEL_DOCUMENTATION.md for status lines per L#.

## Developer Profile

This system is maintained by an institutional SFO investment professional (CFA, CAIA) with deep expertise in:

### Asset Allocation & Portfolio Management
- **Multi-asset-class portfolio construction** — strategic/tactical allocation, rebalancing frameworks, dynamic allocation
- **Institutional fund governance** — $14B+ AUM CIO/Deputy CIO experience, sovereign wealth & public pension fund oversight
- **Cash-flow & liquidity modeling** — spending policies, capital call pacing, PE/PE obligations, fiscal period alignment
- **Fixed income & derivatives** — duration management, treasury futures, swaps, structured products

### Investment Management Expertise
- **Manager research & selection** — active vs. passive evaluation, due diligence, ongoing monitoring
- **Alternatives & real assets** — private equity, real estate, infrastructure, timber, commodities
- **Capital markets analysis** — macro indicators, cross-asset correlations, forward return expectations
- **Consultant management** — Callan consultant relationships, capital markets assumptions, manager searches

### Technical & Data
- **Python quantitative modeling** — pydantic schemas, deterministic pipelines, parquet/ledger structures
- **Financial data** — SEC EDGAR 13F analysis, workbook ingestion/reconciliation, Excel interop
- **Testing & validation** — pytest framework, determinism verification, reconciliation audits
- **AI integration** — AI-augmented research, Claude/Grok analysis, automated reporting
