# M0-02B-0.1 Execution Multiplier Validation

Validation uses Decimal only and the fixed raw-unit rule:

`expected_execCost_raw = signed_contract_qty × configured_multiplier_raw × canonical_execution_price`

Buy is positive and Sell is negative through `signed_contract_qty`. The original `lastPx` remains in the report for comparison; canonical prices come from the exact Decimal execution-price reconciliation. No tolerance or best-of-several rounding policy is used. Actual and expected raw XBt values are also normalized with the frozen wallet asset `scale` for audit display.

- Historical specs diagnosed: `11`
- Eligible validation rows: `7234`
- Exact matches: `7234`
- Raw lastPx mismatches: `1425`
- Canonical multiplier conflicts: `0`
- Execution-price unresolved rows: `0`
- Overall match ratio: `1.000000000000`

## Per-spec validation

| spec_id | symbol | declared | effective | trades | eligible | exact | mismatch | ratio | sign | status | blocking reason |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AAVEUSDT-QUANTO-XBT-2021 | AAVEUSDT | OFFICIAL_EXPLICIT | OFFICIAL_EXPLICIT | 402 | 402 | 402 | 0 | 1.000000000000 | PASS | PASS |  |
| ADAUSDT-QUANTO-XBT-2021 | ADAUSDT | OFFICIAL_EXPLICIT | OFFICIAL_EXPLICIT | 152 | 152 | 152 | 0 | 1.000000000000 | PASS | PASS |  |
| BNBUSDT-QUANTO-XBT-2021 | BNBUSDT | OFFICIAL_EXPLICIT | OFFICIAL_EXPLICIT | 113 | 113 | 113 | 0 | 1.000000000000 | PASS | PASS |  |
| DOGEUSDT-QUANTO-XBT-2021 | DOGEUSDT | OFFICIAL_EXPLICIT | OFFICIAL_EXPLICIT | 1735 | 1735 | 1735 | 0 | 1.000000000000 | PASS | PASS |  |
| DOTUSDT-QUANTO-XBT-2021 | DOTUSDT | OFFICIAL_EXPLICIT | OFFICIAL_EXPLICIT | 3359 | 3359 | 3359 | 0 | 1.000000000000 | PASS | PASS_WITH_PRICE_PRECISION_RECONCILIATION |  |
| LINKUSDT-QUANTO-XBT-2020 | LINKUSDT | OFFICIAL_EXPLICIT | OFFICIAL_EXPLICIT | 232 | 232 | 232 | 0 | 1.000000000000 | PASS | PASS_WITH_PRICE_PRECISION_RECONCILIATION |  |
| LUNAUSD-QUANTO-XBT-2021 | LUNAUSD | OFFICIAL_EXPLICIT | OFFICIAL_EXPLICIT | 358 | 358 | 358 | 0 | 1.000000000000 | PASS | PASS |  |
| ORDIUSD-QUANTO-XBT-2023 | ORDIUSD | OFFICIAL_EXPLICIT | OFFICIAL_EXPLICIT | 9 | 9 | 9 | 0 | 1.000000000000 | PASS | PASS |  |
| TRXUSDT-QUANTO-XBT-2021 | TRXUSDT | OFFICIAL_EXPLICIT | OFFICIAL_EXPLICIT | 15 | 15 | 15 | 0 | 1.000000000000 | PASS | PASS |  |
| UNIUSDT-QUANTO-XBT-2021 | UNIUSDT | OFFICIAL_PARTIAL_EXECUTION_VALIDATED | OFFICIAL_PARTIAL_EXECUTION_VALIDATED | 806 | 806 | 806 | 0 | 1.000000000000 | PASS | PASS |  |
| XLMUSDT-QUANTO-XBT-2021 | XLMUSDT | OFFICIAL_PARTIAL_EXECUTION_VALIDATED | OFFICIAL_PARTIAL_EXECUTION_VALIDATED | 53 | 53 | 53 | 0 | 1.000000000000 | PASS | PASS |  |

## Ineligible rows

- None.

Mismatch examples are capped at 200 rows in `multiplier_validation_mismatches.csv`; the per-spec counts remain complete.
