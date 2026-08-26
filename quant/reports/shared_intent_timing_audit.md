# Shared Intent Timing Audit

> Diagnostic only. A venue-neutral timing head is fitted on 60%, calibrated on 20%, and evaluated on an untouched final 20% per venue.

| venue | train | calibration | untouched test | selected threshold | timing F1 | predicted action rate | net return |
|---|---:|---:|---:|---:|---:|---:|---:|
| `BITMEX` | 155095 | 44714 | 41996 | 0.050000 | 0.000000 | 0.00% | -0.004365 |
| `HYPERLIQUID` | 3477 | 1159 | 1160 | 0.150000 | 0.000000 | 0.00% | 0.000000 |

## Interpretation

The timing head is judged separately from action type. High F1 without stable costed autonomous execution is insufficient; an all-NO_TRADE classifier is explicitly treated as a failed action-timing candidate when the holdout contains actions.

## Boundary

No credentials, private endpoint, mainnet connection, or order was used. The active Demo model remains unchanged and raw CSV/JSON inputs remain read-only.
