# Hermes Tracking — Asset Allocation Model

> Stable entry point for Hermes/OpenWebUI dashboards. Update sections marked
> `<!-- auto -->` from CI/cron; update prose sections by hand at phase boundaries.
> Last manual sync: 2026-07-17 (commit-pointer sync — post-Phase-26 housekeeping).

---

## Current State <!-- auto -->

- Current phase: **Phase 26 — purpose (goals-based) allocation lens SHIPPED** (PR #18 `d1277dc`: 7-purpose taxonomy, banded purpose policy, holding→purpose resolution, lens + md/xlsx sections + CLI `--purpose-policy`; oracle 56/56 vs the study template's new Purpose_Allocation tab; no-purpose output byte-identical). Prior: **Phase 24 — entity dimension implemented** (Jim's Trust pilot: deterministic fixture + study lenses + xlsx/markdown renderers + one-command CLI, design-locked at `ac7cfb4`); Monte Carlo hardening (closed-form reserves, cross-process-stable seeds) and Morningstar Direct ingestion (index returns + empirical CMA calibration) also landed. Phase 23 (PE real-data commitment input layer) design lock at `f81ff43` still pending implementation.
- Latest commit: `f22ca9f` — fix(ingestion): silence Pydantic model_ namespace warnings (non-behavioral). Prior housekeeping: `0f47dd1` docs(tracking) test-count fix. Last behavior change: `d1277dc` (Phase 26 purpose lens, PR #18).
- Branch: `main` (0 ahead, 0 behind origin)
- Last pushed: 2026-07-17 (`f22ca9f`)
- Local HEAD: none — matches origin/main
- Working tree: clean (HERMES_TRACKING.md only — this file). The formerly-untracked PDF is now tracked at `docs/WR Asset Allocation Model Documentation.pdf` (`3afd16b`, moved `f1b68fc`, regenerated `19b4def`)
- Tests: **574 passed** (550 → 574: +24 Phase 26 synthetic tests) (`.venv/bin/pytest -p no:warnings --ignore=tests/test_transaction_cost_summary.py`; 4 cvxportfolio-gated omitted)
- Ruff: **0 errors** — `ruff check src tests scripts` all clean (verified at each Phase 26 sub-step + pre-push hook).
- Latest run set: `data/processed/runs/aa-dc07a16dffa9-96451d89bace-20260712T223056Z-d931-crisis_correlation`

**PHASE DRIFT: 2 commits since last sync** (`94d843d`..HEAD): `4364863` docs(design) Phase 26 design lock · `d1277dc` Phase 26 implementation (PR #18 squash of 4 sub-step commits: schemas, lens, renderers+CLI, SPEC amendment + doc-as-spec entry).

Governance check (this range `94d843d..HEAD`): **PASS — behavior change fully governed**. `d1277dc` is a `feat` behavior change, and its squash INCLUDES the required same-series governance artifacts: SPEC §11 amendment (Spec Amendment 2026-07-15) and the MODEL_DOCUMENTATION.md §Phase 26 doc-as-spec entry. Design was locked before implementation (`4364863`); implementation ran on explicit operator go; no-purpose rendering verified byte-identical; local real-workbook oracle 56/56.

✅ **Governance flag RESOLVED (2026-07-14, `fc04aeb`)**: The 2026-05-05 flag (`021a408`, carried 68 days) was closed via disposition (a) — a `docs(model):` follow-up documenting all three external-review triage commits (`0280024` manifest invocation_id path-safety guard; `d2d9e09` config-hash expansion, overlay workbook_path resolution, gate/coverage schema tightening; `021a408` TA terminal wind-down, fund_count uncap, zero/zero delta guard) in `docs/MODEL_DOCUMENTATION.md` §Governance follow-up. No open governance flags remain.

## Open Gates

- [ ] **Phase 23 implementation** — design locked at `f81ff43` (PE real-data commitment input layer). Implementation pending (unchanged this sync).
- [x] **Monte Carlo MC-0 through MC-3** — DESIGN LOCKED + IMPLEMENTED at `d2c3144`/`478d902`/`971379f`/`9b34373`. MC lint debt sweep landed at `5c83156` — ruff clean as of this sync.
- [x] **Phase 26 purpose (goals-based) allocation lens** — design locked `4364863`, implemented + merged PR #18 (`d1277dc`) same day; oracle 56/56; real purpose policy gitignored at `data/external/entity_jims_trust_purpose_policy_local.yaml`.
- [ ] **Phase 24 entity dimension follow-ups** — design locked `ac7cfb4`, implemented across PRs #6/#11–#17 (`0b0f2c5`). Doc-as-spec entry present (MODEL_DOCUMENTATION.md §Phase 24). No open test gaps identified this sync; re-verify at next full sweep.
- [ ] **Phase 7 STAIRS PE adapter** — design locked at `993a751`. Implementation
      blocked until tests + invariants drafted alongside `pe/stairs_adapter.py`.
- [ ] **Phase 10 L14 transaction-cost diagnostics** — partially resolved at
      `49544f7` (report section); 4 cvxportfolio-gated tests still skipped /
      ModuleNotFoundError when extra not installed.
- [ ] **Phase 19.1 design lock** — SUPERSEDED by Phase 20 (`a5114f6`) +
      Phase 21 (`412e1ee`). `docs/phase_19_1_design_lock.md` retained as
      traceability record. Phase 20 implemented reconciliation; Phase 21
      added configurable gates (advisory / warning / requires_override /
      hard_fail). The 3 missing-test follow-ups from the superseded lock
      remain open until back-checked against Phase 21's gate behavior.
- [ ] **L19 spending-base realism** — partially resolved (Phase 12/12.5/13/14
      at MODEL_DOCUMENTATION.md:1376). Remaining gap: real-workbook
      validation pending.
- [ ] **MODEL_DOCUMENTATION.md sweep** — confirm L16 status flips to
      `[RESOLVED 2026-05-02, Phase 11]` and that L19 caveat references are linked.
- [ ] **Determinism check** — re-run identical inputs must produce byte-identical
      `ledger.parquet` (SPEC §determinism).

## Active Limitations (open)

| ID  | Title                                                          | Doc line |
| --- | -------------------------------------------------------------- | -------- |
| L1  | PE timing scenarios mechanically affect returns                | 475      |
| L2  | Returns are NAV-dependent, not regime-dependent                | 490      |
| L3  | Stub-vs-riskfolio weights are not numerically comparable       | 502      |
| L5  | `source` as a PE-leg pairing key is fragile                    | 543      |
| L7  | Smoothing rule with `weight=0` freezes spending                | 586      |
| L9  | Heavy install footprint for `riskfolio` extra                  | 615      |
| L10 | `/mnt/c` filesystem unsuitable for `.venv`                     | 626      |
| L11 | Synthetic 2-row dummy returns frame in Riskfolio adapter       | 637      |
| L12 | Non-fatal "convert cov to PSD" warning                         | 694      |
| L14 | Only linear transaction cost is modeled (partial resolve)      | 984      |
| L17 | Cross-engine metric comparability is not meaningful            | 839      |
| L19 | Spending-base realism — partial; pending real-workbook validation | 1376  |

## Resolved Limitations

| ID  | Phase    | Resolved    | Title                                                  |
| --- | -------- | ----------- | ------------------------------------------------------ |
| L4  | Phase 5  | 2026-05-02  | Riskfolio default CMA fallback placeholder             |
| L6  | Phase 6  | 2026-05-02  | `correlation_shock` scenario omitted                   |
| L8  | Phase 8  | 2026-05-02  | Rebalancer treated PE as a liquid sleeve               |
| L13 | Phase 4b | 2026-05-02  | Cvxportfolio adapter had no path dependence            |
| L15 | Phase 4a | 2026-05-01  | Owl reacted to forecasted NAV, not realized NAV        |
| L16 | Phase 11 | 2026-05-02  | Owl scale-invariant in initial NAV (absolute guardrail)|
| L18 | Phase 4a | 2026-05-01  | Owl misread inflation shock as headroom                |
| L20 | Phase 20+21 | 2026-05-03 | PE call obligation — workbook reconciliation + gates  |

## Do Not Violate (governance invariants)

- **Ledger is sole state spine.** No sidecars, no hidden state.
- **CMA is baseline prior; scenarios are perturbations.** CMA baseline immutable.
- **No implementation before design lock.** Each phase ships a `docs(model): lock Phase N`
  commit before any implementation commit.
- **MODEL_DOCUMENTATION.md must be updated for any behavior change.** Doc-as-spec.
- **Determinism: identical inputs → byte-identical `ledger.parquet`.**
- **No overwriting run directories** — every run gets a new `run_id`.
- **No optimizer libs in Phase 1.** Phase-1 stub allocator only.
- **No STAIRS before L6 correlation_shock.** [SATISFIED — L6 resolved Phase 6.]
- **PROJECT_SCOPE.md is authoritative** for Wake Robin reference architecture
  (locked 2026-05-02 at `69cae5c`).

## Standard Commands

```bash
# Tests (clean, no warnings — 225 expected; 4 cvxportfolio-gated tests need extra)
.venv/bin/pytest -p no:warnings

# Lint
.venv/bin/ruff check src tests scripts
.venv/bin/ruff format --check src tests scripts

# Run scenario sweep
.venv/bin/python scripts/run_sfo_study.py --config configs/base.yaml

# Determinism: rerun and diff manifest hashes
.venv/bin/python scripts/run_sfo_study.py --config configs/base.yaml
# then compare two manifest.json files under data/processed/runs/
```

## Hermes Automations

| Cadence            | What runs                                                    |
| ------------------ | ------------------------------------------------------------ |
| Daily 18:00 ET     | repo health: git status, pytest -q, ruff check, doc-diff     |
| On every push      | new-commits summary, behavior-change → doc-update enforcement|
| Before phase gate  | design-section presence check, open-L items, required tests  |

Cron jobs are registered separately in Hermes (see `cronjob list`).

## Dashboard Cards (for Open WebUI / Hermes UI)

### Asset Allocation Model — Status
```
Current phase:        Phase 26 purpose-allocation lens shipped (PR #18); Phase 24 entity dimension live; Phase 23 design lock pending; Phase 25 reserved (PE projection anchoring)
Last pushed commit:   f22ca9f  (fix: silence Pydantic model_ warnings; non-behavioral. Last behavior change: d1277dc Phase 26 PR #18)
Local HEAD:           none — matches origin/main
Tests:                574 passed (+24 Phase 26; --ignore=tests/test_transaction_cost_summary.py; 4 cvxportfolio-gated omitted)
Ruff errors:          0 (clean; verified by pre-push hook on every push in range)
Open limitations:     11  (L1-L3, L5, L7, L9-L12, L14 partial, L17, L19 partial)
Resolved limitations: 8   (L4, L6, L8, L13, L15, L16, L18, L20)
Next gated task:      Phase 23 implementation (PE real-data commitment input layer)
Last model-doc update: 2026-07-15 (d1277dc — §Phase 26 entry + SPEC Amendment 2026-07-15, same-series with the behavior change)
Latest run:           20260712T223056Z (aa-dc07a16dffa9-96451d89bace-20260712T223056Z-d931-crisis_correlation)
Stale gov flag:       RESOLVED 2026-07-14 (fc04aeb, disposition (a)) — no open flags
```

### Governance Gates
```
[x] Design lock before implementation       (Phase 7,8,9,10,11 all locked)
[x] PROJECT_SCOPE.md authoritative          (locked 69cae5c)
[x] MODEL_DOCUMENTATION updated post-impl   (L20 resolved; L16/L19 status lines pending full sweep)
[x] CMA baseline immutable                  (verified L4 resolution)
[x] Ledger remains sole state spine         (architectural)
[x] L6 correlation_shock before STAIRS      (Phase 6 resolved L6)
```

### Numerical Health
```
[x] Determinism check         (Phase 1 gate, verified)
[x] Ledger invariants         (test_schemas.py, test_orchestrator.py)
[x] Spend uniqueness          (test_spending_rules.py)
[ ] PSD validation            (L12 warning still emitted — non-fatal)
[x] Cost-aware λ diagnostics  (Phase 4b)
[x] Scenario shock validation (test_scenario_builder.py, test_sweep.py)
[x] Owl scale-invariance      (Phase 11 — absolute-dollar guardrail)
```

---

## Update protocol

- **Auto sections** (`<!-- auto -->`) — overwritten by daily Hermes cron and post-push hook.
- **Active/Resolved Limitations** — updated when a commit message contains `resolves L#`
  or doc edit changes the `Status:` line of an `L#` heading.
- **Gates / Do Not Violate** — only edited when SPEC.md changes. Treat as protected.
- **Phase prose** — edit at phase-boundary commits (`docs(model): lock Phase N`).
