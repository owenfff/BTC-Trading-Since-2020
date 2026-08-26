# Cross-Venue Temporal Autonomous Audit

- status: **DEMO_CONTINUE_LIVE_BLOCKED**
- candidate: `behavioral-distillation-v3.5-cost-calibrated-threshold`
- baseline: `behavioral-distillation-v3.2-event-supervision-baseline`
- dataset rows: `264288`; explicit `NO_TRADE` rate: `95.1322%`
- active Demo model changed: **no**

## Causal audit

- status: **PASS**
- `invalid_decision_time`: `0`
- `future_market_bar`: `0`
- `future_funding`: `0`
- `non_strict_clock_order`: `0`
- `non_future_label`: `0`

## Strict autonomous costed replay

| window | temporal net | event baseline net | temporal PF | baseline PF | temporal target MAE | no-trade observed | no-trade predicted |
|---|---:|---:|---:|---:|---:|---:|---:|
| WF1 | 0.018150 | -3.507125 | 1.040171 | 1.079083 | 0.129250 | 92.79% | 99.91% |
| WF2 | -0.135907 | -0.022724 | 0.995126 | 1.002916 | 1.137246 | 88.57% | 5.31% |
| WF3 | -0.002102 | -0.097926 | 0.994616 | 0.976761 | 0.106268 | 97.65% | 99.77% |

## Gates

- `causal_audit_pass`: **PASS**
- `all_walk_forward_windows_available`: **PASS**
- `target_coefficients_finite_and_bounded`: **PASS**
- `strict_autonomous_positive_all_windows`: **FAIL**
- `strict_autonomous_profit_factor_gt_one_all_windows`: **FAIL**
- `temporal_model_beats_event_baseline_net_all_windows`: **FAIL**

## Boundary

This report measures whether a robot trained on a market clock can reproduce behavior while using its own simulated state. It does not prove the original trader used these indicators, does not promise profitability, and does not activate the Demo model.
