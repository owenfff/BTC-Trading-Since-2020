# Cross-Venue Indicator and Autonomous Replay Audit

- 状态：**DEMO_CONTINUE_LIVE_BLOCKED**
- 策略保真度：`BEHAVIORAL_APPROXIMATION`
- 本次不连接私有 API、不提交订单、不切换 Demo 模型。

## 数据与覆盖

- BitMEX 行：`31311`；Hyperliquid 行：`320`
- v3 可用行：`31631`
- 行级覆盖：`{'PASS': 31631}`
- 指标缺失：`{'feature_rsi_14': 0, 'feature_macd_histogram': 0, 'feature_bollinger_percent_b_20': 0, 'feature_volume_percentile_72bar': 0}`

## Walk-forward

|窗口|训练行|验证行|测试行|自主轨道|
|---|---:|---:|---:|---|
|WF1|24003|2930|2462|可用|
|WF2|26933|2462|1781|可用|
|WF3|29395|1781|455|可用|

## 严格自主状态证明

- 起始仓位：`ZERO`。
- 动态账户字段全部由模拟状态覆盖。
- `teacher_state_fields_consumed = 0`。
- 同一交易所/标准资产同一时刻只保留一个合并目标。

## 指标增强行为结果

|窗口|v2 F1|v3 F1|v2 MAE|v3 MAE|v3自主 F1|v3自主 MAE|
|---|---:|---:|---:|---:|---:|---:|
|WF1|0.210132|0.209158|0.019038|0.019336|0.057706|0.898461|
|WF2|0.148782|0.148381|0.028604|0.029665|0.068779|0.780113|
|WF3|0.063025|0.064603|0.016932|0.017016|0.007590|1.128019|

## 自主成本回放

|窗口|v3 基础净收益|v3 PF|压力净收益|不交易|等权持有|
|---|---:|---:|---:|---:|---:|
|WF1|-0.622667|0.944398|-0.783688|—|0.128624|
|WF2|-0.124975|0.997446|-0.125201|—|-0.147098|
|WF3|-0.285413|0.964485|-0.285971|—|-0.262392|

## 门槛

- `time_leakage_zero`：**PASS**
- `protected_raw_hashes_unchanged`：**PASS**
- `autonomous_test_WF1_available`：**PASS**
- `autonomous_test_WF2_available`：**PASS**
- `autonomous_test_WF3_available`：**PASS**
- `v3_vs_v2_behavior_thresholds`：**PASS**
- `autonomous_positive_all_windows`：**FAIL**
- `autonomous_profit_factor_gt_one`：**FAIL**
- `autonomous_beats_equal_weight_hold`：**FAIL**

## 解释边界

该报告检验的是跨交易所行为近似和自主回放，不是原交易员私有意图恢复，也不是账户真实收益预测。Hyperliquid 数据作为用户确认的同一老师来源纳入研究，但仍保留独立 venue/source/revision 字段。

## 产物

- `cross_venue_indicator_autonomous_audit.json`
- `cross_venue_indicator_model_manifest.json`
- `cross_venue_indicator_by_window.csv`
- `cross_venue_indicator_by_symbol.csv`
- `cross_venue_indicator_cost_sensitivity.csv
