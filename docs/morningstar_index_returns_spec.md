# Morningstar Direct — Historical Index-Return Ingestion Spec

Durable pathway for ingesting Morningstar Direct index returns into the Asset
Allocation Study Model as a clean, auditable return store, with metadata sufficient
to map each index to the model's asset classes, CMA calibration, Monte Carlo
assumptions, and study exhibits.

> **Status:** export ingestion implemented and validated against the June-30-2026
> workbook. Live/API fetch is intentionally **deferred** (see §9).

---

## 1. Where this sits relative to the existing Morningstar/CMA code

There are now **two** Morningstar pathways; they are complementary:

| Pathway | Module | Source | Cadence | Purpose |
|---|---|---|---|---|
| Empirical CMA calibration (pre-existing) | `aa_model.assumptions.benchmark_calibration` | `morningstar_feed` (`C:\Projects\morningstar`) | **daily** TR series, live/module | vol / correlation / trailing return for 3 buckets → candidate `cma.yaml` (diagnostic) |
| **Index-return ingestion (this spec)** | `aa_model.ingestion.morningstar_returns` | Morningstar Direct **export workbook** | **monthly** export, file-based | broad 36-index normalized store + coverage/audit |

This pathway does **not** modify the daily-feed adapter and does **not** change any
allocation recommendation. It is additive and default-off (nothing in the
orchestrator imports it).

## 2. Components

```
configs/morningstar_index_universe.yaml   # index basket + Morningstar id/symbol mapping + metadata
configs/asset_class_index_map.yaml        # asset_class -> primary/secondary/fallback index_key
src/aa_model/ingestion/morningstar_schemas.py    # Pydantic v2 schemas + vocabularies
src/aa_model/ingestion/morningstar_returns.py     # parser + normalizer + coverage + consumption
scripts/import_morningstar_index_returns.py       # CLI (dry-run default; --write to persist)
tests/test_morningstar_index_returns.py           # synthetic-fixture tests (no licensed data)
data/vendor/morningstar/raw/                       # gitignored: raw exports live here
data/normalized/morningstar_index_returns.parquet  # gitignored: normalized output
reports/morningstar_index_coverage.csv             # gitignored: coverage report
```

## 3. The source workbook (`Index Returns - <date>.xlsx`)

Place the manual export under `data/vendor/morningstar/raw/` (gitignored). The
primary tab is **`Common Indices`**.

**Layout — a cross-sectional trailing-return snapshot, NOT a monthly series.**
One row per index; columns are trailing windows:

| Column header (exact) | Horizon | Annualized |
|---|---|---|
| `Total Ret 1 Mo (Mo-End) Base Currency` | `1M` | no |
| `Total Ret 3 Mo (Mo-End) Base Currency` | `3M` | no |
| `Total Ret 6 Mo (Mo-End) Base Currency` | `6M` | no |
| `Total Ret 1 Yr (Mo-End) Base Currency` | `1Y` | no |
| `Total Ret Annlzd 3 Yr (Mo-End) Base Currency` | `3Y_ann` | yes |
| `Total Ret Annlzd 5 Yr (Mo-End) Base Currency` | `5Y_ann` | yes |
| `Total Ret Annlzd 10 Yr (Mo-End) Base Currency` | `10Y_ann` | yes |
| `Total Ret Annlzd 15 Yr (Mo-End) Base Currency` | `15Y_ann` | yes |
| `Total Ret Inception (Mo-End) Base Currency` | `inception_ann` | yes |

Other columns (`Gross Ret …`, `Load-Adj Ret …`, `Investor Ret …`, `… % Rank Cat …`,
yields, cumulative inception) are ignored. Columns are matched by **exact header
name**, so column reordering does not break the parser.

**Critical parsing rules (all enforced):**

1. Real index rows are the rows **above** `Summary Statistics`. Rows labelled
   `Summary Statistics`, `Eightieth/Sixtieth/Fortieth/Twentieth Percentile`, `Sum`,
   `Average`, `Count`, `Maximum`, `Minimum`, `Median`, `Standard Deviation` are
   **never** ingested (parsing stops at the summary block).
