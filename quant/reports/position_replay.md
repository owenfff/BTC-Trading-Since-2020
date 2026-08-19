# M0-02A 合约张数仓位回放报告

分析 commit：`e62b1c298d1802ff6406827c08787ef3c64630ae`；分支：`quant/m0-02a-position-replay`
数据源 commit：`f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6`

## 执行摘要

- 状态：**BLOCKED**
- 标准化 execution：`173,434` 行；Join 前后：`173,434` → `173,434`。
- XBTUSD 终态对账：**PASS**，重建值 `-998000`，快照值 `-998000`。
- 本阶段只重建合约张数；不计算 PnL、净值、杠杆、保证金或行情指标。

## 原始数据保护

保护文件 SHA256 未改变：**True**。

| 指标 | 值 |
| --- | --- |
| 变化文件 | 无 |

## Execution 标准化与排序

`event_time` 优先使用 `transactTime`，缺失时回退 `timestamp`；排序键为 event_time、timestamp、source_row_number、execID。原始行号保留为稳定锚点。

| execType | 数量 |
| --- | --- |
| Funding | 12905 |
| Settlement | 19 |
| Trade | 160510 |

| normalization_status | 数量 |
| --- | --- |
| OK | 173391 |
| OK_WITHOUT_ORDER_ID | 32 |
| OK_WITH_UNMATCHED_ORDER | 10 |
| UNRESOLVED | 1 |

## 订单维表与关联

订单输入 `43,251` 行；派生唯一 `orderID` `43,216`；派生表删除完全重复行 `35`。Join 使用唯一字典映射，不会扩展 execution 行。

| 指标 | 值 |
| --- | --- |
| Join 前 execution 行数 | 173434 |
| Join 后 execution 行数 | 173434 |
| Join 行数断言 | True |
| 非 identical orderID 版本组 | 0 |

### orderID 缺失与关联状态

| execType | orderID 缺失 | UNMATCHED | NO_ORDER_ID | NOT_APPLICABLE |
| --- | --- | --- | --- | --- |
| Funding | 12905 | 0 | 0 | 12905 |
| Settlement | 19 | 0 | 0 | 19 |
| Trade | 32 | 10 | 32 | 0 |

无法匹配的 execution 示例：

共 `1` 个唯一未匹配 orderID，对应 `10` 个示例行（报告最多展示 100 行）：

`['18a1e0fe-da52-40eb-8e51-e2acbded0578']`

