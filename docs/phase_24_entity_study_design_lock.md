# Phase 24 — Design Lock — Entity Asset-Allocation Study Reproduction

> **Status: DRAFT design lock — pending reviewer tightening.** No
> implementation in this commit. No live client data, no person
> identifiers, no real fund/manager names, no real `entity_id`s, and no
> dollar values are consumed by tests or committed artifacts at any point
> in this phase. A concrete client entity (the "pilot entity") is
> onboarded only through **gitignored** local config + manifests.

> **Numbering note.** The Phase 23 doc provisionally reserved "Phase 24"
> for PE projection anchoring. That work is renumbered **Phase 25**; this
> entity-study phase takes **Phase 24**. Reviewer may renumber before lock.

## Standing constraint inheritance

Inherits every load-bearing constraint already in force:

- **Determinism** (SPEC §2): the study is computed from source data and
  reruns byte-identically. No `datetime.now()`; the only time anchor is
  the study `as_of_date`. Study outputs fold their inputs' hashes into
  `config_hash` / `run_id`.
- **Adapters, not dependencies** (SPEC §2.3): the study reader/renderer
  sit behind interfaces; the package still runs end-to-end with zero
  external optimizer libraries.
- **Worksheet alignment** (`docs/phase_19_design_constraints.md`): the
  study aligns to the operating-forecast spine (`Cashflow_Modeling_v7`)
  on timing / flow / source / reconciliation. It does not fork a parallel
  forecast.
- **NAV ≠ liquidity** (PROJECT_SCOPE standing principle): the study's
  balance-sheet lens explicitly separates investable financial assets
  from personal-use / structural NAV; appraisal value ≠ spending capacity.
- **Design-lock before implementation** (CLAUDE.md): this doc lands first.
- **Privacy posture** (see below): committed artifacts carry no client
  specifics; the pilot entity lives entirely in gitignored local files.

## One-line goal

Add a first-class **entity** dimension and an **entity study** capability
that deterministically reproduces the firm's standard Wake Robin
asset-allocation study — an 11-lens deliverable — for a single entity,
from the source documents the model already ingests, with the existing
`.xlsx` study used as the structural blueprint and a **validation oracle**
(golden-within-tolerance), and **without** changing any existing
default-fixture run.

## The 11-lens study and where each lens already lives

The study is the firm's standard Wake Robin format. Each lens maps to an
existing model layer; the phase wires them into one entity-scoped,
deterministic study object plus renderers.

| Lens | Source (already a model target) | Existing layer | Phase-24 work |
|---|---|---|---|
| Balance-sheet segmentation (investable vs personal-use/structural NAV) | Archway positions / balance sheet | entity/balance-sheet + `NAV≠liquidity` | segmentation reducer over classified positions |
| Allocation vs strategic target (7 policy classes) | Investment Summary positions + entity policy | `PublicAllocationConfig` / allocation adapter | policy-class crosswalk + gap/over-under reducer |
| Holdings detail (position-level by class) | Investment Summary (`position_ingestion`, Phase 15) | `ingestion/investment_summary.py` | class-grouped roll-up render |
| PE & alternatives (commitment / unfunded / distributions) | PE Summary "Enterprise Consolidated" | PE commitment book (Phase 23) + pacing | commitment-book → alt-lens reducer |
| Liquidity lens (redemption tiers) | Investment Summary liquidity buckets | `liquidity/coverage.py` + `liquidity_mapping` | tier crosswalk + share-by-tier reducer |
| Burn rate (spending by category) | Entity burn worksheet | `spending/*` (Owl / spending base) | category-normalized burn reducer |
| Cash flow & runway (draw vs inflow, deployable, scenario) | Burn + policy cash + scenarios | `spending/liquidity.py` + `scenarios` | runway/deployable reducer + what-if overlay |
| Liquidity projection (quarterly) | `Cashflow_Modeling_v7` → entity tab | quarterly ledger spine + `workbook_ingestion` | entity-tab ingest → projection ledger |
| Fidelity (custodian) reconciliation | Custodian statement + Archway positions | `pe/call_reconciliation` pattern + Phase 21 gates | custodian recon reducer + gate |
| Summary (three lenses at a glance) | derived | `integration/report.py` | summary composition |
| Notes & sources (provenance / caveats) | provenance taxonomy | manifest / report | provenance render |

**Key finding:** every source document the study cites is a document the
model already targets (`Cashflow_Modeling_v7`, the Investment Summary, the
PE Summary, custodian/Archway extracts). Phase 24 is therefore mostly
**composition + an entity dimension + renderers**, not new ingestion
machinery.

## New: the entity dimension

Today a "study" is one resolved `StudyConfig` → one run; there is **no
top-level entity object**. `entity_id` exists only inside the workbook and
position manifests. Phase 24 introduces:

### `EntityStudyConfig` (new, composes existing configs)

