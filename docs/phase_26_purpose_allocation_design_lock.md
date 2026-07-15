# Phase 26 — Design Lock — Purpose (Goals-Based) Allocation Lens

Status: **DRAFT — pending operator lock**
Drafted: 2026-07-15
Numbering: Phase 25 is reserved for PE projection anchoring (see Phase 24 lock);
this workstream takes **Phase 26**.

---

## Standing constraint inheritance

All Phase 24 standing constraints apply unchanged:

- The model is a research/study tool; nothing here produces trade or
  rebalancing mandates.
- NAV ≠ liquidity; the standing principle in `PROJECT_SCOPE.md` governs.
- Money is `Decimal` end-to-end; reconciliation is exact, not approximate.
- Determinism: pure functions, no wall clock, content-addressed fixtures.
- Doc-as-spec: implementation commits update `docs/MODEL_DOCUMENTATION.md`
  in the same series.
- Privacy: committed code, configs, and tests are generic/methodology-only.
  All real-entity values (targets, bands, holding assignments) live in
  gitignored `data/external/*_local.yaml`.

## One-line goal

Give the entity study a second, parallel policy dimension — **purpose
(goals-based) allocation** — so the same investable base can be reported
against a purpose policy with tolerance bands, exactly as the firm's study
template now does in its `Purpose_Allocation` tab (first observed in the
2026-07-15 template revision).

## Motivating observation (generic)

The firm's study template maps every investable holding to one of seven
**purposes** and states policy as *target weight + asymmetric tolerance
band* per purpose. This differs from the existing allocation-vs-target lens
in three load-bearing ways:

1. **Different partition.** Purposes do not nest inside policy classes: one
   policy class can split across two purposes at the holding level (observed:
   the cash sleeve splits into a transactional-liquidity purpose and a
   short-duration-stability purpose). A pure class→purpose crosswalk is
   therefore **insufficient**; assignment must be resolvable per holding.
2. **Bands, not point targets.** Status is three-valued (below band /
   in band / above band) against `[min, max]` bounds — a holding-free
   purpose with a small positive target can still be *in band* when its
   lower band reaches 0. Variance-vs-target and band status are independent
   facts and both are reported.
3. **Same base, same total.** The purpose partition must reconcile to the
   identical investable base as the class partition — a structural
   consistency check the model can enforce to the penny.

## New objects

### 1. Purpose taxonomy (committed, generic)

```
_PURPOSE_LITERAL = Literal[
    "liquidity", "stability", "income", "growth",
    "aggressive_growth", "hedge", "community",
]
```

Fixed canonical ordering for deterministic rendering (as listed above).
The taxonomy is part of the committed crosswalk layer, like the seven
Wake Robin policy classes. Adding a purpose is a schema change, not config.

### 2. `PurposeTargetBand` (pydantic, strict)

```
purpose:        _PURPOSE_LITERAL
target:         Decimal   # fraction of investable base, >= 0, finite
lower_band_pp:  Decimal   # >= 0; band extends target - lower_band_pp, floored at 0
upper_band_pp:  Decimal   # >= 0; band extends target + upper_band_pp
```

Derived (never stored): `min_pct = max(0, target - lower_band_pp)`,
`max_pct = target + upper_band_pp`. Ordering `min <= target <= max` holds by
construction.

### 3. `EntityPurposePolicyConfig` (pydantic, strict — mirrors `EntityPolicyConfig`)

```
purpose_policy_version: str            # URL-safe
entity_id:              str            # no colons; must match fixture at lens time
bands:                  dict[_PURPOSE_LITERAL, PurposeTargetBand]
assignments:            dict[str, _PURPOSE_LITERAL]   # holding_key -> purpose (overrides)
default_by_policy_class: dict[_POLICY_CLASS_LITERAL, _PURPOSE_LITERAL]
```

Validators:
- `sum(target for bands) == 1.0` within the same tolerance as
  `EntityPolicyConfig` targets.
- Purposes omitted from `bands` have an implied 0% target with zero bands
  (still reported if the entity holds them — over-band by construction
  unless empty).
- `assignments` keys are not validated against a fixture at config-load
  time (config is fixture-independent); unknown keys **fail loud at lens
  time** (a stale assignment is an error, not a silent no-op).

### 4. Purpose resolution rule (locked)

For each holding in `fixture.holdings`:

1. If `holding_key in assignments` → that purpose.
2. Else if `holding.policy_class in default_by_policy_class` → that purpose.
3. Else → **raise** (fail loud; no silent "other" bucket).

The fixture schema itself is **unchanged** — no `purpose` field is added to
`HoldingRecord` or any segment record. Rationale: (a) purpose is policy,
not an observed fact of the holding; (b) fixture `content_hash` stability —
existing fixtures keep their hashes; (c) the same fixture can be studied
under alternative purpose policies without rebuilding.

### 5. `purpose_allocation_lens(fixture, purpose_policy) -> PurposeAllocation`

Frozen-dataclass result, same pattern as `allocation_vs_target_lens`:

Per-purpose row (all seven purposes, canonical order, including empty ones):
```
purpose, current_usd, current_pct, target_pct, min_pct, max_pct,
variance_pp, status, to_target_usd
```

