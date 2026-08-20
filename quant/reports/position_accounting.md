# M0-02B-1B-0 仓位成本与平均入场价回放

> 本阶段只重放衍生品仓位数量、成本、平均入场价、仓位周期和毛已实现交易 PnL；不对 Wallet History 做最终对账，不计算净现金流、未实现 PnL、净值、杠杆或保证金。

## 执行摘要

- `position_accounting_status`: **BLOCKED**
- `m0_02b1b1_readiness`: **BLOCKED_BY_ACCOUNTING_ROUNDING_POLICY**
- source commit: `f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6`
- analysis commit: `dd6bf27442ebc2f36b6fc189b13c746d0791673f`
- branch: `quant/m0-02b1b-position-accounting-replay`
- 处理行数: `173226`；Spot 进入 accounting: `0`。

## Accounting eligibility

| status | count | meaning |
| --- | --- | --- |
| ACCOUNTING_ELIGIBLE | 22926 | eligible |
| ACCOUNTING_ELIGIBLE_WITH_WARNING | 150300 | eligible |

`PASS` 和 `WARNING` 均被处理；只有 `BLOCKED` 才会阻塞本阶段。费用诊断 warning 不会把真实 Trade 排除。

## 覆盖与动作

| execType | count |
| --- | --- |
| Funding | 12905 |
| Settlement | 19 |
| Trade | 160510 |

| action | count |
| --- | --- |
| ADD_LONG | 50952 |
| ADD_SHORT | 27978 |
| CLOSE_LONG | 886 |
| CLOSE_SHORT | 344 |
| FLIP_LONG_TO_SHORT | 91 |
| FLIP_SHORT_TO_LONG | 79 |
| NO_POSITION_CHANGE | 12905 |
| OPEN_LONG | 898 |
| OPEN_SHORT | 333 |
| REDUCE_LONG | 53580 |
| REDUCE_SHORT | 25180 |

- flip count: `170`; full close count: `1230`; position cycle count: `1401`。

## Cost conservation

| check | failure count |
| --- | --- |
| exact currentCost identity | 0 |
| API raw currentCost identity | 0 |
| flip execCost split | 0 |
| full-close residual cost | 0 |
| Settlement residual cost | 0 |
| flat terminal residual cost | 0 |

`execCost_raw` remains signed and authoritative. The exact layer may contain rational values during partial release or flip splitting; the API layer is an integer projection under one fixed policy, and the two legs always sum to the original raw cost.

## Rounding policy audit

- selected average-cost release: `None`
- selected flip execCost split: `None`
- ambiguity count: `0`
- selection reason: no candidate policy satisfies conservation and terminal currentCost anchors

详表见 `cost_rounding_policy_audit.csv`。没有 execID 或 symbol 级 override，也没有逐行择优舍入。

## Average entry price

AEP 独立于 currentCost。Quanto/Linear 使用 Decimal 数量加权；Inverse 使用规格 lot_size / canonical price 的聪值 basis，长仓 ROUND_FLOOR 到 8 位，空头按配置的 ROUND_HALF_UP 到 8 位。不得使用 avgPx，也不得用 currentCost / currentQty 反推 AEP。

## Settlement 与周期

- Settlement rows: `19`; applied close rows: `19`。
- 非零终态 symbol: `['XBTUSD']`。
- Funding 不改变 quantity、currentCost、AEP、cycle 或 gross trading PnL；Settlement 必须完整关闭并清零成本/AEP。

## 每个 symbol 的终态

| symbol | qty | currentCost API | AEP | cycle count |
| --- | --- | --- | --- | --- |
| XBTUSD | -998000 | 1386445848 | 71982.618490822464968098336702587628720357600841946133345892107878589169521669517386375861191593009783898288650769001163067364823586717576221993137280942905343504535017594693555225292123462257237167290 | 688 |

## XBTUSD snapshot reconciliation

| field | reconstructed | snapshot | status |
| --- | --- | --- | --- |
| currentQty | -998000 | -998000 | PASS |
| currentCost | 1386445848 | 1386445811 | BLOCKED |
| posCost | 1386445848 | 1386445811 | BLOCKED |
| avgEntryPrice displayed | 71982.6185 | 71982.3211 | BLOCKED |
| avgCostPrice displayed | 71982.6185 | 71982.3211 | BLOCKED |

Snapshot AEP comparison uses only the declared `Decimal('0.0001')` / ROUND_HALF_UP display quantization; no tolerance is used.

## reported realisedPnl diagnostics

- non-null: `15739`; exact: `0`; mismatch: `15739`; missing: `157487`。
- maximum absolute difference raw: `2516254`。
- reported realisedPnl never updates state and is not automatically combined with execComm or Funding. 詳細分布见 `reported_realised_pnl_diagnostics.csv`。

## Gross realised PnL

| currency | gross realised PnL exact raw |
| --- | --- |
| XBT | 12949758767.78637640858647551 |

## 未解决异常与边界

- blockers: `["no candidate policy satisfies conservation and terminal currentCost anchors", "XBTUSD snapshot reconciliation failed", "rounding policy selection did not pass"]`
- warnings: `["150300 valuation warnings remained accounting-eligible", "15739 reported realisedPnl rows differ from reconstructed gross trading PnL; diagnostic only"]`
- `position_accounting_anomalies.csv` 最多保留 200 个样例；完整逐 Execution 明细只写入被 `.gitignore` 保护的 Parquet。

## 输出

- ignored: `quant/outputs/position_accounting_events.parquet`
- committed summaries: terminal_position_accounting.csv, position_accounting_by_symbol.csv, position_action_summary.csv, cost_rounding_policy_audit.csv, xbtusd_snapshot_reconciliation.csv, reported_realised_pnl_diagnostics.csv, position_accounting_anomalies.csv