2. The workbook may carry a copied summary view (e.g. `Common Indices (2)`). Only
   `Common Indices` is read unless `--sheet` says otherwise.
3. **The filename date is not the return date.** Each row's `Return Date (Mo-End)`
   is parsed and validated independently. In the June-30-2026 file most rows are
   `2026-03-31`, but Credit Suisse Hedge Fund is `2025-10-31`, both NCREIF series
   are `2025-12-31`, S&P UBS Leveraged Loan is `2025-05-31`, and Galene is
   `2026-02-28`. These are flagged `STALE_SERIES`.
4. **Values are percentage points.** `1.25` → `0.0125`. Conversion happens exactly
   once (`--value-scale percent`, the default). Pass `--value-scale decimal` if a
   source is already decimal (no division).
5. NCREIF rows have a blank `1 Mo` (quarterly source). They are **not** forced to
   monthly: `frequency = quarterly_or_monthly_source`, no interpolation, and the
   blank `1M` cell is emitted as a `NaN` row flagged `MISSING_MONTH`.

The parser also accepts two generic layouts for hand-built series: **wide**
(`Date` in column 0, one column per index display name) and **long**
(`date` / `index`(`name`) / `value`(`return`) columns). Leading title rows above
the table are tolerated. Ambiguous inputs **fail loudly** with a sample of the
detected columns.

## 4. Normalized store (long by horizon)

One row per `(index_key, date, horizon)`. The `horizon == "1M"` slice at a
month-end date is the canonical **monthly total return** series consumed by the
model. Columns (fixed order):

`date, index_key, horizon, return_decimal, annualized, level, currency, source,
source_field, return_type, frequency, asof_date, fetched_at_utc, vendor_id,
quality_flag, notes`

* `return_decimal` — decimal (not percent); `NaN` when the source cell is blank.
* `asof_date` — the ingestion as-of (`--asof`, else the modal row return date).
* `source_field` — the exact Morningstar column header (or `wide:<name>` / `long:<field>`).
* `quality_flag` — `OK` or a pipe-joined, sorted subset of the flags below.

### Quality flags

`OK`, `MISSING_MONTH`, `DUPLICATE_DATE`, `NON_MONTH_END_DATE`, `EXTREME_RETURN`
(|ret| > 0.60), `STALE_SERIES` (row date < as-of), `SHORT_HISTORY` (no 5Y/10Y
annualized value), `CURRENCY_MISMATCH`, `RETURN_TYPE_UNKNOWN`. Non-month-end dates
are **normalized** (snapped to month-end) and flagged, not rejected.

## 5. Coverage report

CSV with **one row per configured index** (every index in the universe appears,
even if absent from the workbook):

`index_key, display_name, asset_class, sub_asset_class, model_role,
present_in_workbook, return_date, first_observation_date, last_observation_date,
n_monthly_observations, n_horizons, missing_months, stale_series, return_type,
currency, currency_flag, return_type_flag, short_history_flag, quality_flags, notes`

Validate coverage (no unexpected `stale_series`, no `absent_from_workbook`,
expected `n_horizons`) **before** using any series in a study.

## 6. Commands

Dry run (validate + preview, writes nothing — the default):

```bash
python scripts/import_morningstar_index_returns.py \
  --input "data/vendor/morningstar/raw/Index Returns - June 30 2026.xlsx" \
  --universe configs/morningstar_index_universe.yaml \
  --asset-class-map configs/asset_class_index_map.yaml \
  --output data/normalized/morningstar_index_returns.parquet \
  --coverage-report reports/morningstar_index_coverage.csv \
  --dry-run
```

Persist the normalized store + coverage report:

```bash
python scripts/import_morningstar_index_returns.py \
  --input "data/vendor/morningstar/raw/Index Returns - June 30 2026.xlsx" \
  --universe configs/morningstar_index_universe.yaml \
  --asset-class-map configs/asset_class_index_map.yaml \
  --output data/normalized/morningstar_index_returns.parquet \
  --coverage-report reports/morningstar_index_coverage.csv \
  --write
```

