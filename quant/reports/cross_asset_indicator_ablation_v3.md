# v2/v3 Cross-Asset Indicator Ablation

- status: **APPROVED_FOR_DEMO_SWITCH**
- v2 remains the Demo deployment unless every gate passes.
- global Macro-F1: `0.175910` -> `0.176269`
- global target exposure MAE: `0.063304` -> `0.063154`

| window | v2 Macro-F1 | v3 Macro-F1 | delta | v2 MAE | v3 MAE | MAE delta | gate |
|---|---:|---:|---:|---:|---:|---:|---|
| WF1 | 0.106147 | 0.107236 | +0.001089 | 0.033449 | 0.034565 | +0.001117 | PASS |
| WF2 | 0.158010 | 0.170608 | +0.012598 | 0.028988 | 0.029386 | +0.000398 | PASS |
| WF3 | 0.315782 | 0.345813 | +0.030031 | 0.033710 | 0.034440 | +0.000729 | PASS |

## Decision

All configured rollout gates pass. v3 is eligible for a safe Demo switch after stopping new orders, cancelling bot-created orders, preserving positions, and re-running account/WebSocket reconciliation.

Indicator values are only auditable model input evidence. They do not prove what the original trader used and do not imply profitability.