```json
[
  {
    "source_row_number": 157810,
    "event_time": "2024-10-13T12:45:18.728000Z",
    "execID": "00000000-006d-1000-0000-000c99a628c5",
    "execType": "Trade",
    "symbol": "XBTUSD",
    "side": "Sell",
    "lastQty": 1100,
    "orderID": "18a1e0fe-da52-40eb-8e51-e2acbded0578",
    "order_join_status": "UNMATCHED"
  },
  {
    "source_row_number": 157811,
    "event_time": "2024-10-13T12:45:18.728000Z",
    "execID": "00000000-006d-1000-0000-000c99a628c8",
    "execType": "Trade",
    "symbol": "XBTUSD",
    "side": "Sell",
    "lastQty": 400,
    "orderID": "18a1e0fe-da52-40eb-8e51-e2acbded0578",
    "order_join_status": "UNMATCHED"
  },
  {
    "source_row_number": 157812,
    "event_time": "2024-10-13T12:45:18.728000Z",
    "execID": "00000000-006d-1000-0000-000c99a628cb",
    "execType": "Trade",
    "symbol": "XBTUSD",
    "side": "Sell",
    "lastQty": 100,
    "orderID": "18a1e0fe-da52-40eb-8e51-e2acbded0578",
    "order_join_status": "UNMATCHED"
  },
  {
    "source_row_number": 157813,
    "event_time": "2024-10-13T12:45:18.728000Z",
    "execID": "00000000-006d-1000-0000-000c99a628ce",
    "execType": "Trade",
    "symbol": "XBTUSD",
    "side": "Sell",
    "lastQty": 16400,
    "orderID": "18a1e0fe-da52-40eb-8e51-e2acbded0578",
    "order_join_status": "UNMATCHED"
  },
  {
    "source_row_number": 157814,
    "event_time": "2024-10-13T12:45:18.728000Z",
    "execID": "00000000-006d-1000-0000-000c99a628d1",
    "execType": "Trade",
    "symbol": "XBTUSD",
    "side": "Sell",
    "lastQty": 27900,
    "orderID": "18a1e0fe-da52-40eb-8e51-e2acbded0578",
    "order_join_status": "UNMATCHED"
  },
  {
    "source_row_number": 157815,
    "event_time": "2024-10-13T12:45:18.728000Z",
    "execID": "00000000-006d-1000-0000-000c99a628d4",
    "execType": "Trade",
    "symbol": "XBTUSD",
    "side": "Sell",
    "lastQty": 16400,
    "orderID": "18a1e0fe-da52-40eb-8e51-e2acbded0578",
    "order_join_status": "UNMATCHED"
  },
  {
    "source_row_number": 157816,
    "event_time": "2024-10-13T12:45:18.728000Z",
    "execID": "00000000-006d-1000-0000-000c99a628d7",
    "execType": "Trade",
    "symbol": "XBTUSD",
    "side": "Sell",
    "lastQty": 4400,
    "orderID": "18a1e0fe-da52-40eb-8e51-e2acbded0578",
    "order_join_status": "UNMATCHED"
  },
  {
    "source_row_number": 157817,
    "event_time": "2024-10-13T12:45:18.728000Z",
    "execID": "00000000-006d-1000-0000-000c99a628da",
    "execType": "Trade",
    "symbol": "XBTUSD",
    "side": "Sell",
    "lastQty": 28800,
    "orderID": "18a1e0fe-da52-40eb-8e51-e2acbded0578",
    "order_join_status": "UNMATCHED"
  },
  {
    "source_row_number": 157818,
    "event_time": "2024-10-13T12:45:18.728000Z",
    "execID": "00000000-006d-1000-0000-000c99a628dd",
    "execType": "Trade",
    "symbol": "XBTUSD",
    "side": "Sell",
    "lastQty": 22200,
    "orderID": "18a1e0fe-da52-40eb-8e51-e2acbded0578",
    "order_join_status": "UNMATCHED"
  },
  {
    "source_row_number": 157819,
    "event_time": "2024-10-13T12:45:18.728000Z",
    "execID": "00000000-006d-1000-0000-000c99a628e0",
    "execType": "Trade",
    "symbol": "XBTUSD",
    "side": "Sell",
    "lastQty": 2300,
    "orderID": "18a1e0fe-da52-40eb-8e51-e2acbded0578",
    "order_join_status": "UNMATCHED"
  }
]
```

## Settlement 处理

共 `19` 条；状态分布：`{'APPLIED_POSITION_DELTA': 18, 'UNRESOLVED': 1}`。依据：BitMEX 说明到期时未平仓合约自动关闭；本阶段只应用合约数量变化，不计算结算 PnL。

