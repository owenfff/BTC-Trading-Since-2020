# Behavioral Strategy Specification V1

> `BEHAVIORAL_APPROXIMATION` / `APPROXIMATION_ONLY`. This document is an evidence contract, not a trained model, profitability claim, or order authorization.

## Plain-language conclusion

当前最可靠的提炼不是“某一个指标发出买卖信号”，而是一个**有状态的目标仓位调整过程**：大多数时间观望，进入非空仓位后反复小步加仓、减仓、平仓或反手；执行层可用被动挂单作为近似，必要时才做受限主动纠偏。

这仍然不是原交易员私有策略的精确恢复。成交前的精确触发条件、当时盘口、撤单意图和主观判断，在当前公开导出中不可识别。RSI、MACD、布林带等只属于模型输入候选，不是原交易员真实使用它们的证据。

## Evidence layers

| layer | classification | confidence | safe interpretation |
|---|---|---|---|
| `inventory_state` | `OBSERVED_FACT` | `HIGH` | Non-idle behavior is strongly conditioned by current exposure and position state; the public record supports a stateful position-adjustment description. |
| `sparse_adjustment_actions` | `OBSERVED_FACT` | `HIGH` | Most eligible clock rows are NO_TRADE; observed non-idle rows contain directional opens, adds, reductions, closes and flips. |
| `passive_inventory_execution` | `SUPPORTED_APPROXIMATION` | `MEDIUM` | Layered limit/GTC execution is a plausible implementation of the observed inventory-adjustment behavior, supported by an independent public analysis, but it is not proven to be the trader's private rule. |
| `urgency_override` | `SUPPORTED_APPROXIMATION` | `MEDIUM` | Market/IOC-style execution can be used only as a bounded urgency override when passive execution cannot safely correct the target; this is an implementation hypothesis, not an identified trigger. |
| `position_episode_risk` | `OBSERVED_FACT` | `HIGH` | The record is better described as position episodes with repeated adjustments than as isolated independent trades; holding duration and action interval are measurable, while the private risk limits are not. |
| `indicator_inputs` | `SUPPORTED_APPROXIMATION` | `LOW` | Indicators are valid causal model inputs when computed from already-closed bars, but correlations and bucket lifts do not establish that the original trader used these indicators or that they caused an action. |
| `pre_action_timing` | `UNIDENTIFIABLE` | `BLOCKED` | The current public export does not identify the exact pre-action trigger, quote state, order-book condition, cancellation intent or private decision rule. |
| `cross_venue_execution` | `SUPPORTED_APPROXIMATION` | `MEDIUM` | The same trader identity can support a shared high-level intent vocabulary, but executable behavior remains venue-native because contract scale, funding, liquidity, symbol coverage and order semantics differ. |

## What the robot may implement

1. 只在自己的已对账仓位状态上计算目标暴露。
2. 保留显式观望路径，不把每次指标波动都转成订单。
3. 跨交易所共享高层动作词汇，但按交易所分别处理合约乘数、币种、资金费、盘口和执行语义。
4. 被动挂单、单合约单活动订单、ReduceOnly 反手先减仓、过期/失联/对账失败时拒绝下单。
5. 只有严格自主时间外回放通过门槛，才允许候选模型进入 Demo 观察。

## What remains blocked

- 精确知道“为什么在这一秒下单”。
- 证明指标就是原交易员当时使用的指标。
- 从公开成交记录恢复未公开的盘口、撤单前意图或主观风险限额。
- 把条件式动作分类分数当成自主信号。
- 宣称盈利或允许主网/实盘自动切换。

## Audit facts

- Eligible rows: `264288`; non-idle rows: `12866`; non-idle rate: `4.87%`.
- Venues retained separately: `BITMEX, HYPERLIQUID`.
- The current active runtime/model is unchanged; no new Demo orders are authorized by this specification.

## Sources

- `quant\reports\strategy_behavior_profile_v4.json` — `STRATEGY-BEHAVIOR-PROFILE-V4`; SHA256 `867efac94e5c559e7b46a142a5201970d6d0455bcb9be11742b8356981ddb49c`.
- `quant\reports\pre_action_observability_audit.json` — `M15-PRE-ACTION-OBSERVABILITY-1.0`; SHA256 `0c9ab309670e4de538578be03b710f8f8eaed96e607cfec4defaf9241382240c`.
- `quant\reports\identifiability_ceiling_audit.json` — `M15-IDENTIFIABILITY-CEILING-1.0`; SHA256 `a5ac9a3e07c7811d06eb2f6627ad14205f9f63f34490539eae5db30cb5d4ebc5`.
- [Paul Wei Hyperliquid BTC tracker](https://paul.catseye.today/) — visual replay and public-state cross-check. Limitation: A replay of public candles, fills, orders and state snapshots; it does not by itself expose a complete pre-action quote/order-book history or private decision rule.
- [TradeTrace Paul Wei trading pattern research](https://github.com/AaronL725/TradeTrace/blob/main/reports/paulwei-analysis.md) — independent interpretation of observable execution and inventory patterns. Limitation: Secondary analysis, not a private strategy disclosure or proof of causality; its conservative rules remain hypotheses.

## Boundary

No credentials, private endpoint, mainnet connection or order was used. Root raw CSV/JSON inputs remain read-only.
