# Cross-Venue State-Robust Autonomous Audit

- status: **DEMO_CONTINUE_LIVE_BLOCKED**
- candidate: `behavioral-distillation-v3.8-state-robust-action-target`
- active Demo model changed: **no**

## Training contract

Only the chronological training fit segment receives deterministic zero-start and half-teacher-state variants for observed non-idle actions. Calibration, threshold selection, and every walk-forward test row remain untouched.

## Venue coverage

- `BITMEX`: `258492` rows; model-eligible global test rows `WF1=17561, WF2=8760, WF3=4773`.
- `HYPERLIQUID`: `5796` rows; model-eligible global test rows `WF1=0, WF2=0, WF3=0`.

## Strict autonomous costed replay

| window | net return | profit factor | target MAE | observed action rate | predicted action rate |
|---|---:|---:|---:|---:|---:|
| WF1 | -3.514461 | 0.823073 | 0.834064 | 7.21% | 100.00% |
| WF2 | -0.103915 | 0.999159 | 0.774508 | 11.43% | 100.00% |
| WF3 | 0.229969 | 1.035073 | 0.852344 | 2.35% | 100.00% |

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
