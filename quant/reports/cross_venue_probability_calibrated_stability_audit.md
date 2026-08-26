# Cross-Venue Probability Calibration and Stability Audit

- status: **DEMO_CONTINUE_LIVE_BLOCKED**
- candidate: `behavioral-distillation-v3.6-probability-calibrated`
- active Demo model changed: **no**
- dataset rows: `264288`

## Venue coverage

- `BITMEX`: `258492` rows, `2020-05-02T00:00:00.000Z` to `2026-07-18T20:00:00.000Z`; raw global test rows `WF1=24671, WF2=8760, WF3=4773`; model-eligible global test rows `WF1=17561, WF2=8760, WF3=4773`.
- `HYPERLIQUID`: `5796` rows, `2025-11-15T18:00:00.000Z` to `2026-07-15T05:00:00.000Z`; raw global test rows `WF1=0, WF2=1110, WF3=4686`; model-eligible global test rows `WF1=0, WF2=0, WF3=0`.
- A venue with no global test rows is not silently treated as validated; its within-venue holdout appears below as diagnostic-only.

## Temporal calibration contract

Fit uses the first 60% of each training window, probability calibration uses the next 20%, and threshold selection uses the final 20%. The walk-forward test interval is untouched until evaluation.

## Strict autonomous costed replay

| window | net return | profit factor | target MAE | observed no-trade | predicted no-trade | stable symbols |
|---|---:|---:|---:|---:|---:|---:|
| WF1 | 0.000000 | — | 0.090124 | 92.79% | 100.00% | 3 |
| WF2 | 0.000000 | — | 0.219395 | 88.57% | 100.00% | 1 |
| WF3 | 0.000000 | — | 0.138184 | 97.65% | 100.00% | 1 |

## Per-symbol stability

- Minimum sample for a stable-symbol statistic: `100` rows.
- Detail CSV: `quant\reports\cross_venue_probability_calibrated_by_symbol.csv`.
- `WF1`: `3` stable symbols; positive-net fraction `0.0`; PF>1 fraction `None`.
- `WF2`: `1` stable symbols; positive-net fraction `0.0`; PF>1 fraction `None`.
- `WF3`: `1` stable symbols; positive-net fraction `0.0`; PF>1 fraction `None`.

## Native venue diagnostics

- `HYPERLIQUID` (`DIAGNOSTIC_ONLY`): train `4636`, test `1160`, strict net `0.0029506384214426085`, PF `1.011048263029534`. This does not satisfy the global cross-venue gate.

## Gates

- `causal_audit_pass`: **PASS**
- `all_walk_forward_windows_available`: **PASS**
- `calibration_nll_not_worse_on_training_holdouts`: **PASS**
- `target_coefficients_finite_and_bounded`: **PASS**
- `global_cross_venue_test_coverage`: **FAIL**
- `strict_autonomous_positive_all_windows`: **FAIL**
- `strict_autonomous_profit_factor_gt_one_all_windows`: **FAIL**
- `per_symbol_results_complete`: **PASS**

## Boundary

This is a causal behavioral approximation from public trade records. It does not prove exact strategy recovery, future profitability, or deployability; credentials, private endpoints, mainnet connections, and orders were not used.
