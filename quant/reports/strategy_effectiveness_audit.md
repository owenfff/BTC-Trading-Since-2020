# Strategy Effectiveness Audit

- 审计状态：**DEMO_CONTINUE_LIVE_BLOCKED**
- 策略标记：`BEHAVIORAL_APPROXIMATION`
- 历史品种：`66`；可建模品种：`53`；可建模行：`10630`
- 泄漏审计：**PASS**；受保护原始输入哈希：**PASS**
- 本次没有连接私有 API、没有提交订单、没有使用真实资金；Demo 不会因为本报告自动切换模型或自动下单。

## 先看结论

该审计同时检查行为复现和净成本后表现。回放收益是逐品种等权的标准化暴露收益代理，不是钱包、账户或真实交易收益。任何一个时间外窗口无数据、泄漏、翻转召回为零或净收益门槛失败，都会阻断 Live。

## Walk-forward 窗口

|窗口|训练截止|验证区间|测试区间|测试行|状态|
|---|---|---|---|---:|---|
|WF1|<2023-01-01|2023-01-01–2024-01-01|2024-01-01–2025-01-01|207|TEST_DATA_AVAILABLE|
|WF2|<2024-01-01|2024-01-01–2025-01-01|2025-01-01–2026-01-01|0|NO_TEST_DATA|
|WF3|<2025-01-01|2025-01-01–2026-01-01|2026-01-01–2026-07-18|0|NO_TEST_DATA|

## 行为门槛（测试集）

|窗口|v2 Macro-F1|v3 Macro-F1|v2 MAE|v3 MAE|v3 Flip 召回|
|---|---:|---:|---:|---:|---:|
|WF1|0.178977|0.178411|0.031489|0.031891|—|
|WF2|—|—|—|—|—|
|WF3|—|—|—|—|—|

## 净成本回放

|窗口|v3 基础成本净收益|v3 基础 PF|v3 压力成本净收益|活动标准合约数|
|---|---:|---:|---:|---:|
|WF1|0.037112|1.029722|0.036428|2|
|WF2|—|—|—|0|
|WF3|—|—|—|0|

## 基线比较

|窗口|v3 基础成本|不交易|等权买入并持有|
|---|---:|---:|---:|
|WF1|0.037112|—|0.119643|
|WF2|—|—|—|
|WF3|—|—|—|

## 门槛结果

- `behavior_WF1`：**FAIL**（可用=True）
- `behavior_WF2`：**FAIL**（可用=False）
- `behavior_WF3`：**FAIL**（可用=False）
- `base_positive_all_three_windows`：**FAIL**（可用=False）
- `average_return_per_adjustment_positive`：**FAIL**
- `profit_factor_gt_one`：**FAIL**
- `stress_positive_at_least_two_of_three`：**FAIL**
- `beat_equal_weight_buy_and_hold_when_available`：**FAIL**

## 数据与单位边界

历史规格注册表用于确认 payout model、settlement currency、multiplier 和 lot size；标准化回放不会把 XBT、USD、USDT 直接相加，也不会把不同结算币种当成同一钱包余额。资金费只使用带来源时间的观测值。

## 阻塞原因与建议

- 需要公开行情覆盖到冻结截止日；当前可建模数据的测试区间为 `207` 行，WF2/WF3 是否可用见上表。
- v3 必须在每个测试窗口保持翻转动作召回率大于 0；当前结果会如实记录为失败或不可用，不用默认值掩盖。
- 在所有三段时间外测试和至少两段压力成本测试通过前，不晋级 Live；即使通过，也仍需 30 天 Demo 连续观察和人工复核。

## 产物

- `strategy_effectiveness_audit.json`：机器可读总报告。
- `strategy_effectiveness_by_window.csv`：v2/v3 逐窗口行为指标。
- `strategy_effectiveness_by_symbol.csv`：逐窗口、逐历史品种行为指标。
- `strategy_cost_sensitivity.csv`：基础/压力成本以及逐标准合约回放摘要。
