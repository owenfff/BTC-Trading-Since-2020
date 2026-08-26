# Cross-Venue Strategy Equivalence Audit

> Status: **`SHARED_INTENT_SUPPORTED_VENUE_NATIVE_POLICY_REQUIRED`**. This is a descriptive boundary report, not a model promotion or identity proof.

## Direct answer

如果两个公开账户确实属于同一个交易员，最合理的解释是：**共享高层交易意图，但执行策略按交易所条件变化**。同一人的仓位管理习惯可以一致，订单价格、数量、时机和风险尺度不应直接视为一致。

## Venue evidence

| venue | source role | observations | action events | execution evidence |
|---|---|---:|---:|---|
| BITMEX | teacher behavior profile | 258492 clock rows | 12709 | lifecycle/order export; no independent historical order-book stream |
| Hyperliquid | external public reference | 341 fills | 341 | True Limit, True GTC in the pinned snapshot |

Common action families observed: `ADD, FLIP, OPEN, REDUCE`.

The denominators are intentionally not treated as interchangeable: BitMEX is a clock-row behavior profile while Hyperliquid is a partial public order/fill snapshot.

## What can be shared

- 有状态目标仓位调整；
- 开仓、加仓、减仓、反手等高层动作词汇；
- 持仓 episode、分批调整和观望路径。

## What must stay venue-native

- `contract_multiplier_and_settlement_currency`；
- `symbol_and_market_availability`；
- `fee_funding_margin_and_leverage_rules`；
- `quote_depth_latency_and_order_queue`；
- `order_lifecycle_and_fill_semantics`；

## Gates

| gate | status | detail |
|---|---|---|
| `shared_action_vocabulary` | **SUPPORTED_APPROXIMATION** | The two sources share several high-level position-adjustment actions; this supports a shared vocabulary, not identical rules. |
| `same_executable_policy` | **NOT_ESTABLISHED** | Venue-native contract, market, cost, liquidity and execution context differ; records must remain separated. |
| `same_trader_identity` | **USER_PROVIDED_PREMISE_NOT_DATA_VERIFIED** | The audit accepts the research premise that the accounts are one trader, but the repository does not cryptographically prove identity from these reports. |
| `exact_private_trigger_recovery` | **BLOCKED** | The available sources do not contain complete pre-action quote/order-book state and private trigger intent for both venues. |

## Modeling rule

`Use a shared high-level intent layer with independent venue adapters/calibration; never combine positions, units, fees, funding or order books across venues.`

当前结论仍为 `BEHAVIORAL_APPROXIMATION`；本报告不授权模型切换、不新增 Demo 订单、不连接主网。原始 CSV/JSON 保持不变。
