# M0-02A.1 合约张数仓位回放报告

分析 commit：`1e62097400fc72e4c5ba9715feff3a9818c26a6b`；分支：`quant/m0-02a-position-replay`
数据源 commit：`f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6`

## 状态

- `position_replay_status`：**READY_WITH_WARNINGS**
- `m0_02b_readiness`：**BLOCKED_BY_HISTORICAL_INSTRUMENT_METADATA**
- 标准化 execution：`173,434` 行；Join 前后：`173,434` → `173,434`。
- XBTUSD 对账：**PASS**，重建 `-998000`，快照 `-998000`。
- 本阶段只重建衍生品合约张数；Spot 只保留原始成交余额方向，不计算完整资产单位；不计算 PnL、净值、杠杆或保证金。

## 原始数据保护

保护文件 SHA256 未改变：**True**；变化文件：`无`。

## Execution 与 instrument 分类

`event_time` 优先使用 `transactTime`，缺失时回退 `timestamp`；随后按 timestamp、原始行号和 execID 稳定排序。BitMEX 的 instrument `typ` 分类依据官方 API 文档；不通过 symbol 下划线推断 Spot。

| execType | count |
| --- | --- |
| Funding | 12905 |
| Settlement | 19 |
| Trade | 160510 |

| instrument_class | execution_count |
| --- | --- |
| DERIVATIVE | 173226 |
| SPOT | 208 |

| Trade instrument_class | trade_count |
| --- | --- |
| DERIVATIVE | 160302 |
| SPOT | 208 |

| instrument_typ | execution_count |
| --- | --- |
| FFCCSX | 18923 |
| FFWCSX | 154303 |
| IFXXXP | 208 |

## 订单维表与关联

订单输入 `43,251` 行；一行一个 `orderID` 的派生维表 `43,216` 个；完全重复行 `35`；非 identical 版本组 `0`。

| execType | missing orderID | UNMATCHED | NO_ORDER_ID | NOT_APPLICABLE |
| --- | --- | --- | --- | --- |
| Funding | 12905 | 0 | 0 | 12905 |
| Settlement | 19 | 0 | 0 | 19 |
| Trade | 32 | 10 | 32 | 0 |

唯一未匹配 orderID：`['18a1e0fe-da52-40eb-8e51-e2acbded0578']`；具体 execution 示例：

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

## Spot Trade 隔离

Spot Trade 仍在 normalized execution 中，但 `signed_contract_qty=0`，不进入衍生品仓位累计；摘要单独输出。

| symbol | typ | trade_count | buy_raw_qty | sell_raw_qty | net_base_qty_raw |
| --- | --- | --- | --- | --- | --- |
| BMEX_USDT | IFXXXP | 201 | 40566000000 | 47912000000 | -7346000000 |
| XBT_USDT | IFXXXP | 7 | 14380000 | 0 | 14380000 |

## Settlement 处理

共 `19` 条；状态分布：`{'APPLIED_POSITION_DELTA': 19}`。每条 Settlement 都经过 position_before、side、lastQty、signed_qty、position_after 和完整归零校验。AAVEUSDT 使用配置化官方提前结算证据，仍必须满足仓位闭合不变量。

