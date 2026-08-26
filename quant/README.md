# M0-01 / M0-02A.1 数据集审计与合约张数回放

本目录固定数据版本并完成数据体检；M0-02A.1 在此基础上只按 execution 重放衍生品合约张数，并将 Spot Trade 单独保留为原始余额方向。不训练模型、不接交易所 API、不修改原始 CSV/JSON、不计算 PnL、净值、杠杆或保证金，也不自动交易。

## M15 Hyperliquid 公开回放与跨交易所行为审计

本阶段把 Hyperliquid 网站的公开快照作为固定、可校验的外部教师来源；原始文件保存于被忽略的 `quant/data/external/`，不与 BitMEX 原始 CSV 混写。只有经过来源 SHA256 校验、因果指标检查和严格自主回放的归一化行才进入跨交易所研究数据集。交易所和结算单位始终单独保留，Spot 不进入衍生品仓位语义。

从仓库根目录运行：

```bash
python quant/scripts/import_hyperliquid_public.py --cutoff 2026-07-18T21:17:31.514Z
python quant/scripts/build_cross_venue_model_dataset.py --contract v2
python quant/scripts/build_cross_venue_model_dataset.py --contract v3
python quant/scripts/audit_hyperliquid_public_source.py \
  --data-dir quant/data/external/hyperliquid/paul/ace13c7a675a20d4932b430508a750d7ad7867e9 \
  --manifest quant/data/external/hyperliquid/paul/ace13c7a675a20d4932b430508a750d7ad7867e9/source-manifest.json \
  --report-md quant/reports/hyperliquid_public_source_audit.md \
  --report-json quant/reports/hyperliquid_public_source_audit.json
python quant/scripts/audit_cross_venue_strategy.py
```

`audit_cross_venue_strategy.py` 同时输出 `CONDITIONAL_BEHAVIOR` 与 `STRICT_AUTONOMOUS_REPLAY`，后者从零仓位开始，只用决策时已经关闭的 K 线，在下一根 K 线开盘模拟执行，并计入费用、资金费和滑点。当前候选若未通过自主收益门槛会保持 `DEMO_CONTINUE_LIVE_BLOCKED`，不会切换部署模型或提交订单。

官方公开 API 的有限近期刷新使用：

```bash
python quant/scripts/refresh_hyperliquid_public.py
```

该命令只调用 Hyperliquid `info` 公共接口，不读取凭证；API 的历史/响应窗口有限，失败时明确阻断，不用它冒充完整历史。`build_hyperliquid_replay_dashboard.py` 生成被忽略的 `quant/outputs/replay_dashboard_hyperliquid_btc.json`，本地前端的“回放与诊断”可在 BitMEX / Hyperliquid 间切换，并显示 RSI14、MACD 柱、布林 `%B` 和指标覆盖状态。

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

## M0-02B-1B-0 仓位成本与平均入场价回放

本阶段在已验证的数量回放和 Execution valuation 之上，按稳定的 `event_time`、`timestamp`、原始行号和 `execID` 顺序，逐 symbol 重放 `current_qty`、`currentCost`、平均成本释放、反手成本拆分、独立 AEP 和 position cycle。`PASS` 与 `WARNING` valuation 都具备 accounting eligibility；只有 `BLOCKED` 行阻塞本阶段。

官方口径相关的 AEP 使用独立状态：Quanto/Linear 使用 Decimal 数量加权，Inverse 使用 `lot_size / canonical_execution_price` 的八位 satoshi basis，并固定长仓 floor、短仓 ROUND_HALF_UP 的 policy。`realisedPnl`、`execComm` 和 Funding 不会反向驱动仓位状态或被自动合并成净现金流。

在仓库根目录运行：

```bash
python quant/scripts/rebuild_position_accounting.py
```

Windows 也可以使用：

```powershell
py -3.11 quant/scripts/rebuild_position_accounting.py
```

