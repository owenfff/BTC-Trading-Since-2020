# Accounting Foundation Manifest

- Status: **HIGH_CONFIDENCE_WITH_RESIDUALS**
- Downstream behavioral research: **READY_WITH_KNOWN_ACCOUNTING_RESIDUALS**
- Teacher data: `TRADE_RECORDS_ONLY`
- Analysis commit: `86be1f430ece5c64237b2dfc133842124119101c`
- Source position-accounting report analysis commit: `2b4b9fbe17c22281b45ae3d07867e94295c28d6a`
- Raw inputs unchanged: **True**

## Dual ledger boundary

The exchange-reported ledger preserves exchange and wallet values. The analytical ledger reconstructs quantity, execution cost, gross PnL, AEP, cycles, and confidence flags. They are never silently summed or substituted for one another.

## Count checks

| Dataset | Expected | Actual | Status |
| --- | ---: | ---: | --- |
| Raw Execution | 173434 | 173434 | PASS |
| Derivative Execution | 173226 | 173226 | PASS |
| Raw Trade | 160510 | 160510 | PASS |
| Derivative Trade | 160302 | 160302 | PASS |
| Funding | 12905 | 12905 | PASS |
| Settlement | 19 | 19 | PASS |
| Spot Trade | 208 | 208 | PASS |

## Fidelity contract

- `quantity_fidelity`: `EXACT`
- `execution_price_fidelity`: `EXACT_OR_AUDITED_RECOVERED`
- `fee_fidelity`: `REPORTED_EXCHANGE_VALUE`
- `funding_fidelity`: `REPORTED_EXCHANGE_VALUE`
- `wallet_fidelity`: `PENDING_WALLET_RECONCILIATION`
- `current_cost_engine_fidelity`: `HIGH_CONFIDENCE_WITH_RESIDUAL`
- `aep_engine_fidelity`: `HIGH_CONFIDENCE_WITH_ENGINE_SEMANTICS_UNRESOLVED`
- `execution_order_fidelity`: `PARTIAL_WITH_CONFIDENCE_FLAGS`

## Known residuals

- Closest analytical cost candidate differs from snapshot by about 2 raw units.
- Displayed analytical AEP differs from snapshot by 0.2974; exchange engine semantics remain unresolved.
- These residuals remain explicit limitations and do not block downstream behavioral research.

## Next action

Build wallet ledger with raw/major currency separation and day/hour/terminal reconciliation.