| execID | symbol | side | lastQty | settlement_status | reason |
| --- | --- | --- | --- | --- | --- |
| 00cde560-bb12-e103-be34-f25d857472aa | YFIUSDTZ20 | Sell | 355 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| 7dd33a7a-e74e-4c17-460c-1f938c0fdbd4 | LTCZ20 | Sell | 372 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| ef4c248c-5878-5c1c-a1c0-cab05d59d932 | ETHZ20 | Sell | 901 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| b6312ffe-df7c-41c7-570d-0bd97c17e9a5 | ETHH21 | Sell | 150 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| 7a34520d-79f3-561a-393a-ca34af0ab555 | TRXU21 | Sell | 1100000 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| c30a506f-3bce-dade-6497-3446e4df0a89 | LTCU21 | Sell | 1000 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| 0d881570-ba4c-bc12-7efb-56ae7220d7eb | AAVEUSDT | Sell | 7439 | UNRESOLVED | Instrument metadata does not confirm an expiring contract. |
| 68f2bbb3-0259-fdf0-349f-278db210f05c | TRXUSDT | Sell | 8332 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| d2436e87-e8aa-91d5-20eb-de74f0688747 | ETHZ21 | Sell | 25450000000 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| d6b72f59-ce20-9043-dec6-5fe862e213e5 | ETHM22 | Sell | 2086000 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| 0405f072-04ab-3737-a08a-65d6f84092de | ETHH23 | Sell | 1029000 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| 4ff3b2aa-54d6-6150-1335-13e8ce02220d | ETHM23 | Buy | 747000 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| bbb5fa5f-0716-d44a-1afe-18272c8a0eb3 | ETHU23 | Buy | 6424000 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| 12b7d977-d654-2ba0-2839-3e25cde3c880 | ORDIUSD | Sell | 64 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| d91ede81-0a13-3c9c-99b7-de1d0a3b3078 | ETHZ23 | Buy | 102000 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| 8abe1bc8-2050-946e-55fe-950b91ce7ece | ETHH24 | Sell | 200000 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| 00000000-0077-1000-0000-00000dd74f41 | ETHM24 | Sell | 12296000 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| 00000000-0077-1000-0000-0000154082dc | ETHU24 | Sell | 9800000 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |
| 00000000-0077-1000-0000-0000232df236 | ETHZ24 | Sell | 4699000 | APPLIED_POSITION_DELTA | Expiring instrument metadata and positive side/lastQty support a contract-quantity close. |

## 仓位回放

| action | 数量 |
| --- | --- |
| ADD_LONG | 50988 |
| ADD_SHORT | 28057 |
| CLOSE_LONG | 885 |
| CLOSE_SHORT | 344 |
| FLIP_LONG_TO_SHORT | 95 |
| FLIP_SHORT_TO_LONG | 83 |
| NO_POSITION_CHANGE | 12906 |
| OPEN_LONG | 899 |
| OPEN_SHORT | 334 |
| REDUCE_LONG | 53598 |
| REDUCE_SHORT | 25245 |

### 非零终态仓位

| symbol | reconstructed_position | trade_events | settlement_events | final_status |
| --- | --- | --- | --- | --- |
| AAVEUSDT | 7439 | 402 | 1 | WARNING |
| BMEX_USDT | -7346000000 | 201 | 0 | PASS |
| XBTUSD | -998000 | 98874 | 0 | PASS |
| XBT_USDT | 14380000 | 7 | 0 | PASS |

### XBTUSD 终态快照对账

| 字段 | 值 |
| --- | --- |
| symbol | XBTUSD |
| snapshot_timestamp | 2026-07-19T12:35:00.504Z |
| reconstructed_current_qty | -998000 |
| snapshot_current_qty | -998000 |
| difference | 0 |
| last_event_source_row_number | 173435 |
| last_event_execID | 00000000-0077-1000-0000-000083b7b0d5 |
| reconciliation_status | PASS |

## 未解决异常与 M0-02B 判断

阻塞项：

- 1 Settlement rows remain UNRESOLVED.

警告：

- 35 exact duplicate order rows were removed only in the derived order dimension.
- 10 execution rows have an orderID that is not present in order_dimension; executions were retained.
- 32 Trade rows have no orderID and were replayed from execution fields.
- This is contract-quantity replay only; no average entry price, PnL, equity, leverage, margin, market data, or trading API was used.

M0-02B 仍应另行实现单位、合约类型、平均开仓价和 PnL 规则；本报告不把张数回放误当成财务对账。

参考：[Get Executions](https://docs.bitmex.com/api-explorer/get-execution)、[BitMEX Settlement 说明](https://support.bitmex.com/hc/en-gb/articles/18588991131933-What-Is-Settlement-and-How-Is-Settlement-Price-Calculated-on-BitMEX)。
