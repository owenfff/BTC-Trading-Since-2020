# Shared Intent / Venue-Native Layer Audit

> Diagnostic only. One venue-neutral intent model is fitted on the first 60%; exposure layers use the next 20%; the final 20% is untouched.

| venue | train | calibration | untouched test | base net return | layered net return | base actions | layered actions |
|---|---:|---:|---:|---:|---:|---:|---:|
| `BITMEX` | 155095 | 44714 | 41996 | 0.000000 | 0.000000 | 0.00% | 0.00% |
| `HYPERLIQUID` | 3477 | 1159 | 1160 | 0.000000 | 0.000000 | 0.00% | 0.00% |

## Interpretation

A useful result would preserve intent while making the venue-native layer explainable and stable on the untouched slice. A positive return is not a profitability guarantee; a negative result does not prove the trader changed strategy.

## Boundary

No credentials, private endpoint, mainnet connection, or order was used. The active Demo model remains unchanged and raw CSV/JSON inputs remain read-only.