Flags: `--sheet` (default `Common Indices`), `--asof YYYY-MM-DD`, `--value-scale
{percent,decimal}`, `--allow-unmapped` (permit workbook rows not in the universe),
`--allow-missing-configured` (permit configured indices absent from the workbook).
Without the `--allow-*` flags, either mismatch **fails loudly**.

## 7. How to export from Morningstar Direct for this importer

1. In Morningstar Direct, open the index/benchmark list and add the data columns
   **Total Ret 1 Mo / 3 Mo / 6 Mo / 1 Yr / Annlzd 3 / 5 / 10 / 15 Yr / Inception
   (Mo-End) Base Currency**, plus `Return Date (Mo-End)` and `Base Currency`.
2. Export to Excel. Keep the sheet named `Common Indices` (or pass `--sheet`).
3. Save into `data/vendor/morningstar/raw/` — **do not commit it** (§10).
4. Run the dry-run command; fix any `STALE_SERIES` / unmapped warnings; then `--write`.

## 8. Adding an index / mapping to an asset class

* **New index:** add an entry to `configs/morningstar_index_universe.yaml` with a
  snake_case `index_key`, the **byte-exact** Morningstar `display_name`, asset
  class, region, currency, `return_type`, `frequency`, and `model_role`. Leave
  `morningstar_id` / `morningstar_symbol` `null` until confirmed from an approved
  Morningstar source — **never guess vendor IDs.**
* **Map to an asset class:** add/extend an entry in
  `configs/asset_class_index_map.yaml`. Prefer broad market indices as
  `primary_index_key`; sector proxies (biotech, banks, Mag7) and ETFs are
  `reporting_only`/proxy roles, not primary benchmarks. Custom proxies (e.g.
  `galene_credit_fund_proxy_returns`) carry `requires_approval: true` and must be
  explicitly approved before driving CMA calibration. All referenced index_keys are
  validated to exist in the universe at load time.

## 9. Live / API fetch — DEFERRED

Live fetch is **not** implemented. The existing licensed access
(`morningstar_feed` / `MORNINGSTAR_FEED_DIR`) is a **daily** feed with a different
column model; wiring a monthly index-export fetch would need a Morningstar Direct
data-request definition that does not yet exist in the repo. When added, it must:
credentials only via env vars / untracked local config (never in-repo); no live
fetch in tests; no scheduled/background fetch; polite rate limiting; cache raw
responses under `data/vendor/morningstar/raw/`; and stamp `fetched_at_utc` /
`asof_date` on outputs. Until then, use the manual export path above.

## 10. Licensing / secrets safeguards

`.gitignore` excludes all licensed data and any series derived from it:
`data/vendor/`, `data/normalized/*` (except `.gitkeep`), `reports/morningstar_*`,
plus `configs/morningstar_credentials_local.yaml` and `.env.morningstar`. Only
**code, schemas, configs, docs, tiny synthetic fixtures, and tests** are committed.
Tests build synthetic fixtures in `tmp_path` and never read a real export.

## 11. Model consumption

`aa_model.ingestion.morningstar_returns` exposes read helpers that preserve
existing behavior when the store is absent (all optional, lazy):

* `load_normalized_returns(path)` — load the parquet/CSV store.
* `monthly_return_series(df, index_key)` — the canonical 1M decimal series.
* `trailing_return(df, index_key, horizon)` — a stored trailing figure.
* `index_keys_for_asset_class(map_cfg, asset_class, sub_asset_class)` — resolve the
  primary/secondary/fallback index_keys (+ `requires_approval`) for CMA / Monte
  Carlo / exhibit sourcing.

CMA calibration, Monte Carlo assumptions, and study exhibits select series by
`index_key`; when the store is missing, callers fall back to `configs/cma.yaml`
unchanged.
