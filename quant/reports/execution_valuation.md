# M0-02B-1A Execution 价值、费用与币种单位标准化

> 本报告只做 Execution 价值字段的单位标准化与组件拆分；不计算平均成本、策略 PnL、未实现 PnL、净值、杠杆或保证金，也不连接交易所。

## 执行摘要

- Status: **READY_WITH_WARNINGS**
- Readiness: **READY_FOR_POSITION_ACCOUNTING_REPLAY**
- Source commit: `f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6`
- Analysis commit: `a3a0b3ca1633c979a38fd149f61a834105ab4da1`
- Raw Execution rows: `173434`; derivative rows: `173226`; output rows: `173226`.
- Components: `362191`; each component remains separate and no cross-currency net cashflow is produced.

## 数据边界与关联

| 检查 | 结果 | 预期/说明 |
| --- | --- | --- |
| Raw Execution | 173434 | 173434 |
| Trade / Funding / Settlement | 160510/12905/19 | 160510 / 12905 / 19 |
| Derivative executions | 173226 | 173226 |
| Derivative Trade | 160302 | 160302 |
| Spot Trade excluded | 208 | 208 |
| execID uniqueness | 0 | 0 duplicates |
| Order rows read | 43251 | dimension input only |
| Wallet history rows read | 17484 | cash ledger is not reconstructed here |

- Derivative input/output join equality: **True** (`173226` → `173226`).
- Historical spec mapping rows: `173226`; status counts: `{"MATCHED": 173226}`.
- Compatibility status counts: `{"PASS": 173226}`.

## 币种与 scale

`api-v1-wallet-assets.csv` is the frozen scale registry. Raw monetary fields are interpreted as integer smallest units and converted with `major = raw / 10**scale` using Decimal only.

| settlement currency | scale | executions | scale coverage | missing |
| --- | --- | --- | --- | --- |
| XBT | 8 | 173226 | 1.000000000000 | 0 |

- Commission currency source counts: `{"EVENT_SETTL_CURRENCY_FALLBACK": 172089, "EXEC_COMM_CCY": 1137}`.
- Commission source priority: `execCommCcy` → event `settlCurrency` only when it matches the resolved specification → specification settlement currency. No quote-currency fallback is used.
- `homeNotional` and `foreignNotional` are retained as Decimal text fields without applying wallet-asset scale.

## 字段拆分与会计边界

| component type | currency | count | raw signed sum | major signed sum | failures |
| --- | --- | --- | --- | --- | --- |
| EXECUTION_COST_REFERENCE | XBT | 12905 | 5335415492101 | 53354.15492101 | 0 |
| FUNDING_PAYMENT | XBT | 12905 | 1526046326 | 15.26046326 | 0 |
| POSITION_COST | XBT | 160302 | -4593810828 | -45.93810828 | 0 |
| REPORTED_REALISED_PNL | XBT | 15739 | 1662631236 | 16.62631236 | 0 |
| SETTLEMENT_COMMISSION | XBT | 19 | 0 | 0 | 0 |
| SETTLEMENT_POSITION_VALUE_REFERENCE | XBT | 19 | -6969502127 | -69.69502127 | 0 |
| TRADE_FEE_OR_REBATE | XBT | 160302 | 1788005306 | 17.88005306 | 0 |

- `execCost` on Trade is `POSITION_COST`, not wallet cashflow; on Funding it is a non-cash execution-cost reference; on Settlement it is a position-value reference.
- `execComm` keeps the original signed value and is classified as trade fee/rebate, funding payment, or settlement commission according to `execType`.
- `realisedPnl` remains an independent reported field/component. It is not added to fees or funding; its overlap with future wallet/PnL reconciliation is explicitly left unresolved.

## 原始金额字段统计与 round-trip

| field | total | missing | zero | positive | negative | invalid | non-integer |
| --- | --- | --- | --- | --- | --- | --- | --- |
| execCost | 173226 | 0 | 0 | 91690 | 81536 | 0 | 0 |
| execComm | 173226 | 0 | 541 | 109864 | 62821 | 0 | 0 |
| realisedPnl | 173226 | 157487 | 0 | 4818 | 10921 | 0 | 0 |