- `current_usd` = Σ market value of holdings resolved to the purpose.
- Base = Σ investable segments (the same base the class lens uses).
- `status`: `below_band` if `current_pct < min_pct`; `above_band` if
  `current_pct > max_pct`; else `in_band`. **Bounds are inclusive.**
- `to_target_usd = target_pct × base − current_usd` (signed; positive = add).
- Structural invariant enforced in-lens: Σ `current_usd` over purposes
  == investable base **to the penny** (holdings are the source for both
  sides; a mismatch means holdings don't reconcile to segments and is
  raised, mirroring the holdings-detail lens contract).

### 6. Renderers + CLI

- `render_study_markdown`: new section `## Purpose allocation (goals-based)`
  rendered **only when a purpose policy is supplied**, placed immediately
  after the allocation-vs-target section. Columns mirror the lens row.
- `export_study_xlsx`: new sheet `Purpose Allocation`, same gating.
- CLI: optional `--purpose-policy PATH` (loads
  `EntityPurposePolicyConfig`; mutually independent of `--policy`).
- **No purpose policy ⇒ byte-identical output** to pre-Phase-26 renders.
  This is the same no-regression contract Phase 24 gave the no-entity path.

## Validation oracle (real workbook as golden — local only)

The real study workbook's `Purpose_Allocation` tab is the oracle, exercised
from a gitignored local script/config (never committed):

- Per-purpose current $, current %, variance pp, status, and to-target $
  reconcile **to the penny / to the workbook's own precision**.
- The holding-level split of one policy class across two purposes
  reproduces exactly (this is the case that kills a class-only crosswalk).
- Committed tests use synthetic fixtures only (see below).

## Determinism contract

Same as Phase 24: pure functions of (fixture, purpose_policy); Decimal
arithmetic; canonical purpose ordering; no wall clock; renderers are
display-format only. Two runs on the same inputs are byte-identical.

## What Phase 26 is **NOT**

- **Not a rebalancing mandate.** Band status is descriptive. No orders, no
  sizing, no coupling to allocators/optimizers.
- **Not a fixture schema change.** `EntityFixture` and all record types are
  untouched; existing content hashes are stable.
- **Not a replacement for the class lens.** Both dimensions render; no
  attempt to force them to agree beyond the shared-base reconciliation.
- **Not household aggregation.** Single entity, same as Phase 24.
- **Not band support for the class lens.** If wanted later, that is a
  separate amendment.

## Tests planned (synthetic fixtures only)

1. Config validation: targets sum to 1 (pass/fail), negative band rejected,
   band floor at 0 (min never negative), URL-safe version, strict extra-keys.
2. Resolution: explicit assignment overrides class default; unmapped holding
   raises; stale assignment key (no such holding) raises at lens time.
3. Lens: hand-worked three-status example (below/in/above), inclusive
   band edges (current == min and current == max are in_band), empty
   purpose with floor-0 band reports in_band, empty purpose with positive
   min reports below_band, Σ purposes == investable base, signed
   to-target arithmetic.
4. Class-split case: one policy class split across two purposes via
   assignments reconciles on both dimensions.
5. Renderers: no purpose policy ⇒ byte-identical markdown/xlsx; with
   policy ⇒ section/sheet present with expected rows; entity_id mismatch
   between fixture and purpose policy raises.
6. CLI: `--purpose-policy` happy path + missing-file failure.

## L-status implications

None closed, none opened. Purpose allocation is a reporting dimension; it
does not touch spending rules (L19) or PE pacing.

## SPEC amendment

Required at implementation time per SPEC §11 (same mechanism as Phase 24's
amendment commit): add the purpose dimension to the entity-study scope
statement. The amendment ships in the implementation series, not with this
lock.

## Privacy posture (load-bearing)

Committed: taxonomy, schemas, lens, renderers, synthetic tests — generic
only. Gitignored local: the real entity's purpose policy
(`data/external/*_purpose_policy_local.yaml`), its holding assignments, the
oracle harness, and any rendered study containing real values. No client
names, dollar values, fund names, or real targets/bands in committed files.

## Locked design choices (summary)

| # | Choice | Decision |
|---|--------|----------|
| 1 | Purpose taxonomy | 7 fixed literals, committed, canonical order |
| 2 | Where purpose lives | Policy config (assignments + class defaults), **not** the fixture |
| 3 | Resolution order | explicit holding assignment → class default → fail loud |
| 4 | Band semantics | asymmetric pp bands, min floored at 0, inclusive bounds |
| 5 | Status | three-valued vs [min,max]; independent of variance sign |
| 6 | Reconciliation | Σ purpose buckets == investable base, exact, enforced in-lens |
| 7 | Output gating | no purpose policy ⇒ byte-identical legacy output |
| 8 | Oracle | real workbook tab, local/gitignored; committed tests synthetic |

## Implementation gating & sub-steps

Implementation begins only on explicit operator **"go"** against this lock.
Proposed sub-steps (each independently green: full suite + ruff + byte-stability):

1. Schemas: `PurposeTargetBand`, `EntityPurposePolicyConfig`, taxonomy
   literal + loader (`load_entity_purpose_policy`). Tests group 1.
2. Resolution + lens (`purpose_allocation_lens`). Tests groups 2–4.
3. Renderers + CLI flag. Tests groups 5–6.
4. Local oracle validation vs the real workbook tab (no commit); record
   PASS/deltas in the implementation notes; doc-as-spec entry + SPEC
   amendment in the same series.
