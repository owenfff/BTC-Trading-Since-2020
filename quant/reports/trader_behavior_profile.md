# Trader Behavior Profile

- status: **READY_WITH_WARNINGS**
- analysis commit: `8866448fc183929078caf418b09de7307c16d02b`
- source commit: `f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6`
- teacher data: `TRADE_RECORDS_ONLY`
- strategy fidelity: `BEHAVIORAL_APPROXIMATION`

## Layered dataset

Raw fills are not treated as independent decisions. The dataset keeps a visible chain from fills to order episodes, execution batches, position actions, decision episodes, and zero-to-zero position cycles.

| layer | rows |
| --- | ---: |
| raw_execution_rows | 173434 |
| derivative_trade_fills | 160302 |
| execution_batches | 62388 |
| order_episodes | 31702 |
| decision_episodes | 32231 |
| trade_cycles | 1401 |

## BTC-first boundary

- XBTUSD trade actions: `98874`; order episodes: `20316`; decisions: `20845`; cycles: `688`.
- Altcoin and non-XBTUSD derivative behavior remains in the layered outputs for generalization diagnostics; it does not redefine the BTC teacher scope.
- Daily synthetic observations provide `HOLD_LONG`, `HOLD_SHORT`, and `NO_TRADE` samples only for XBTUSD and are marked synthetic.

## Confidence and accounting boundary

Every action, decision, and cycle carries ordering, action, accounting, price, wallet, and overall confidence. Wallet confidence is aggregate-only because wallet history cannot prove a universal row-level execution join. Exchange internal currentCost and AEP are not used as exact teacher labels.

- wallet reconciliation status: `READY_WITH_WARNINGS`
- downstream accounting status: `READY_WITH_KNOWN_ACCOUNTING_RESIDUALS`
- accounting engine audit status: `BLOCKED` (residual policy audit is retained, not silently repaired)
- execution-order audit: `READY_WITH_AMBIGUOUS_CROSS_ORDER_TIES`
- raw inputs unchanged: **True**

## Output format

- `trade_actions`: `csv_fallback_no_parquet_engine` at `quant\outputs\trade_actions.csv` (`160302` rows).
- `order_episodes`: `csv_fallback_no_parquet_engine` at `quant\outputs\order_episodes.csv` (`31702` rows).
- `decision_episodes`: `csv_fallback_no_parquet_engine` at `quant\outputs\decision_episodes.csv` (`32231` rows).
- `trade_cycles`: `csv_fallback_no_parquet_engine` at `quant\outputs\trade_cycles.csv` (`1401` rows).

The requested Parquet outputs are ignored by Git. If the local runtime lacks the pinned Parquet engine, the script writes a clearly labeled ignored CSV fallback and keeps the same schema; installing `quant/requirements.txt` restores Parquet output.

## Next action

Acquire and freeze public BTC canonical market context before constructing leakage-safe features and labels.
