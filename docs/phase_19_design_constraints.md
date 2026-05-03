# Phase 19 — Design Constraints

> Pre-design-lock reference. The actual `docs(model): lock Phase 19` commit
> will live in `MODEL_DOCUMENTATION.md`. This file holds the standing
> worksheet-alignment constraint and the Phase 19 design prompt that must be
> applied when the design-lock is authored.

## Standing design constraint (applies Phase 19 and forward)

The spending / liquidity / PE pacing model must stay closely aligned with the
`Cashflow Modeling v7.xlsx` operating forecast.

```
Cash-flow worksheet = operating forecast source of truth.
Model = normalized architecture, validation, coverage, pacing, and scenario engine.
```

### Four alignment dimensions

1. **Timing alignment** — quarters, fiscal periods, and lookahead windows match
   the worksheet's period structure.

2. **Flow alignment** — spending, distributions, capital calls, taxes, entity
   obligations, and operating cash flows map back to worksheet lines or to
   explicit model-generated flows.

3. **Source alignment** — every modeled obligation knows its provenance from
   the canonical taxonomy:

   - `explicit_config`
   - `cashflow_workbook`
   - `pe_pacing_model`
   - `investment_summary`
   - `synthetic_fixture`

4. **Reconciliation alignment** — reports show where model totals reconcile to
   the worksheet, and where they intentionally differ. Differences classify as
   advisory / warning / blocking.

### Boundary rules

```
Read the worksheet.
Normalize the worksheet.
Reconcile to the worksheet.
Do not mutate the worksheet.
Do not infer legal/tax/entity-governance meaning unless classified upstream.
Do not commit live workbook data.
```

This is consistent with the existing Phase 14–18 architecture: workbook
ingestion is read-only, client-specific classification is local/private, and
Phase 18 already bridges the selected spending base into liquidity coverage
rather than leaving liquidity detached from the spending engine.

## Phase 19 design prompt (for the design-lock author)

Apply the standing constraint above when authoring the Phase 19 design lock.
The PE call-obligation bridge MUST NOT become "PE pacing in isolation"; it
must become "PE pacing reconciled to the family-office cash-flow forecast."

### Required behavior

The next-12m capital-call obligation bridge must answer, by quarter and by
source:

1. What does the cash-flow worksheet forecast for PE calls over the next 4 quarters?
2. What does the PE pacing model forecast for the same quarters?
3. Which source is used for liquidity coverage?
4. What is the reconciliation delta?
5. Is the difference advisory, warning, or blocking?

### Default precedence

- If the workbook has classified capital-call lines: workbook is the operating
  forecast source. PE pacing is a model-derived cross-check only.
- If the workbook has classified capital-call lines AND the user explicitly
  configures PE pacing as the obligation source: PE pacing wins, workbook
  becomes the cross-check. This must be an explicit config flag, not a default.
- If the workbook has no classified capital-call lines: PE pacing may populate
  `next_12m_capital_calls_usd`.
- If both are absent: leave `next_12m_capital_calls_usd = None` and emit
  advisory.

### Required source taxonomy on every obligation

Every emitted obligation record carries one of:

- `explicit_config`
- `cashflow_workbook`
- `pe_pacing_model`
- `investment_summary`
- `synthetic_fixture`

### Reconciliation diagnostics

Surface, by quarter:

- Workbook value (if present)
- PE pacing value (if present)
- Selected value (the one used for `next_12m_capital_calls_usd`)
- Source used
- Delta (workbook − pacing) absolute and percent
- Classification: advisory (within tolerance) / warning (outside tolerance) /
  blocking (irreconcilable, e.g. opposite signs)

The advisory/warning/blocking classifier mirrors the Phase 16 board-snapshot
reconciliation pattern (`abs_pct <= 0.5` advisory, etc.) — reuse the existing
threshold idiom rather than inventing a new one.

### Hard non-goals

- No Monte Carlo. Phase 19 is deterministic pacing, not a stochastic engine.
- No heuristic "unfunded × percentage" default. If neither source is present,
  the answer is `None` + advisory, not a fabricated estimate.
- No live client data in docs / tests. Synthetic fixtures only.
- No silent override of the workbook by PE pacing. Override requires an
  explicit config flag and surfaces in diagnostics.
- No new ledger flow type without a separate doc-lock. Phase 19's contribution
  to liquidity coverage is via the existing capital-call obligation field, not
  a new flow.

### Required tests (sketch — design lock will refine)

- Workbook-classified lines present, PE pacing absent → workbook wins, source
  = `cashflow_workbook`, no reconciliation delta.
- PE pacing present, workbook absent → pacing wins, source = `pe_pacing_model`,
  advisory noting workbook-source unavailable.
- Both present, within tolerance → workbook wins, source = `cashflow_workbook`,
  advisory with reconciliation delta.
- Both present, outside tolerance → workbook wins, source = `cashflow_workbook`,
  WARNING with reconciliation delta surfaced in liquidity report.
- Both present, opposite signs / irreconcilable → BLOCKING; coverage emits
  `next_12m_capital_calls_usd = None` + breach-equivalent advisory.
- Explicit config override (`pe_pacing` selected as authoritative) → pacing
  wins, source = `pe_pacing_model`, workbook becomes cross-check, delta still
  reported.
- Determinism: identical inputs produce byte-identical reconciliation output.

### Linkage to existing limitations

This phase touches:

- **L1** — PE timing scenarios mechanically affect returns. Phase 19's pacing
  reconciliation does not resolve L1 but should not regress it.
- **L14** — only linear transaction cost is modeled (partial). Phase 19 is
  orthogonal but should not complicate the cvxportfolio extras path.
- New L# (Phase 19): if the design surfaces a residual realism gap (e.g.
  inability to classify one-off accelerated calls), mint a new L-item in the
  design lock and add a status line to MODEL_DOCUMENTATION.md.

---

## How to use this file

1. When opening Phase 19's design-lock series, read this file first.
2. Treat sections "Standing design constraint" and "Phase 19 design prompt"
   as inputs to the `docs(model): lock Phase 19` commit. They do NOT replace
   that commit.
3. After the design lock lands, this file's Phase 19 prompt section becomes
   redundant — the authoritative version lives in MODEL_DOCUMENTATION.md.
   Keep the standing constraint section indefinitely; it applies to all
   future phases that touch spending / liquidity / PE pacing.