- Raw → major → raw exact round-trip failures: `0`.
- Normalization status counts: `{"WARNING": 150300, "PASS": 22926}`.
- Missing remains distinct from zero. Fractional raw amounts and malformed raw amounts are blocking anomalies; this run does not auto-repair them.

## Funding

| symbol | currency | events | + execComm | - execComm | zero | missing | raw sum | major sum | failures |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AAVEUSDT | XBT | 164 | 164 | 0 | 0 | 0 | 9794978 | 0.09794978 | 0 |
| ADAUSD | XBT | 75 | 73 | 2 | 0 | 0 | 14107344 | 0.14107344 | 0 |
| ADAUSDT | XBT | 3 | 3 | 0 | 0 | 0 | 2528167 | 0.02528167 | 0 |
| ALTMEXUSD | XBT | 19 | 19 | 0 | 0 | 0 | 111797 | 0.00111797 | 0 |
| AXSUSDT | XBT | 88 | 11 | 77 | 0 | 0 | 5089608 | 0.05089608 | 0 |
| BCHUSD | XBT | 28 | 27 | 1 | 0 | 0 | 2579566 | 0.02579566 | 0 |
| BMEXUSD | XBT | 29 | 29 | 0 | 0 | 0 | 881486 | 0.00881486 | 0 |
| BNBUSD | XBT | 2 | 2 | 0 | 0 | 0 | 30551 | 0.00030551 | 0 |
| BNBUSDT | XBT | 72 | 66 | 6 | 0 | 0 | 1677055 | 0.01677055 | 0 |
| DOGEUSD | XBT | 2273 | 2261 | 12 | 0 | 0 | 59966235 | 0.59966235 | 0 |
| DOGEUSDT | XBT | 333 | 308 | 25 | 0 | 0 | 65141629 | 0.65141629 | 0 |
| DOTUSDT | XBT | 147 | 144 | 3 | 0 | 0 | 134372207 | 1.34372207 | 0 |
| ETHUSD | XBT | 1574 | 1056 | 517 | 1 | 0 | 612843039 | 6.12843039 | 0 |
| LINKUSDT | XBT | 21 | 21 | 0 | 0 | 0 | 13162360 | 0.13162360 | 0 |
| LTCUSD | XBT | 878 | 870 | 8 | 0 | 0 | 296270713 | 2.96270713 | 0 |
| LUNAUSD | XBT | 70 | 45 | 25 | 0 | 0 | 2189273 | 0.02189273 | 0 |
| ORDIUSD | XBT | 397 | 397 | 0 | 0 | 0 | 11258 | 0.00011258 | 0 |
| TRXUSDT | XBT | 11 | 11 | 0 | 0 | 0 | 137522 | 0.00137522 | 0 |
| UNIUSDT | XBT | 83 | 83 | 0 | 0 | 0 | 30687657 | 0.30687657 | 0 |
| XBTUSD | XBT | 6006 | 2592 | 3411 | 3 | 0 | 183807344 | 1.83807344 | 0 |
| XLMUSDT | XBT | 1 | 1 | 0 | 0 | 0 | 410048 | 0.00410048 | 0 |
| XRPUSD | XBT | 631 | 581 | 50 | 0 | 0 | 90246489 | 0.90246489 | 0 |

- Funding does not change contract quantity. Its signed `execComm` is retained as the funding-payment component; `execCost` is not silently treated as funding cashflow.

## Trade fees / rebates

