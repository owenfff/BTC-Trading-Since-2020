# M0-01 / M0-02A.1 数据集审计与合约张数回放

本目录固定数据版本并完成数据体检；M0-02A.1 在此基础上只按 execution 重放衍生品合约张数，并将 Spot Trade 单独保留为原始余额方向。不训练模型、不接交易所 API、不修改原始 CSV/JSON、不计算 PnL、净值、杠杆或保证金，也不自动交易。

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

## M0-02A.1 合约张数回放

在仓库根目录、`quant/m0-02a-position-replay` 分支执行：

```bash
python quant/scripts/rebuild_positions.py
```

脚本按 `transactTime`、`timestamp`、原始行号和 `execID` 稳定排序，使用唯一 `orderID` 维表做不扩行的关联，依据 instrument `typ` 区分衍生品、Spot、参考指数和未知类型，保留全部 Trade、Funding、Settlement execution 行，并生成：

- `quant/outputs/normalized_execution_events.parquet`
- `quant/outputs/position_events.parquet`
- `quant/outputs/terminal_positions.csv`
- `quant/outputs/terminal_derivative_positions.csv`
- `quant/reports/settlement_events.csv`
- `quant/reports/spot_execution_summary.csv`
- `quant/reports/instrument_temporal_audit.csv`
- `quant/reports/instrument_temporal_audit.md`
- `quant/reports/position_replay.md`
- `quant/reports/position_replay.json`

历史提前结算证据保存在 `quant/config/historical_settlement_evidence.json`，运行时不联网。Settlement 最终状态必须通过 `position_before + signed_contract_qty == 0` 的闭合校验；当前 instrument 快照早于历史成交的 symbol 会进入 temporal audit，并保持 M0-02B 阻塞。

原始数据文件始终只读；脚本会在输出前后重新计算受保护文件的 SHA256，并对 XBTUSD 与位置快照进行终态对账。

## M0-02B-1A Execution 价值、费用与币种单位标准化

本阶段从原始 Execution CSV 重新构建一条衍生品 Execution 价值表和一条长表组件账本。使用 `api-v1-wallet-assets.csv` 的冻结 `scale` 将整数最小单位转换为 Decimal 主单位，并保留 `execCost`、`execComm`、`realisedPnl` 的独立语义和原始符号。不进行跨币种相加，不计算平均成本、策略 PnL、未实现 PnL、净值、杠杆或保证金。

在仓库根目录运行：

```bash
python quant/scripts/build_execution_valuation.py
```

Windows 也可以显式使用：

```powershell
py -3.11 quant/scripts/build_execution_valuation.py
```

构建会直接读取原始 CSV、重新执行历史规格匹配和 M0-02B-0.2 canonical price reconciliation，生成两个被 `.gitignore` 保护的 Parquet：

- `quant/outputs/execution_valuation.parquet`
- `quant/outputs/execution_components.parquet`

Git 中只保留小型汇总报告：

- `quant/reports/execution_valuation.md`
- `quant/reports/execution_valuation.json`
- `quant/reports/execution_valuation.csv`
- `quant/reports/execution_component_summary.csv`
- `quant/reports/currency_scale_coverage.csv`
- `quant/reports/funding_summary.csv`
- `quant/reports/trade_fee_summary.csv`
- `quant/reports/settlement_value_summary.csv`
- `quant/reports/execution_value_anomalies.csv`

运行测试：

```bash
pytest quant/tests -v
```

## 审计范围

- 校验 `manifest.json` 声明的文件、大小、SHA256、行数、列名和时间范围。
- 审计主要订单、成交和钱包历史表的行数、字段、缺失值、重复行、时间解析/顺序、主键质量和枚举值。
- 检查订单—成交 `orderID` 覆盖率，以及重复 `orderID` 是精确重复还是更像订单生命周期记录。
- 报告价格、数量、成交价缺失、PnL/费用/成本极端值和钱包余额跳变候选。
- 使用 instrument 和 wallet-assets 作为单位解释上下文；不会把所有数字默认当成 BTC。

所有异常只报告、不自动修复。原始数据文件应保持不变。
