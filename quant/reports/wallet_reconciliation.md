# Wallet Reconciliation

- status: **READY_WITH_WARNINGS**
- analysis commit: `1166e23eff2da21afb5ec3447cccbebf77971295`
- source commit: `f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6`
- raw wallet rows: `17484`
- completed rows: `17482`; pending/canceled rows excluded from balance continuity: `2`
- raw inputs unchanged: **True**

## Unit and currency boundary

Each amount remains an integer raw wallet unit and also has a Decimal major-unit view using the frozen wallet-assets scale. Currencies are never combined without an explicit conversion source. USDt Conversion and SpotTrade remain separate transaction groups.

## Coverage

| check | value |
| --- | ---: |
| continuity PASS rows | 17474 |
| continuity mismatch rows | 5 |
| continuity batches | 14292 |
| continuity mismatch batches | 5 |
| currencies | BMEX, USDT, XBT |
| snapshot exact PASS rows | 3 / 15 |
| snapshot zero-without-history rows | 12 |
| snapshot unresolved/mismatch rows | 0 |
| equity terminal status | PASS |

## Wallet / Execution / Funding comparison

The comparison is aggregate-only. A difference does not claim a broken row-level mapping because wallet rows do not carry a universally unique execution reference.

| wallet type | execution type | currency | wallet raw | execution raw | difference | status |
| --- | --- | --- | ---: | ---: | ---: | --- |
| RealisedPNL | Trade | USDT | None | 0 | None | NOT_COMPARABLE_NO_WALLET_OR_EXECUTION_VALUE |
| RealisedPNL | Trade | XBT | 9505857152 | 1543389629 | 7962467523 | AGGREGATE_DIFFERENCE |
| Funding | Funding | XBT | 129849982 | 1526046326 | -1396196344 | AGGREGATE_DIFFERENCE |

## Snapshot and equity boundaries

Wallet snapshot, margin snapshot, and derived equity curve are retained as separate evidence. Margin balance and unrealised PnL are not added to wallet cash.

## Next action

Use this ledger's per-event and per-day features to build BTC-first order episodes, decision episodes, and trade cycles; carry wallet and reconciliation confidence into each episode.

## Outputs

- ignored: `quant/outputs/wallet_ledger.parquet`, `quant/outputs/wallet_daily_ledger.parquet`
- committed: wallet_reconciliation.json, wallet_reconciliation_by_day.csv, wallet_reconciliation_by_type.csv, wallet_reconciliation_anomalies.csv