| symbol | currency | liquidity | trades | + fee | - fee | zero | formula exact | diagnostic diff |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| AAVEUSDT | XBT | AddedLiquidity | 374 | 0 | 374 | 0 | 11 | 363 |
| AAVEUSDT | XBT | RemovedLiquidity | 28 | 28 | 0 | 0 | 1 | 27 |
| ADAM20 | XBT | AddedLiquidity | 241 | 0 | 204 | 37 | 0 | 241 |
| ADAM20 | XBT | RemovedLiquidity | 125 | 122 | 3 | 0 | 0 | 125 |
| ADAUSD | XBT | AddedLiquidity | 462 | 0 | 462 | 0 | 9 | 453 |
| ADAUSD | XBT | RemovedLiquidity | 38 | 38 | 0 | 0 | 3 | 35 |
| ADAUSDT | XBT | AddedLiquidity | 134 | 0 | 134 | 0 | 49 | 85 |
| ADAUSDT | XBT | RemovedLiquidity | 18 | 18 | 0 | 0 | 2 | 16 |
| ALTMEXUSD | XBT | AddedLiquidity | 43 | 0 | 43 | 0 | 1 | 42 |
| ALTMEXUSD | XBT | RemovedLiquidity | 8 | 8 | 0 | 0 | 0 | 8 |
| AXSUSDT | XBT | AddedLiquidity | 804 | 0 | 804 | 0 | 209 | 595 |
| AXSUSDT | XBT | RemovedLiquidity | 27 | 27 | 0 | 0 | 4 | 23 |
| BCHH21 | XBT | AddedLiquidity | 76 | 0 | 76 | 0 | 23 | 53 |
| BCHH21 | XBT | RemovedLiquidity | 25 | 25 | 0 | 0 | 17 | 8 |
| BCHUSD | XBT | AddedLiquidity | 67 | 0 | 67 | 0 | 4 | 63 |
| BCHUSD | XBT | RemovedLiquidity | 59 | 59 | 0 | 0 | 2 | 57 |
| BMEXUSD | XBT | AddedLiquidity | 96 | 0 | 75 | 21 | 4 | 92 |
| BMEXUSD | XBT | RemovedLiquidity | 18 | 18 | 0 | 0 | 0 | 18 |
| BNBUSD | XBT | AddedLiquidity | 18 | 0 | 18 | 0 | 0 | 18 |
| BNBUSD | XBT | RemovedLiquidity | 8 | 8 | 0 | 0 | 0 | 8 |
| BNBUSDT | XBT | AddedLiquidity | 92 | 0 | 92 | 0 | 0 | 92 |
| BNBUSDT | XBT | RemovedLiquidity | 21 | 21 | 0 | 0 | 0 | 21 |
| DOGEUSD | XBT | AddedLiquidity | 2445 | 1172 | 1093 | 180 | 203 | 2242 |
| DOGEUSD | XBT | RemovedLiquidity | 1206 | 1197 | 0 | 9 | 29 | 1177 |
| DOGEUSDT | XBT | AddedLiquidity | 1374 | 0 | 1374 | 0 | 101 | 1273 |
| DOGEUSDT | XBT | RemovedLiquidity | 361 | 361 | 0 | 0 | 12 | 349 |
| DOTUSDT | XBT | AddedLiquidity | 3312 | 0 | 3312 | 0 | 301 | 3011 |
| DOTUSDT | XBT | RemovedLiquidity | 47 | 47 | 0 | 0 | 2 | 45 |
| DOTUSDTH21 | XBT | AddedLiquidity | 33 | 0 | 33 | 0 | 0 | 33 |
| DOTUSDTH21 | XBT | RemovedLiquidity | 16 | 15 | 1 | 0 | 1 | 15 |
| EOSH21 | XBT | AddedLiquidity | 18 | 0 | 18 | 0 | 0 | 18 |
| EOSH21 | XBT | RemovedLiquidity | 19 | 19 | 0 | 0 | 5 | 14 |
| EOSUSDTZ20 | XBT | AddedLiquidity | 5 | 0 | 5 | 0 | 0 | 5 |
| EOSUSDTZ20 | XBT | RemovedLiquidity | 2 | 2 | 0 | 0 | 0 | 2 |
| ETHH21 | XBT | AddedLiquidity | 708 | 0 | 708 | 0 | 344 | 364 |
| ETHH21 | XBT | RemovedLiquidity | 429 | 429 | 0 | 0 | 168 | 261 |
| ETHH22 | XBT | AddedLiquidity | 345 | 0 | 345 | 0 | 28 | 317 |
| ETHH22 | XBT | RemovedLiquidity | 132 | 132 | 0 | 0 | 24 | 108 |
| ETHH23 | XBT | AddedLiquidity | 262 | 262 | 0 | 0 | 47 | 215 |
| ETHH23 | XBT | RemovedLiquidity | 128 | 128 | 0 | 0 | 11 | 117 |
| ETHH24 | XBT | AddedLiquidity | 29 | 29 | 0 | 0 | 0 | 29 |
| ETHH24 | XBT | RemovedLiquidity | 5 | 5 | 0 | 0 | 0 | 5 |
| ETHM20 | XBT | AddedLiquidity | 35 | 0 | 35 | 0 | 0 | 35 |
| ETHM20 | XBT | RemovedLiquidity | 51 | 51 | 0 | 0 | 0 | 51 |
| ETHM21 | XBT | AddedLiquidity | 135 | 0 | 135 | 0 | 14 | 121 |
| ETHM21 | XBT | RemovedLiquidity | 43 | 43 | 0 | 0 | 16 | 27 |
| ETHM22 | XBT | AddedLiquidity | 160 | 0 | 160 | 0 | 18 | 142 |
| ETHM22 | XBT | RemovedLiquidity | 73 | 70 | 3 | 0 | 20 | 53 |
| ETHM23 | XBT | AddedLiquidity | 307 | 105 | 202 | 0 | 31 | 276 |
| ETHM23 | XBT | RemovedLiquidity | 43 | 43 | 0 | 0 | 4 | 39 |
| ETHM24 | XBT | AddedLiquidity | 218 | 218 | 0 | 0 | 6 | 212 |
| ETHM24 | XBT | RemovedLiquidity | 63 | 63 | 0 | 0 | 1 | 62 |
| ETHU20 | XBT | AddedLiquidity | 89 | 0 | 89 | 0 | 0 | 89 |
| ETHU20 | XBT | RemovedLiquidity | 132 | 132 | 0 | 0 | 0 | 132 |
| ETHU21 | XBT | AddedLiquidity | 440 | 0 | 440 | 0 | 139 | 301 |
| ETHU21 | XBT | RemovedLiquidity | 36 | 36 | 0 | 0 | 18 | 18 |
| ETHU22 | XBT | AddedLiquidity | 23 | 0 | 23 | 0 | 2 | 21 |
| ETHU22 | XBT | RemovedLiquidity | 24 | 24 | 0 | 0 | 0 | 24 |
| ETHU23 | XBT | AddedLiquidity | 137 | 137 | 0 | 0 | 3 | 134 |
| ETHU23 | XBT | RemovedLiquidity | 42 | 42 | 0 | 0 | 3 | 39 |
| ETHU24 | XBT | AddedLiquidity | 150 | 150 | 0 | 0 | 5 | 145 |
| ETHU24 | XBT | RemovedLiquidity | 6 | 6 | 0 | 0 | 0 | 6 |
| ETHUSD | XBT | AddedLiquidity | 8523 | 632 | 7891 | 0 | 283 | 8240 |
| ETHUSD | XBT | RemovedLiquidity | 9373 | 9365 | 8 | 0 | 448 | 8925 |
| ETHUSDZ20 | XBT | AddedLiquidity | 5 | 0 | 5 | 0 | 0 | 5 |
| ETHUSDZ20 | XBT | RemovedLiquidity | 3 | 3 | 0 | 0 | 0 | 3 |
| ETHZ20 | XBT | AddedLiquidity | 859 | 0 | 859 | 0 | 547 | 312 |
| ETHZ20 | XBT | RemovedLiquidity | 308 | 308 | 0 | 0 | 175 | 133 |
| ETHZ21 | XBT | AddedLiquidity | 710 | 0 | 710 | 0 | 120 | 590 |
| ETHZ21 | XBT | RemovedLiquidity | 159 | 159 | 0 | 0 | 29 | 130 |
| ETHZ22 | XBT | AddedLiquidity | 161 | 0 | 161 | 0 | 11 | 150 |
| ETHZ22 | XBT | RemovedLiquidity | 21 | 19 | 2 | 0 | 2 | 19 |
| ETHZ23 | XBT | AddedLiquidity | 196 | 196 | 0 | 0 | 12 | 184 |
| ETHZ23 | XBT | RemovedLiquidity | 74 | 74 | 0 | 0 | 3 | 71 |
| ETHZ24 | XBT | AddedLiquidity | 70 | 70 | 0 | 0 | 7 | 63 |
| ETHZ24 | XBT | RemovedLiquidity | 9 | 9 | 0 | 0 | 2 | 7 |
| LINKUSDT | XBT | AddedLiquidity | 196 | 0 | 196 | 0 | 50 | 146 |
| LINKUSDT | XBT | RemovedLiquidity | 36 | 35 | 1 | 0 | 3 | 33 |
| LINKUSDTZ20 | XBT | AddedLiquidity | 3 | 0 | 3 | 0 | 0 | 3 |
| LINKUSDTZ20 | XBT | RemovedLiquidity | 13 | 13 | 0 | 0 | 4 | 9 |
| LTCH21 | XBT | AddedLiquidity | 1221 | 0 | 1221 | 0 | 517 | 704 |
| LTCH21 | XBT | RemovedLiquidity | 193 | 193 | 0 | 0 | 56 | 137 |
| LTCM20 | XBT | AddedLiquidity | 244 | 0 | 244 | 0 | 0 | 244 |
| LTCM20 | XBT | RemovedLiquidity | 143 | 143 | 0 | 0 | 0 | 143 |
| LTCM21 | XBT | AddedLiquidity | 158 | 0 | 158 | 0 | 22 | 136 |
| LTCM21 | XBT | RemovedLiquidity | 14 | 13 | 1 | 0 | 2 | 12 |
| LTCU20 | XBT | AddedLiquidity | 159 | 0 | 159 | 0 | 0 | 159 |
| LTCU20 | XBT | RemovedLiquidity | 157 | 157 | 0 | 0 | 0 | 157 |
| LTCU21 | XBT | AddedLiquidity | 394 | 0 | 394 | 0 | 16 | 378 |
| LTCU21 | XBT | RemovedLiquidity | 23 | 23 | 0 | 0 | 5 | 18 |
| LTCUSD | XBT | AddedLiquidity | 4688 | 650 | 4038 | 0 | 275 | 4413 |
| LTCUSD | XBT | RemovedLiquidity | 1907 | 1903 | 4 | 0 | 99 | 1808 |
| LTCZ20 | XBT | AddedLiquidity | 617 | 0 | 617 | 0 | 221 | 396 |
| LTCZ20 | XBT | RemovedLiquidity | 198 | 196 | 2 | 0 | 80 | 118 |
| LTCZ21 | XBT | AddedLiquidity | 105 | 0 | 105 | 0 | 24 | 81 |
| LTCZ21 | XBT | RemovedLiquidity | 17 | 17 | 0 | 0 | 4 | 13 |
| LUNAUSD | XBT | AddedLiquidity | 296 | 0 | 296 | 0 | 17 | 279 |
| LUNAUSD | XBT | RemovedLiquidity | 62 | 62 | 0 | 0 | 2 | 60 |
| ORDIUSD | XBT | AddedLiquidity | 9 | 9 | 0 | 0 | 1 | 8 |
| TRXH21 | XBT | AddedLiquidity | 2080 | 0 | 2044 | 36 | 78 | 2002 |
| TRXH21 | XBT | RemovedLiquidity | 138 | 135 | 1 | 2 | 32 | 106 |
| TRXM20 | XBT | AddedLiquidity | 102 | 0 | 99 | 3 | 0 | 102 |
| TRXM20 | XBT | RemovedLiquidity | 35 | 35 | 0 | 0 | 0 | 35 |
| TRXM21 | XBT | AddedLiquidity | 1366 | 0 | 1366 | 0 | 82 | 1284 |
| TRXM21 | XBT | RemovedLiquidity | 102 | 97 | 3 | 2 | 22 | 80 |
| TRXU20 | XBT | AddedLiquidity | 363 | 0 | 345 | 18 | 0 | 363 |
| TRXU20 | XBT | RemovedLiquidity | 408 | 402 | 4 | 2 | 0 | 408 |
| TRXU21 | XBT | AddedLiquidity | 1716 | 0 | 1716 | 0 | 59 | 1657 |
| TRXU21 | XBT | RemovedLiquidity | 42 | 41 | 1 | 0 | 5 | 37 |
| TRXUSDT | XBT | AddedLiquidity | 12 | 0 | 12 | 0 | 1 | 11 |
| TRXUSDT | XBT | RemovedLiquidity | 3 | 3 | 0 | 0 | 0 | 3 |
| TRXZ20 | XBT | AddedLiquidity | 392 | 0 | 345 | 47 | 33 | 359 |
| TRXZ20 | XBT | RemovedLiquidity | 106 | 105 | 1 | 0 | 14 | 92 |
| TRXZ21 | XBT | AddedLiquidity | 114 | 0 | 114 | 0 | 0 | 114 |
| TRXZ21 | XBT | RemovedLiquidity | 10 | 10 | 0 | 0 | 0 | 10 |
| UNIUSDT | XBT | AddedLiquidity | 786 | 0 | 786 | 0 | 17 | 769 |
| UNIUSDT | XBT | RemovedLiquidity | 20 | 20 | 0 | 0 | 1 | 19 |
| XBTM21 | XBT | RemovedLiquidity | 19 | 19 | 0 | 0 | 3 | 16 |
| XBTUSD | XBT | AddedLiquidity | 32985 | 11398 | 21427 | 160 | 836 | 32149 |
| XBTUSD | XBT | RemovedLiquidity | 65889 | 65856 | 32 | 1 | 3352 | 62537 |
| XLMUSDT | XBT | AddedLiquidity | 43 | 0 | 43 | 0 | 0 | 43 |
| XLMUSDT | XBT | RemovedLiquidity | 10 | 10 | 0 | 0 | 1 | 9 |
| XRPUSD | XBT | AddedLiquidity | 2488 | 305 | 2183 | 0 | 187 | 2301 |
| XRPUSD | XBT | RemovedLiquidity | 3009 | 3001 | 8 | 0 | 290 | 2719 |
| XTZUSDTZ20 | XBT | AddedLiquidity | 5 | 0 | 5 | 0 | 0 | 5 |
| XTZUSDTZ20 | XBT | RemovedLiquidity | 4 | 4 | 0 | 0 | 0 | 4 |
| YFIUSDTH21 | XBT | AddedLiquidity | 331 | 0 | 331 | 0 | 25 | 306 |
| YFIUSDTH21 | XBT | RemovedLiquidity | 28 | 28 | 0 | 0 | 0 | 28 |
| YFIUSDTZ20 | XBT | AddedLiquidity | 412 | 0 | 412 | 0 | 23 | 389 |
| YFIUSDTZ20 | XBT | RemovedLiquidity | 95 | 92 | 3 | 0 | 9 | 86 |

