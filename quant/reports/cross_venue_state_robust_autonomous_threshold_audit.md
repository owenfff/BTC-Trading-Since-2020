# Cross-Venue State-Robust Autonomous-Threshold Audit

- status: **DEMO_CONTINUE_LIVE_BLOCKED**
- candidate: `behavioral-distillation-v3.9-state-robust-autonomous-threshold`
- active Demo model changed: **no**

## Training contract

Only the chronological training fit segment receives deterministic zero-start and half-teacher-state variants for observed non-idle actions. Calibration, threshold selection, and every walk-forward test row remain untouched.

## Venue coverage

- `BITMEX`: `258492` rows; model-eligible global test rows `WF1=17561, WF2=8760, WF3=4773`.
- `HYPERLIQUID`: `5796` rows; model-eligible global test rows `WF1=0, WF2=0, WF3=0`.

## Strict autonomous costed replay

| window | net return | profit factor | target MAE | observed action rate | predicted action rate |
|---|---:|---:|---:|---:|---:|
| WF1 | -0.262682 | 0.954884 | 0.498413 | 7.21% | 95.73% |
| WF2 | 0.001748 | 1.002534 | 0.280270 | 11.43% | 99.98% |
| WF3 | 0.253175 | 1.037702 | 0.848301 | 2.35% | 100.00% |

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
