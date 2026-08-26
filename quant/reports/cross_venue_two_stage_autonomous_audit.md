# Cross-Venue Two-Stage Autonomous Audit

- status: **DEMO_CONTINUE_LIVE_BLOCKED**
- candidate: `behavioral-distillation-v3.7-two-stage-action-target`
- active Demo model changed: **no**

## Model contract

The timing head predicts whether exposure changes. The action/target head is trained only on non-idle actions, then the final signal is replayed from zero simulated state.

## Venue coverage

- `BITMEX`: `258492` rows; model-eligible global test rows `WF1=17561, WF2=8760, WF3=4773`.
- `HYPERLIQUID`: `5796` rows; model-eligible global test rows `WF1=0, WF2=0, WF3=0`.

## Strict autonomous costed replay

| window | net return | profit factor | target MAE | observed action rate | predicted action rate |
|---|---:|---:|---:|---:|---:|
| WF1 | 0.000000 | — | 0.090151 | 7.21% | 0.00% |
| WF2 | -0.048939 | 0.933658 | 0.266388 | 11.43% | 22.36% |
| WF3 | 0.000000 | — | 0.138184 | 2.35% | 0.00% |

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