- `execComm` is the reported signed fee/rebate value and is preserved as authoritative for this milestone. The commission-rate multiplication is diagnostic only and is not used to overwrite `execComm`.

## Settlement

| time | execID | symbol | currency | scale | execCost major | execComm major | realisedPnl major | status |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 2020-12-25T11:59:59.999000Z | 00cde560-bb12-e103-be34-f25d857472aa | YFIUSDTZ20 | XBT | 8 | -0.8622879 | 0 |  | PASS |
| 2020-12-25T11:59:59.999000Z | 7dd33a7a-e74e-4c17-460c-1f938c0fdbd4 | LTCZ20 | XBT | 8 | -1.844376 | 0 |  | PASS |
| 2020-12-25T11:59:59.999000Z | ef4c248c-5878-5c1c-a1c0-cab05d59d932 | ETHZ20 | XBT | 8 | -23.16471 | 0 |  | PASS |
| 2021-03-26T11:59:59.999000Z | b6312ffe-df7c-41c7-570d-0bd97c17e9a5 | ETHH21 | XBT | 8 | -4.5975 | 0 |  | PASS |
| 2021-09-24T11:59:59.999000Z | 7a34520d-79f3-561a-393a-ca34af0ab555 | TRXU21 | XBT | 8 | -2.4057 | 0 |  | PASS |
| 2021-09-24T11:59:59.999000Z | c30a506f-3bce-dade-6497-3446e4df0a89 | LTCU21 | XBT | 8 | -3.536 | 0 |  | PASS |
| 2021-11-02T11:59:59.999000Z | 0d881570-ba4c-bc12-7efb-56ae7220d7eb | AAVEUSDT | XBT | 8 | -2.42429571 | 0 |  | PASS |
| 2021-11-02T11:59:59.999000Z | 68f2bbb3-0259-fdf0-349f-278db210f05c | TRXUSDT | XBT | 8 | -0.856113 | 0 |  | PASS |
| 2021-12-31T11:59:59.999000Z | d2436e87-e8aa-91d5-20eb-de74f0688747 | ETHZ21 | XBT | 8 | -20.03933 | 0 |  | PASS |
| 2022-06-24T11:59:59.999000Z | d6b72f59-ce20-9043-dec6-5fe862e213e5 | ETHM22 | XBT | 8 | -1.1735836 | 0 |  | PASS |
| 2023-03-31T11:59:59.999000Z | 0405f072-04ab-3737-a08a-65d6f84092de | ETHH23 | XBT | 8 | -0.6605151 | 0 |  | PASS |
| 2023-06-30T11:59:59.999000Z | 4ff3b2aa-54d6-6150-1335-13e8ce02220d | ETHM23 | XBT | 8 | 0.4577616 | 0 |  | PASS |
| 2023-09-29T11:59:59.999000Z | bbb5fa5f-0716-d44a-1afe-18272c8a0eb3 | ETHU23 | XBT | 8 | 3.9745288 | 0 |  | PASS |
| 2023-10-19T12:00:00Z | 12b7d977-d654-2ba0-2839-3e25cde3c880 | ORDIUSD | XBT | 8 | -0.00213056 | 0 |  | PASS |
| 2023-12-29T12:00:00Z | d91ede81-0a13-3c9c-99b7-de1d0a3b3078 | ETHZ23 | XBT | 8 | 0.0564366 | 0 |  | PASS |
| 2024-03-29T12:00:00Z | 8abe1bc8-2050-946e-55fe-950b91ce7ece | ETHH24 | XBT | 8 | -0.1012 | 0 |  | PASS |
| 2024-06-28T12:00:10.288000Z | 00000000-0077-1000-0000-00000dd74f41 | ETHM24 | XBT | 8 | -6.8882192 | 0 |  | PASS |
| 2024-09-27T12:00:15.299000Z | 00000000-0077-1000-0000-0000154082dc | ETHU24 | XBT | 8 | -3.96998 | 0 |  | PASS |
| 2024-12-27T12:00:10.289000Z | 00000000-0077-1000-0000-0000232df236 | ETHZ24 | XBT | 8 | -1.6578072 | 0 | -0.06870867 | PASS |