```
entity_id: str                 # required, URL-safe; resolves via EntityRegistry (Phase 23)
study_as_of_date: date         # single anchor for every lens; folds into config_hash
policy: EntityPolicyConfig     # this entity's strategic targets (7 Wake Robin classes)
study: StudyConfig             # the existing resolved composite, filtered to this entity
sources: EntitySourceManifest  # per-lens local (gitignored) source refs + expected filenames
```

`EntityStudyConfig` does **not** replace `StudyConfig`; it wraps it. When
no entity study is configured, the orchestrator path is byte-identical to
today.

### `EntityPolicyConfig` — the 7 Wake Robin strategic classes

Policy targets are authored per entity (the firm's Wake Robin strategic
policy). The seven policy classes are a **superset/aggregation** of the
model's existing position `_ASSET_CLASS_LITERAL`; Phase 24 pins a
deterministic crosswalk (no silent reclassification):

| Wake Robin policy class | maps from model asset classes |
|---|---|
| RE OpCo Stabilized | `real_estate_equity` flagged `opco_strategic` (stabilized) |
| Real Estate | `real_estate_equity` (direct) + `real_estate_debt` |
| Equity | `public_equity` |
| Private Equity | `private_equity` |
| Absolute Return | hedge / multi-strat sleeve (new policy bucket) |
| Fixed Income | `fixed_income_public` + `private_credit` |
| Cash & Cash Alts | `cash_equivalent` |

The crosswalk table is committed (methodology, not client data). Any
position whose class does not map raises loudly (fail-loud, no silent
"other" bucket). "Absolute Return" and "RE OpCo Stabilized" are new
**policy-level** aggregation buckets — position-level literals are not
expanded in this phase (avoids churn); the mapping is a reduce step.

### Liquidity-tier crosswalk

The study's redemption tiers (Daily / Monthly / Quarterly / At-Maturity)
are a **presentation axis** distinct from the model's Phase-12
`liquid / semi_liquid / illiquid` tiers and the Phase-15 `liquidity_bucket`
taxonomy. Phase 24 pins a deterministic bucket→tier crosswalk (committed,
methodology) with per-entity overrides allowed in the gitignored manifest.
Income-producing stabilized RE never silently upgrades to a faster tier
(reuses the Phase-15 T3 guarantee).

## Study data model + renderers

```
EntityStudyConfig ─▶ orchestrator (entity path) ─▶ EntityStudyResult
                                                     ├─ eleven lens objects (pure data)
                                                     └─ provenance + reconciliation diagnostics
EntityStudyResult ─▶ markdown renderer   (reuses integration/report.py section style)
EntityStudyResult ─▶ xlsx study exporter (mirrors the 11-tab layout — client deliverable)
```

- **`EntityStudyResult`** is pure, hashable data (one dataclass/model per
  lens). No rendering logic; deterministic ordering everywhere.
- **Markdown renderer** extends the existing `write_markdown_report`
  section vocabulary (`## …`) — no new dependency.
- **xlsx exporter** writes a new workbook mirroring the 11 tabs. It
  **never** opens or mutates the source study `.xlsx`; it writes a fresh
  file under the run directory (`data/processed/runs/<run_id>/`). openpyxl
  is already a dependency.

## Validation oracle (the existing `.xlsx` as golden)

The client `.xlsx` is the **structural blueprint and a numeric oracle**,
not an input:

- A **local, gitignored** oracle harness (`data/external/…_local`) reads
  the study `.xlsx` read-only and compares model-computed lens values to
  the workbook's values within a documented tolerance (e.g. rounding /
  display precision).
