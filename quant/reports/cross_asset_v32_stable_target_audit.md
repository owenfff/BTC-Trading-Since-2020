# v3.2 Stable Target Audit

- status: **DEMO_CONTINUE_LIVE_BLOCKED**
- candidate: `behavioral-distillation-v3.2-stable-target`
- active model changed: **no**
- target regression: ridge λ = `1.0`

## Strict autonomous results

| window | v3 net | v3.2 net | v3 PF | v3.2 PF | v3 max coefficient | v3.2 max coefficient |
|---|---:|---:|---:|---:|---:|---:|
| WF1 | -0.622667 | -0.177838 | 0.944398 | 0.911508 | 138240021121.450623 | 0.275375 |
| WF2 | -0.124975 | -0.036691 | 0.997446 | 0.992108 | 22841296698.888840 | 0.275375 |
| WF3 | -0.285413 | -0.048754 | 0.964485 | 0.960893 | 28096047923.432228 | 0.275375 |

## Gates

- `target_coefficients_finite_and_bounded`: **PASS**
- `strict_autonomous_positive_all_windows`: **FAIL**
- `strict_autonomous_profit_factor_gt_one_all_windows`: **FAIL**
- `candidate_has_test_results_for_all_windows`: **PASS**

## Boundary

The candidate reduces the numerical failure from target-regression collinearity, but costed strict autonomous replay remains below the promotion bar. It stays a non-active candidate; no Demo model switch or new order is authorized.