- Settlement rows normalized: `19`; expected `19`.
- Settlement `execCost` is reported as a position-value reference; it is not merged into a cashflow total.

## Canonical execution price reuse

- The builder re-runs the existing M0-02B-0.2 Decimal price reconciler from raw normalized events; it does not trust an existing generated CSV as input.
- Configured historical Trade rows: `7234`.
- EXACT: `5809`; RECOVERED: `1425`; UNRESOLVED: `0`.
- Canonical execCost reproduction failures: `0`.
- Non-audited current/snapshot Trade rows keep raw `lastPx` and are not promoted to historical canonical price in this milestone.

## 异常、阻塞与后续边界

- Blocking findings: `[]`.
- Warnings: `["172089 rows use the documented commission-currency fallback chain", "150300 Trade rows differ from the commission-rate diagnostic; reported execComm is retained", "commission-rate diagnostic is informational and does not create a wallet cashflow", "realisedPnl remains independent; overlap with future wallet/PnL reconciliation is not resolved in M0-02B-1A"]`.
- Full anomaly rows are capped at 200 in `execution_value_anomalies.csv`; the complete valuation and component ledgers remain ignored Parquet outputs.
- This milestone does not calculate average entry price, realised strategy PnL, unrealised PnL, net worth, leverage, margin, signals, or trades.

## 输出文件

- Ignored: `quant/outputs/execution_valuation.parquet`, `quant/outputs/execution_components.parquet`.
- Committed summaries: `execution_valuation.json`, `execution_valuation.csv`, `execution_component_summary.csv`, `currency_scale_coverage.csv`, `funding_summary.csv`, `trade_fee_summary.csv`, `settlement_value_summary.csv`, `execution_value_anomalies.csv`.
- Protected raw-file hashes were captured before and after generation; any changed raw file blocks the run.