- Tolerances and any accepted divergences (e.g. classification "by
  strategy not label" per the Notes tab) are recorded in the **local**
  oracle notes — never in the committed doc.
- Committed tests use **synthetic** entities/fixtures only. The oracle
  harness runs locally against the real workbook and is **not** part of CI.

## Determinism contract

- Every lens value derives from source data + committed methodology
  tables; no wall-clock reads. Sole time anchor: `study_as_of_date`.
- `entity_id`, `study_as_of_date`, and each source's version/hash fold
  into `config_hash`; changing the entity, the as-of date, or any source
  invalidates `run_id` correctly.
- Lens objects sort deterministically (class order = committed policy
  order; positions by stable key). xlsx/markdown output is byte-stable for
  identical inputs.
- No-entity-study runs are byte-identical to pre-Phase-24.

## What Phase 24 is **NOT**

- Not a change to any existing default-fixture run (byte-stable).
- Not new ingestion machinery — it composes Phase 14/15/23 ingestion.
- Not a `StudyConfig` refactor; `EntityStudyConfig` wraps it.
- Not a live-data phase: only synthetic fixtures are committed; the pilot
  entity is gitignored-local.
- Not a multi-entity consolidation / roll-up (single entity per study).
- Not a rebalancing-order / trade-list generator (allocation gaps are
  reported, not executed).
- Not a tax-aware or entity-governance distributability layer (those
  remain upstream classification).
- Not a Monte Carlo or stochastic layer (the scenario overlay is the
  deterministic what-if toggle set only).
- Not a mutation of the source study `.xlsx` or any source document.
- Not a position-level asset-class literal expansion (policy buckets are a
  reduce step).

## Tests planned (synthetic fixtures only)

Entity model & crosswalks (~8): entity_id resolves via EntityRegistry;
policy-class crosswalk maps every synthetic class; unmapped class raises;
"Absolute Return" / "RE OpCo Stabilized" aggregation correctness;
liquidity bucket→tier crosswalk; income-producing RE never upgrades tier;
policy targets sum to 100%; per-entity tier override applies.

Lens reducers (~11, one per lens): each reducer computes correct
aggregates on a synthetic entity fixture (balance-sheet segmentation,
allocation-vs-target gaps, holdings roll-up, alt-lens unfunded, liquidity
share-by-tier, burn normalization, runway/deployable, quarterly
projection, custodian recon delta, summary composition, provenance).

Renderers (~4): markdown sections render; xlsx exporter writes 11 tabs;
exporter never touches the source file (path-safety); byte-stable output.

Determinism (~3): same input → byte-identical `EntityStudyResult` dump,
markdown, and xlsx; changing `study_as_of_date` / `entity_id` / a source
version changes `config_hash`.

End-to-end (~2): no entity study configured → byte-identical
pre-Phase-24 ledger/manifest/report; synthetic entity study → all 11
lenses render, existing outputs unchanged.

Target: ~28 tests, all synthetic.

## L-status implications

- **L19 / L20** — unchanged (this phase consumes their outputs; it does
  not alter workbook classification or the Phase-20 source precedence).
- **L2 (liquidity coverage)** — unchanged; the liquidity lens presents
  existing coverage output on a new axis.
- New standing limitation **L22 (entity-study realism)**: the study is
  only as good as the entity's local manifests + policy authoring. Marked
  PARTIALLY RESOLVED on first synthetic-fixture landing; full resolution
  requires a validated local oracle pass against the real workbook.

## Privacy posture (load-bearing)

- The pilot entity's config, manifests, source refs, and oracle notes are
  **gitignored** (`data/external/…_local`, `configs/*_local.yaml`).
- Person identifiers, real `entity_id`s, real fund/manager names, account
  numbers, and dollar values **never** enter committed artifacts or chat.
- The committed crosswalk tables and this doc are **methodology only** —
  the firm's Wake Robin policy taxonomy, no client specifics.
- The oracle harness confirms gitignore membership before reading the
  source `.xlsx`; it opens the source read-only and never writes to it.
- Committed tests use synthetic entities (e.g. `entity_synth_a`).

## Locked design choices

- Introduce `EntityStudyConfig` that **wraps** (not replaces)
  `StudyConfig`; no-entity path stays byte-identical.
- Seven Wake Robin policy classes are **policy-level aggregation buckets**
  over existing position literals via a committed crosswalk; fail-loud on
  unmapped classes; no position-literal expansion.
- Liquidity tiers are a presentation axis with a committed bucket→tier
  crosswalk + per-entity local overrides; no silent tier upgrades.
- `EntityStudyResult` is pure data; markdown + xlsx renderers are separate
  adapters; the xlsx exporter writes a fresh file and never touches the
  source.
- The client `.xlsx` is a blueprint + local oracle, never a committed
  input; CI stays synthetic-only.
- Single anchor date (`study_as_of_date`) across all lenses; folded into
  `config_hash`.

## Implementation gating & internal sub-steps

Implementation is gated on: (1) this design lock committed (docs-only);
(2) no reviewer tightening in flight; (3) synthetic fixtures authored
before production code; (4) `EntityStudyConfig` + crosswalks + Entity
resolution land before any lens reducer (reducers depend on them).

Because the full 11-lens study is large, implementation proceeds in
reviewable internal sub-steps under this single lock, each byte-stable on
existing fixtures:

1. Entity dimension: `EntityStudyConfig`, `EntityPolicyConfig`, crosswalk
   tables, EntityRegistry wiring, no-entity byte-stability test.
2. Core allocation lenses: balance-sheet segmentation, allocation-vs-target,
   holdings detail, liquidity lens (highest reuse of existing code).
3. Cash-flow lenses: burn rate, cash-flow/runway + what-if, quarterly
   liquidity projection (entity-tab ingest).
4. Alternatives + reconciliation: PE/alt lens, custodian recon + gate.
5. Renderers: markdown sections, then xlsx 11-tab exporter.
6. Local oracle harness (gitignored) + summary/notes composition.

Each sub-step is its own implementation commit; MODEL_DOCUMENTATION.md is
updated in the same series per house rule.
