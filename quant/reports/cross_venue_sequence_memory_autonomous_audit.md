# Cross-Venue Sequence-Memory Autonomous Audit

- status: **DEMO_CONTINUE_LIVE_BLOCKED**
- candidate: `behavioral-distillation-v4.0-sequence-memory`
- active Demo model changed: **no**

## Training contract

Only the chronological training fit segment receives deterministic zero-start and half-teacher-state variants for observed non-idle actions. Calibration, threshold selection, and every walk-forward test row remain untouched.

## Venue coverage

- `BITMEX`: `258492` rows; model-eligible global test rows `WF1=17561, WF2=8760, WF3=4773`.
- `HYPERLIQUID`: `5796` rows; model-eligible global test rows `WF1=0, WF2=0, WF3=0`.

## Strict autonomous costed replay

| window | net return | profit factor | target MAE | observed action rate | predicted action rate |
|---|---:|---:|---:|---:|---:|
| WF1 | 0.000000 | — | 0.090151 | 7.21% | 0.00% |
| WF2 | -0.000028 | 1.000252 | 0.257933 | 11.43% | 98.03% |
| WF3 | 0.004218 | 1.004397 | 0.410698 | 2.35% | 82.32% |

## Gates

- `causal_audit_pass`: **PASS**
- `all_walk_forward_windows_available`: **PASS**
- `target_coefficients_finite_and_bounded`: **PASS**
- `global_cross_venue_test_coverage`: **FAIL**
- `strict_autonomous_positive_all_windows`: **FAIL**
- `strict_autonomous_profit_factor_gt_one_all_windows`: **FAIL**
- `per_symbol_results_complete`: **PASS**

## Boundary

This is a causal behavioral approximation from public trade records. It does not prove exact strategy recovery, future profitability, or deployability; no credential, private endpoint, mainnet connection, or order was used.
