# JPM 2026 LTCMA — strategic allocation (max-Sharpe)

Study output of the JPM CMA profile (`configs/base_jpm.yaml`). Reporting/study
only — **not** a rebalancing mandate or a committed policy.

| field | value |
|---|---|
| CMA source | J.P. Morgan Asset Management LTCMA 2026 (USD), data as of 2025-09-30 |
| Engine | riskfolio, objective = max-Sharpe (`MV`) |
| Risk-free rate | 3.10% — sourced at runtime from the `cash` (U.S. Cash / 1–3mo T-bill) bucket |
| Policy size | $100,000,000 |
| Generated | 2026-07-17 |
| run_id | `aa-6c30f8eb2f48-2386a8b94fcf-20260717T212450Z-801e` |
| config_hash | `sha256:6c30f8eb2f488919ee72b9211aa2a47a81bf40d28ddab5ecfe84cb25914e19ee` |
| fixtures_hash | `sha256:2386a8b94fcff1d0bf31af069f3008e0117a2dffe5a996821d628a3858c9778b` |

## Allocation

| bucket | weight | $ (M) |
|---|---:|---:|
| fixed_income | 54.0% | 54.0 |
| real_estate | 24.0% | 24.0 |
| cash | 12.4% | 12.4 |
| pe_buyout | 8.1% | 8.1 |
| absolute_return | 1.6% | 1.6 |
| equity | 0.0% | 0.0 |
| **Total** | **100.0%** | **100.0** |

**Portfolio (derived):** expected return **6.19%** · volatility **4.22%** ·
Sharpe (excess/vol) **0.73**.

## Rationale

Unconstrained max-Sharpe on the JPM 2026 assumptions concentrates in the
assets with the best risk-adjusted return and diversifying correlations:

- **Real estate** and **private equity** carry the return (highest single-asset
  risk-adjusted returns in this set); PE is held below its raw appetite because
  of its high volatility.
- **Fixed income** takes the largest weight as efficient ballast — low
  volatility and low/negative correlation with real estate.
- **Cash** is efficient low-risk fill once the T-bill risk-free rate removes its
  excess return (without that rf it would dominate the solution).
- **Equity → 0%**: under JPM's 2026 numbers, U.S. large-cap has the weakest
  risk-adjusted profile in this universe, so the unconstrained optimum drops it.
  This is a property of the inputs, not a bug.

## Caveats

- **Unconstrained.** No policy floors/caps are applied, so a 0% equity / 54%
  fixed-income book is the pure risk-adjusted optimum, not a realistic SFO
  policy. A usable strategic allocation would add box constraints (e.g. minimum
  equity, maximum fixed income, PE pinned at the pacing target) via the
  allocator's `Constraints`.
- Universe is 6 buckets; `re_opco_stabilized` is excluded ($0, no JPM analog,
  and a perfect `real_estate` duplicate → singular covariance).
- riskfolio auto-repairs JPM's slightly non-positive-definite correlation matrix
  (benign).

## Distribution posture

JPM's LTCMA is institutional/qualified-investor material ("not for retail
distribution"). This report contains only the **derived allocation** (the
model's output). JPM's raw per-asset return / volatility / correlation
assumptions are **not** reproduced here and remain gitignored
(`data/external/jpm_ltcma_2026.yaml`, `configs/cma_jpm.yaml`).

## Reproduce

```bash
python scripts/build_cma_from_jpm.py --write      # regenerate the gitignored CMA
python -m aa_model.cli.main run --config configs/base_jpm.yaml
```