| execID | symbol | side | lastQty | position_before | signed_qty | position_after | settlement_status | resolution_method |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 00cde560-bb12-e103-be34-f25d857472aa | YFIUSDTZ20 | Sell | 355 | 355 | -355 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| 7dd33a7a-e74e-4c17-460c-1f938c0fdbd4 | LTCZ20 | Sell | 372 | 372 | -372 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| ef4c248c-5878-5c1c-a1c0-cab05d59d932 | ETHZ20 | Sell | 901 | 901 | -901 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| b6312ffe-df7c-41c7-570d-0bd97c17e9a5 | ETHH21 | Sell | 150 | 150 | -150 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| 7a34520d-79f3-561a-393a-ca34af0ab555 | TRXU21 | Sell | 1100000 | 1100000 | -1100000 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| c30a506f-3bce-dade-6497-3446e4df0a89 | LTCU21 | Sell | 1000 | 1000 | -1000 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| 0d881570-ba4c-bc12-7efb-56ae7220d7eb | AAVEUSDT | Sell | 7439 | 7439 | -7439 | 0 | APPLIED_POSITION_DELTA | OFFICIAL_EARLY_SETTLEMENT_AND_POSITION_CLOSE_INVARIANT |
| 68f2bbb3-0259-fdf0-349f-278db210f05c | TRXUSDT | Sell | 8332 | 8332 | -8332 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| d2436e87-e8aa-91d5-20eb-de74f0688747 | ETHZ21 | Sell | 25450000000 | 25450000000 | -25450000000 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| d6b72f59-ce20-9043-dec6-5fe862e213e5 | ETHM22 | Sell | 2086000 | 2086000 | -2086000 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| 0405f072-04ab-3737-a08a-65d6f84092de | ETHH23 | Sell | 1029000 | 1029000 | -1029000 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| 4ff3b2aa-54d6-6150-1335-13e8ce02220d | ETHM23 | Buy | 747000 | -747000 | 747000 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| bbb5fa5f-0716-d44a-1afe-18272c8a0eb3 | ETHU23 | Buy | 6424000 | -6424000 | 6424000 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| 12b7d977-d654-2ba0-2839-3e25cde3c880 | ORDIUSD | Sell | 64 | 64 | -64 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| d91ede81-0a13-3c9c-99b7-de1d0a3b3078 | ETHZ23 | Buy | 102000 | -102000 | 102000 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| 8abe1bc8-2050-946e-55fe-950b91ce7ece | ETHH24 | Sell | 200000 | 200000 | -200000 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| 00000000-0077-1000-0000-00000dd74f41 | ETHM24 | Sell | 12296000 | 12296000 | -12296000 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| 00000000-0077-1000-0000-0000154082dc | ETHU24 | Sell | 9800000 | 9800000 | -9800000 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |
| 00000000-0077-1000-0000-0000232df236 | ETHZ24 | Sell | 4699000 | 4699000 | -4699000 | 0 | APPLIED_POSITION_DELTA | INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT |

## 衍生品仓位终态

| symbol | typ | reconstructed_position | trade_events | settlement_events | final_status |
| --- | --- | --- | --- | --- | --- |
| XBTUSD | FFWCSX | -998000 | 98874 | 0 | PASS |

| field | value |
| --- | --- |
| symbol | XBTUSD |
| snapshot_timestamp | 2026-07-19T12:35:00.504Z |
| reconstructed_current_qty | -998000 |
| snapshot_current_qty | -998000 |
| difference | 0 |
| last_event_source_row_number | 173435 |
| last_event_execID | 00000000-0077-1000-0000-000083b7b0d5 |
| reconciliation_status | PASS |

## Instrument Temporal Audit

需要历史规格的 symbol：`['AAVEUSDT', 'ADAUSDT', 'BNBUSDT', 'DOGEUSDT', 'DOTUSDT', 'LINKUSDT', 'LUNAUSD', 'ORDIUSD', 'TRXUSDT', 'UNIUSDT', 'XLMUSDT']`。这些历史元数据风险不阻塞已完成的张数回放，但使 M0-02B 保持 `BLOCKED_BY_HISTORICAL_INSTRUMENT_METADATA`。

## 未解决异常

没有达到仓位回放阻塞阈值的异常。

警告：

- 35 exact duplicate order rows were removed only in the derived order dimension.
- 10 execution rows have an orderID that is not present in order_dimension; executions were retained.
- 32 Trade rows have no orderID and were replayed from execution fields.
- 11 symbols have execution before current metadata listing; M0-02B remains blocked until historical specs are versioned.
- 208 Spot Trade events were retained as SPOT_BALANCE_DELTA and excluded from derivative positions.
- This is contract-quantity replay only; no average entry price, PnL, equity, leverage, margin, market data, or trading API was used.

M0-02B 仍需建立按历史时间版本化的合约规格表，再处理 multiplier、结算币种、平均成本和 PnL。

参考：[Get Instruments | BitMEX API](https://docs.bitmex.com/api-explorer/get-instruments)、[BitMEX 提前结算公告](https://www.bitmex.com/blog/axs-eos-link-sol-aave-matic-srm-sushi-trx-uni-vet-and-xlm-quanto-perpetuals-new-listing-and-early-settlement-of-contracts-due-to-naming-conventions)。
