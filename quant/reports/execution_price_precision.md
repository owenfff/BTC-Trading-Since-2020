# M0-02B-0.2 Historical Execution Price Precision

- Formula: `Quanto: execCost / (signed_contract_qty * multiplier_raw); Inverse: signed_contract_qty * multiplier_raw / execCost`
- Policy: EXACT equality; recovered only with official tick-grid equality and an exact signed one-tick delta; no tolerance or rounding selection
- Configured historical Trade rows: **7234**
- EXACT: **5809**
- RECOVERED: **1425**
- UNRESOLVED: **0**
- Raw lastPx mismatches: **1425**

## Per-spec summary

| Spec | Symbol | Trades | EXACT | RECOVERED | UNRESOLVED | Tick | Implied on grid | Canonical exact | Status |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| AAVEUSDT-QUANTO-XBT-2021 | AAVEUSDT | 402 | 402 | 0 | 0 |  | 0.000000000000 | 402 | PASS |
| ADAUSDT-QUANTO-XBT-2021 | ADAUSDT | 152 | 152 | 0 | 0 | 0.00001 | 1.000000000000 | 152 | PASS |
| BNBUSDT-QUANTO-XBT-2021 | BNBUSDT | 113 | 113 | 0 | 0 | 0.01 | 1.000000000000 | 113 | PASS |
| DOGEUSDT-QUANTO-XBT-2021 | DOGEUSDT | 1735 | 1735 | 0 | 0 | 0.00001 | 1.000000000000 | 1735 | PASS |
| DOTUSDT-QUANTO-XBT-2021 | DOTUSDT | 3359 | 1990 | 1369 | 0 | 0.0005 | 1.000000000000 | 3359 | PASS |
| LINKUSDT-QUANTO-XBT-2020 | LINKUSDT | 232 | 176 | 56 | 0 | 0.0005 | 1.000000000000 | 232 | PASS |
| LUNAUSD-QUANTO-XBT-2021 | LUNAUSD | 358 | 358 | 0 | 0 |  | 0.000000000000 | 358 | PASS |
| ORDIUSD-QUANTO-XBT-2023 | ORDIUSD | 9 | 9 | 0 | 0 |  | 0.000000000000 | 9 | PASS |
| TRXUSDT-QUANTO-XBT-2021 | TRXUSDT | 15 | 15 | 0 | 0 |  | 0.000000000000 | 15 | PASS |
| UNIUSDT-QUANTO-XBT-2021 | UNIUSDT | 806 | 806 | 0 | 0 |  | 0.000000000000 | 806 | PASS |
| XLMUSDT-QUANTO-XBT-2021 | XLMUSDT | 53 | 53 | 0 | 0 |  | 0.000000000000 | 53 | PASS |

## Candidate-field diagnostics

The candidate fields are diagnostic only: `avgPx` is not assumed to equal a single Trade price; `price` is not automatically a fill price; notional ratios require instrument and sign semantics; `cost_implied_price` is derived from the account-cost identity.

### AAVEUSDT-QUANTO-XBT-2021

| Candidate | Available in raw mismatch rows | Exact to cost-implied | Semantic note |
| --- | ---: | ---: | --- |
| lastPx | 0 | 0 | public Execution price; may have display precision loss |
| avgPx | 0 | 0 | execution-average field; not assumed to equal a single Trade price |
| price | 0 | 0 | order/execution price field; not promoted without exact semantic proof |
| cost_implied_price | 0 | 0 | derived from account-cost identity; canonical only after official-price rules |
| foreignNotional_over_homeNotional | 0 | 0 | not used unless quote/base semantics and sign are valid |

### ADAUSDT-QUANTO-XBT-2021

| Candidate | Available in raw mismatch rows | Exact to cost-implied | Semantic note |
| --- | ---: | ---: | --- |
| lastPx | 0 | 0 | public Execution price; may have display precision loss |
| avgPx | 0 | 0 | execution-average field; not assumed to equal a single Trade price |
| price | 0 | 0 | order/execution price field; not promoted without exact semantic proof |
| cost_implied_price | 0 | 0 | derived from account-cost identity; canonical only after official-price rules |
| foreignNotional_over_homeNotional | 0 | 0 | not used unless quote/base semantics and sign are valid |

### BNBUSDT-QUANTO-XBT-2021

| Candidate | Available in raw mismatch rows | Exact to cost-implied | Semantic note |
| --- | ---: | ---: | --- |
| lastPx | 0 | 0 | public Execution price; may have display precision loss |
| avgPx | 0 | 0 | execution-average field; not assumed to equal a single Trade price |
| price | 0 | 0 | order/execution price field; not promoted without exact semantic proof |
| cost_implied_price | 0 | 0 | derived from account-cost identity; canonical only after official-price rules |
| foreignNotional_over_homeNotional | 0 | 0 | not used unless quote/base semantics and sign are valid |

### DOGEUSDT-QUANTO-XBT-2021

