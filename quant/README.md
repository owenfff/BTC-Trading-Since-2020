# M0-01 / M0-02A 数据集审计与合约张数回放

本目录固定数据版本并完成数据体检；M0-02A 在此基础上只按 execution 重放合约张数。不训练模型、不接交易所 API、不修改原始 CSV/JSON、不计算 PnL、净值、杠杆或保证金，也不自动交易。

## 运行

在仓库根目录执行：

```bash
python quant/scripts/audit_dataset.py
```

脚本会以批量/流式方式读取 CSV，并生成：

- `quant/reports/data_audit.md`
- `quant/reports/data_audit.json`

运行测试：

```bash
pytest quant/tests -v
```

## M0-02A 合约张数回放

在仓库根目录、`quant/m0-02a-position-replay` 分支执行：

```bash
python quant/scripts/rebuild_positions.py
```

脚本按 `transactTime`、`timestamp`、原始行号和 `execID` 稳定排序，使用唯一 `orderID` 维表做不扩行的关联，保留全部 Trade、Funding、Settlement execution 行，并生成：

- `quant/outputs/normalized_execution_events.parquet`
- `quant/outputs/position_events.parquet`
- `quant/outputs/terminal_positions.csv`
- `quant/reports/settlement_events.csv`
- `quant/reports/position_replay.md`
- `quant/reports/position_replay.json`

原始数据文件始终只读；脚本会在输出前后重新计算受保护文件的 SHA256，并对 XBTUSD 与位置快照进行终态对账。

## 审计范围

- 校验 `manifest.json` 声明的文件、大小、SHA256、行数、列名和时间范围。
- 审计主要订单、成交和钱包历史表的行数、字段、缺失值、重复行、时间解析/顺序、主键质量和枚举值。
- 检查订单—成交 `orderID` 覆盖率，以及重复 `orderID` 是精确重复还是更像订单生命周期记录。
- 报告价格、数量、成交价缺失、PnL/费用/成本极端值和钱包余额跳变候选。
- 使用 instrument 和 wallet-assets 作为单位解释上下文；不会把所有数字默认当成 BTC。

所有异常只报告、不自动修复。原始数据文件应保持不变。
