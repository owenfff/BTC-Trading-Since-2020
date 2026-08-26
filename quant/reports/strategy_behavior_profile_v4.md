# Strategy Behavior Profile V4

> This is a descriptive profile of public trade records. It is not proof of the original trader's indicators, a causal strategy explanation, a profitability claim, or a deployable model.

## Data scope

- Rows seen: `264609`; eligible rows with complete market context: `264288`.
- Decision range: `2020-05-01T11:00:00Z` to `2026-07-18T20:00:00Z`.
- Non-idle observed action rate: `4.87%`.

## What the record actually shows

| action | count | share of eligible rows |
|---|---:|---:|
| `ADD_LONG` | 3754 | 1.42% |
| `ADD_SHORT` | 2488 | 0.94% |
| `CLOSE_LONG` | 681 | 0.26% |
| `CLOSE_SHORT` | 232 | 0.09% |
| `FLIP_LONG` | 115 | 0.04% |
| `FLIP_SHORT` | 106 | 0.04% |
| `NO_TRADE` | 251422 | 95.13% |
| `OPEN_LONG` | 663 | 0.25% |
| `OPEN_SHORT` | 248 | 0.09% |
| `REDUCE_LONG` | 2671 | 1.01% |
| `REDUCE_SHORT` | 1908 | 0.72% |

## Cross-venue observation

| venue | rows | non-idle rate | target abs mean |
|---|---:|---:|---:|
| `BITMEX` | 258492 | 4.92% | 0.100566 |
| `HYPERLIQUID` | 5796 | 2.71% | 0.332662 |

## Strongest observed associations

Lift means action rate in the bucket divided by its overall eligible-row rate. It is descriptive, can be confounded by position state and time, and is not a trading rule.

### rsi14

- `<30_OVERSOLD` → `FLIP_SHORT`: rate `0.09%`, baseline `0.04%`, lift `2.36x`, support `12`.
- `<30_OVERSOLD` → `REDUCE_SHORT`: rate `1.67%`, baseline `0.72%`, lift `2.32x`, support `212`.
- `>=70_OVERBOUGHT` → `CLOSE_LONG`: rate `0.59%`, baseline `0.26%`, lift `2.30x`, support `87`.
- `>=70_OVERBOUGHT` → `ADD_SHORT`: rate `2.07%`, baseline `0.94%`, lift `2.20x`, support `304`.
- `>=70_OVERBOUGHT` → `OPEN_SHORT`: rate `0.18%`, baseline `0.09%`, lift `1.96x`, support `27`.

### macd_histogram

- `NEGATIVE` → `FLIP_LONG`: rate `0.05%`, baseline `0.04%`, lift `1.18x`, support `68`.
- `NEGATIVE` → `ADD_LONG`: rate `1.65%`, baseline `1.42%`, lift `1.16x`, support `2186`.
- `NEGATIVE` → `REDUCE_SHORT`: rate `0.83%`, baseline `0.72%`, lift `1.15x`, support `1094`.
- `NONNEGATIVE` → `REDUCE_LONG`: rate `1.13%`, baseline `1.01%`, lift `1.12x`, support `1492`.
- `NONNEGATIVE` → `ADD_SHORT`: rate `1.05%`, baseline `0.94%`, lift `1.11x`, support `1384`.

### bollinger_percent_b

- `<0_BELOW_LOWER` → `FLIP_LONG`: rate `0.09%`, baseline `0.04%`, lift `1.97x`, support `14`.
- `<0_BELOW_LOWER` → `REDUCE_SHORT`: rate `1.37%`, baseline `0.72%`, lift `1.90x`, support `224`.
- `>1_ABOVE_UPPER` → `REDUCE_LONG`: rate `1.90%`, baseline `1.01%`, lift `1.88x`, support `311`.
- `>1_ABOVE_UPPER` → `ADD_SHORT`: rate `1.60%`, baseline `0.94%`, lift `1.70x`, support `262`.
- `>1_ABOVE_UPPER` → `FLIP_SHORT`: rate `0.07%`, baseline `0.04%`, lift `1.67x`, support `11`.

### market_regime

- `TREND_DOWN` → `FLIP_LONG`: rate `0.06%`, baseline `0.04%`, lift `1.32x`, support `58`.
- `TREND_UP` → `ADD_SHORT`: rate `1.15%`, baseline `0.94%`, lift `1.23x`, support `1185`.
- `TREND_DOWN` → `REDUCE_SHORT`: rate `0.87%`, baseline `0.72%`, lift `1.21x`, support `882`.
- `TREND_DOWN` → `ADD_LONG`: rate `1.72%`, baseline `1.42%`, lift `1.21x`, support `1732`.
- `TREND_UP` → `CLOSE_LONG`: rate `0.30%`, baseline `0.26%`, lift `1.18x`, support `312`.

### current_exposure

- `SHORT` → `ADD_SHORT`: rate `5.58%`, baseline `0.94%`, lift `5.92x`, support `2488`.
- `SHORT` → `REDUCE_SHORT`: rate `4.28%`, baseline `0.72%`, lift `5.92x`, support `1908`.
- `SHORT` → `CLOSE_SHORT`: rate `0.52%`, baseline `0.09%`, lift `5.92x`, support `232`.
- `SHORT` → `FLIP_LONG`: rate `0.26%`, baseline `0.04%`, lift `5.92x`, support `115`.
- `LONG` → `ADD_LONG`: rate `3.85%`, baseline `1.42%`, lift `2.71x`, support `3754`.

### return_24bar

- `ZERO` → `OPEN_LONG`: rate `0.42%`, baseline `0.25%`, lift `1.67x`, support `6`.
- `ZERO` → `CLOSE_LONG`: rate `0.42%`, baseline `0.26%`, lift `1.63x`, support `6`.
- `POSITIVE` → `ADD_SHORT`: rate `1.11%`, baseline `0.94%`, lift `1.18x`, support `1472`.
- `NEGATIVE` → `FLIP_LONG`: rate `0.05%`, baseline `0.04%`, lift `1.16x`, support `66`.
- `NEGATIVE` → `REDUCE_SHORT`: rate `0.81%`, baseline `0.72%`, lift `1.13x`, support `1060`.

## Holding and action timing

- Observed cycle-duration mean / P95: `49.92728832392948` / `223.26404194444444` hours.
- Same venue/instrument action-interval mean / P95: `20.183877519137635` / `64.0` hours.

## Strategy interpretation boundary

The defensible conclusion is a stateful, position-adjustment behavior pattern: most clock periods are idle, and non-idle actions are heavily conditioned by current exposure, instrument, and observed market context. The data does not identify a unique RSI/MACD rule or prove that indicators caused any action. The autonomous candidates remain separate and must pass strict walk-forward validation before Demo promotion.

## Safety

No credentials, private endpoint, mainnet connection, or order was used. Raw source CSV/JSON files remain read-only.