| Candidate | Available in raw mismatch rows | Exact to cost-implied | Semantic note |
| --- | ---: | ---: | --- |
| lastPx | 0 | 0 | public Execution price; may have display precision loss |
| avgPx | 0 | 0 | execution-average field; not assumed to equal a single Trade price |
| price | 0 | 0 | order/execution price field; not promoted without exact semantic proof |
| cost_implied_price | 0 | 0 | derived from account-cost identity; canonical only after official-price rules |
| foreignNotional_over_homeNotional | 0 | 0 | not used unless quote/base semantics and sign are valid |

### DOTUSDT-QUANTO-XBT-2021

| Candidate | Available in raw mismatch rows | Exact to cost-implied | Semantic note |
| --- | ---: | ---: | --- |
| lastPx | 1369 | 0 | public Execution price; may have display precision loss |
| avgPx | 1369 | 1359 | execution-average field; not assumed to equal a single Trade price |
| price | 1369 | 0 | order/execution price field; not promoted without exact semantic proof |
| cost_implied_price | 1369 | 1369 | derived from account-cost identity; canonical only after official-price rules |
| foreignNotional_over_homeNotional | 1369 | 0 | not used unless quote/base semantics and sign are valid |

### LINKUSDT-QUANTO-XBT-2020

| Candidate | Available in raw mismatch rows | Exact to cost-implied | Semantic note |
| --- | ---: | ---: | --- |
| lastPx | 56 | 0 | public Execution price; may have display precision loss |
| avgPx | 56 | 44 | execution-average field; not assumed to equal a single Trade price |
| price | 56 | 0 | order/execution price field; not promoted without exact semantic proof |
| cost_implied_price | 56 | 56 | derived from account-cost identity; canonical only after official-price rules |
| foreignNotional_over_homeNotional | 56 | 0 | not used unless quote/base semantics and sign are valid |

### LUNAUSD-QUANTO-XBT-2021

| Candidate | Available in raw mismatch rows | Exact to cost-implied | Semantic note |
| --- | ---: | ---: | --- |
| lastPx | 0 | 0 | public Execution price; may have display precision loss |
| avgPx | 0 | 0 | execution-average field; not assumed to equal a single Trade price |
| price | 0 | 0 | order/execution price field; not promoted without exact semantic proof |
| cost_implied_price | 0 | 0 | derived from account-cost identity; canonical only after official-price rules |
| foreignNotional_over_homeNotional | 0 | 0 | not used unless quote/base semantics and sign are valid |

### ORDIUSD-QUANTO-XBT-2023

| Candidate | Available in raw mismatch rows | Exact to cost-implied | Semantic note |
| --- | ---: | ---: | --- |
| lastPx | 0 | 0 | public Execution price; may have display precision loss |
| avgPx | 0 | 0 | execution-average field; not assumed to equal a single Trade price |
| price | 0 | 0 | order/execution price field; not promoted without exact semantic proof |
| cost_implied_price | 0 | 0 | derived from account-cost identity; canonical only after official-price rules |
| foreignNotional_over_homeNotional | 0 | 0 | not used unless quote/base semantics and sign are valid |

### TRXUSDT-QUANTO-XBT-2021

| Candidate | Available in raw mismatch rows | Exact to cost-implied | Semantic note |
| --- | ---: | ---: | --- |
| lastPx | 0 | 0 | public Execution price; may have display precision loss |
| avgPx | 0 | 0 | execution-average field; not assumed to equal a single Trade price |
| price | 0 | 0 | order/execution price field; not promoted without exact semantic proof |
| cost_implied_price | 0 | 0 | derived from account-cost identity; canonical only after official-price rules |
| foreignNotional_over_homeNotional | 0 | 0 | not used unless quote/base semantics and sign are valid |

### UNIUSDT-QUANTO-XBT-2021

| Candidate | Available in raw mismatch rows | Exact to cost-implied | Semantic note |
| --- | ---: | ---: | --- |
| lastPx | 0 | 0 | public Execution price; may have display precision loss |
| avgPx | 0 | 0 | execution-average field; not assumed to equal a single Trade price |
| price | 0 | 0 | order/execution price field; not promoted without exact semantic proof |
| cost_implied_price | 0 | 0 | derived from account-cost identity; canonical only after official-price rules |
| foreignNotional_over_homeNotional | 0 | 0 | not used unless quote/base semantics and sign are valid |

### XLMUSDT-QUANTO-XBT-2021

| Candidate | Available in raw mismatch rows | Exact to cost-implied | Semantic note |
| --- | ---: | ---: | --- |
| lastPx | 0 | 0 | public Execution price; may have display precision loss |
| avgPx | 0 | 0 | execution-average field; not assumed to equal a single Trade price |
| price | 0 | 0 | order/execution price field; not promoted without exact semantic proof |
| cost_implied_price | 0 | 0 | derived from account-cost identity; canonical only after official-price rules |
| foreignNotional_over_homeNotional | 0 | 0 | not used unless quote/base semantics and sign are valid |

The complete configured-history per-Trade fields, including original `lastPx` and `canonical_execution_price`, are in `execution_price_precision_trades.csv` and the `trades` array in JSON. `unresolved.csv` is capped at 200 samples and is empty when all configured historical rows resolve.