脚本从原始 CSV、历史规格和 Python 模块重新构建输入，不依赖 ignored Parquet。逐 Execution 输出写入被 `.gitignore` 保护的：

- `quant/outputs/position_accounting_events.parquet`

Git 中只保留终态、动作、舍入审计、snapshot 对账、reported `realisedPnl` 诊断和最多 200 条异常样例等小型摘要。任何原始 CSV/JSON SHA256 变化、成本守恒失败、Settlement 残余成本、终态锚点失败或舍入 policy 歧义都会阻塞本阶段。

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

## M0-02B-1B-0.1 accounting semantics audit

本补丁在不改动原始 CSV/JSON、也不接交易所的前提下，补齐四类会计语义诊断：

- `reportedPnl + execComm` 的 gross candidate 分解；`brokerExecComm` 非零时单独标记 unresolved，不会盲加。
- `historical_instrument_terms.json` 固化 XBTUSD、XBTM21、XBTU21 在 2021-06-08 04:30 UTC 的 lot size 1→100 边界；其它合约明确标记为冻结 instrument snapshot fallback。
- 同一 symbol / transactTime / timestamp / orderID 下，优先审计 cumQty 链；跨 orderID 的同时间并列不使用 UUID 推断。
- 保留现有 `PROPORTIONAL_INDEPENDENT_EVENT_ROUNDING`，并诊断 cumulative rounded delta、integer quotient/remainder carry 和 average-basis release；不逐 Execution 选择模型。

运行：

```bash
py -3.11 quant/scripts/rebuild_position_accounting.py
pytest quant/tests -v
```

新增的小型报告为 `instrument_terms_temporal_audit.csv`、`execution_tie_order_audit.csv`、`position_cost_model_audit.csv`、`aep_model_audit.csv` 和 `xbtusd_current_cycle_summary.csv`。逐 Execution Parquet 仍只放在 `quant/outputs/` 并由 `.gitignore` 保护。

## 审计范围

- 校验 `manifest.json` 声明的文件、大小、SHA256、行数、列名和时间范围。
- 审计主要订单、成交和钱包历史表的行数、字段、缺失值、重复行、时间解析/顺序、主键质量和枚举值。
- 检查订单—成交 `orderID` 覆盖率，以及重复 `orderID` 是精确重复还是更像订单生命周期记录。
- 报告价格、数量、成交价缺失、PnL/费用/成本极端值和钱包余额跳变候选。
- 使用 instrument 和 wallet-assets 作为单位解释上下文；不会把所有数字默认当成 BTC。

所有异常只报告、不自动修复。原始数据文件应保持不变。

## M2 behavioral episodes and trade cycles

`python quant/scripts/build_behavior_dataset.py` 在冻结的 Execution、position replay、accounting foundation 和 wallet reconciliation 之上构建分层行为数据：

- `trade_actions`：每条衍生品 Trade 的 position action；
- `execution_batches`：同一 order 的相邻 fills，默认 300 秒 gap 边界；
- `order_episodes`：每个 symbol/orderID 生命周期，不把 partial fills 当作独立决策；
- `decision_episodes`：订单决策加 XBTUSD 日级 `HOLD_*` / `NO_TRADE` 合成样本；
- `trade_cycles`：从开仓到完整平仓/反手/数据终点的 position cycle。

每条 action、decision 和 cycle 都保留 `ordering_confidence`、`action_confidence`、`accounting_confidence`、`price_confidence`、`wallet_confidence` 和 `overall_confidence`。XBTUSD 是 BTC-first 教师范围，策略保真度固定为 `BEHAVIORAL_APPROXIMATION`；钱包只做 aggregate-only evidence，不伪造逐笔 join。

Parquet 大文件只写入 `quant/outputs/` 并被 `.gitignore` 保护；若运行时没有 `quant/requirements.txt` 中的 Parquet engine，脚本会生成明确标记的 ignored CSV fallback，并在 `quant/reports/trader_behavior_profile.md` 中记录。
