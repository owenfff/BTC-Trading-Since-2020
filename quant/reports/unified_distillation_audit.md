# Unified Distillation v4.6 Audit

- status: **CANDIDATE_NOT_PROMOTED**
- model: `behavioral-distillation-v4.6-unified-distillation`
- feature contract: `m16-unified-cross-venue-distillation`
- frozen cutoff: `2026-07-18T21:17:31.514000Z`
- dataset SHA256: `3db0b050ec3f4c5602cf3c682e1a5bd8a2c8bbff0a21c5f304e0bebfafbafc69`
- model SHA256: `695648b77b77e249afc3c6981dcea5ccf58c74a2861eb98db29eb13d8c9bb508`
- track 1: `CONDITIONAL_BEHAVIOR`
- track 2: `STRICT_AUTONOMOUS_REPLAY` from zero state
- source venue is used for balancing/reporting only, not as a learned signal
- coverage policy: unavailable Hyperliquid windows are reported and excluded; no synthetic or substituted rows are used
- candidate promotion gates: **FAIL**
- rollout authorization: **no**
- active v3 Demo model changed: **no**
- Demo orders submitted by this audit: **no**

## Coverage

- `WF1`: {'BITMEX': {'rows': 2635, 'eligible_rows': 2462, 'status': 'PASS'}, 'HYPERLIQUID': {'rows': 0, 'eligible_rows': 0, 'status': 'INSUFFICIENT_COVERAGE'}}
- `WF2`: {'BITMEX': {'rows': 1653, 'eligible_rows': 1653, 'status': 'PASS'}, 'HYPERLIQUID': {'rows': 128, 'eligible_rows': 128, 'status': 'PASS'}}
- `WF3`: {'BITMEX': {'rows': 263, 'eligible_rows': 263, 'status': 'PASS'}, 'HYPERLIQUID': {'rows': 193, 'eligible_rows': 192, 'status': 'PASS'}}

## Promotion gates

- `time_leakage_zero`: **PASS**
- `protected_raw_hashes_unchanged`: **PASS**
- `available_venue_WF1_coverage`: **PASS**
- `strict_autonomous_positive_WF1`: **FAIL**
- `strict_autonomous_profit_factor_WF1`: **PASS**
- `available_venue_WF2_coverage`: **PASS**
- `strict_autonomous_positive_WF2`: **FAIL**
- `strict_autonomous_profit_factor_WF2`: **FAIL**
- `available_venue_WF3_coverage`: **PASS**
- `strict_autonomous_positive_WF3`: **PASS**
- `strict_autonomous_profit_factor_WF3`: **PASS**
- `behavior_macro_f1_not_worse_WF1`: **FAIL**
- `behavior_target_mae_not_worse_WF1`: **FAIL**
- `behavior_macro_f1_not_worse_WF2`: **PASS**
- `behavior_target_mae_not_worse_WF2`: **FAIL**
- `behavior_macro_f1_not_worse_WF3`: **PASS**
- `behavior_target_mae_not_worse_WF3`: **FAIL**

## Interpretation

This report evaluates a unified behavioral approximation. It does not recover private triggers, prove profitability, or authorize mainnet/live trading.

## Outputs

- `quant\reports\unified_distillation_by_window.csv`
- `quant\reports\unified_distillation_by_venue.csv`
- `quant\reports\unified_distillation_cost_sensitivity.csv`
