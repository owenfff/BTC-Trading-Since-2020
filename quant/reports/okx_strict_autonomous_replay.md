# OKX Strict Autonomous Replay

- status: **PASS_WITH_WARNINGS**
- strategy: `behavioral-distillation-v3-cross-asset-indicators`
- track: `STRICT_AUTONOMOUS_REPLAY`
- fidelity: `BEHAVIORAL_APPROXIMATION`
- market rows: `8999`; warmup rows: `72`; signal rows: `8927`
- period: `2025-08-18T05:00:00.001000Z` → `2026-08-28T03:00:00.001000Z`

## 结果

- 净结果：`26.833634%`
- 最终权益（初始=1）：`1.26833634`
- 最大回撤：`20.665695%`
- Profit Factor：`1.0201536516118839`
- 交易次数：`1`；换手暴露：`1.000000`
- 原始动作与目标仓位推导动作不一致：`8927`；目标暴露饱和（±1）行数：`8927`
- 手续费：`0.00050000`；滑点：`0.00010000`；资金费净支付：`-0.01116515`

## 基线

- 不交易：净结果 `0.000000%`
- 买入并持有：净结果 `-27.090758%`

## 时间因果与覆盖

- 因果时间违规：`0`
- 指标缺失计数：`{"feature_atr_14bar": 14, "feature_bollinger_percent_b_20": 19, "feature_macd_histogram": 33, "feature_rsi_14": 14, "feature_volume_percentile_72bar": 71}`
- 上下文覆盖：`{"COMPLETE": 1899, "MARK_INDEX_MISSING": 7100}`
- 回放只使用已确认关闭的 OKX K 线；成交执行价取下一根 K 线开盘价。
- 本报告没有读取 BitMEX 未来仓位、未来成交或账户结果。

## 结论

- 模型升级：**NOT_PROMOTED_CURRENT_V3_MARKET_CONTEXT_ONLY**
- 模型可用性：**NOT_READY_FOR_DEMO**；原因：动作分类头与目标暴露推导不一致；目标暴露长期饱和在边界；有效仓位调整次数过少，无法证明稳定捕捉信号
- 本次只是用 OKX 公共行情验证当前冻结 v3 的可执行性，不代表已经训练出新的 v4/v5，也不代表未来盈利。
- OKX 公共行情是市场环境输入；BitMEX 原始成交仍是行为教师来源，二者没有被混成一份账户记录。

## 三段时间窗口

| window | start | end | rows | net return | max drawdown |
|---|---|---|---:|---:|---:|
| WF1 | 2025-08-18T05:00:00.001000Z | 2025-12-21T03:00:00.001000Z | 2999 | 22.675951% | 15.534057% |
| WF2 | 2025-12-21T04:00:00.001000Z | 2026-04-25T02:00:00.001000Z | 2999 | 7.267290% | 16.599784% |
| WF3 | 2026-04-25T03:00:00.001000Z | 2026-08-28T03:00:00.001000Z | 3001 | -3.431990% | 20.665531% |
