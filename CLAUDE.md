# Session Conventions for asset-allocation

This repo is built per [SPEC.md](SPEC.md). Read it before making changes.
PROJECT_SCOPE.md is authoritative for the Wake Robin reference architecture (locked 2026-05-02).
HERMES_TRACKING.md is the live status snapshot — read it first to know which phase / L# items are open.

## Phase
Phase 12.5 — L19 flow-side: `distribution_inflow` ledger flow + `distributable_income` spending base.
Phase 12 closed the base-side fix (configurable Owl denominator).
Phase 11 closed L16 (Owl scale-invariance via absolute-dollar guardrail; L19 was carved out as the spending-base realism follow-on).
Phases 4a, 4b, 5, 6, 7-locked, 8, 9, 10 already in main.

## Architecture rules
- Quarterly ledger is the spine. Every flow lands on it. New flow types require a Phase doc-lock.
- Schemas first (pydantic v2). Configs are validated; failure is loud.
- Adapter contracts in §9 of SPEC are mandated; stubs are reference implementations.
- Determinism: every run writes `data/processed/runs/<run_id>/manifest.json`. Reruns with identical inputs produce byte-identical `ledger.parquet`.
- Phase gates are real. Each phase ships a `docs(model): lock Phase N` design commit BEFORE any implementation commit.
- MODEL_DOCUMENTATION.md is doc-as-spec — every behavior change updates it in the same series.
- CMA baseline is immutable; scenarios are perturbations.

## Local commands

```
.venv/bin/pytest -p no:warnings              # 225 passing baseline
.venv/bin/ruff check src tests scripts       # must be clean
.venv/bin/ruff format --check src tests scripts
.venv/bin/python scripts/run_sfo_study.py --config configs/base.yaml
```

Note: `cvxportfolio` is an optional extra; 4 transaction-cost tests skip / fail without it. `riskfolio` extra is similar.

## What NOT to do
- Don't hard-code 60/40 anywhere. Stub allocator reads `configs/public_allocation.yaml::stub_weights`.
- Don't introduce a base class for a single subclass beyond what §9 of SPEC mandates.
- Don't overwrite an existing run directory; reruns create a new `run_id`.
- Don't bypass the design-lock-before-implementation rule.
- Don't ship a behavior change without a matching MODEL_DOCUMENTATION.md edit.
- Don't push red main. WIP commits stay local.

## Active limitations (open)
L1, L2, L3, L5, L7, L9, L10, L11, L12, L14 (partial), L17, L19 (Phase 12.5 closing).
See HERMES_TRACKING.md for the live table; MODEL_DOCUMENTATION.md for status lines per L#.
