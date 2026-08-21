# Feature Dictionary

All feature columns are computed at decision time `t` using only observations with timestamps strictly before `t`. No train/test normalization statistics are fitted in M4.

## Market features

| feature | definition | missing rule |
| --- | --- | --- |
| `feature_return_{1,3,6,12,24,72}bar` | Close-to-close return over prior closed 5m bars | null if the complete UTC grid window is unavailable |
| `feature_realized_volatility_72bar` | Population standard deviation of prior 72 log returns | null if any child interval is incomplete |
| `feature_atr_14bar` | 14-bar true-range average | null if prior close/child bar is missing |
| `feature_volume_change_1bar` | Latest closed volume versus prior closed volume | null if prior volume is zero/missing |
| `feature_volume_percentile_72bar` | Rank of latest volume within prior 72 closed bars | null if the window is incomplete |
| `feature_ma_distance_24bar` | Close divided by prior 24-bar mean minus one | null if the window is incomplete |
| `feature_trend_slope_24bar` | OLS slope of log close over prior 24 bars | null if the window is incomplete |
| `feature_distance_rolling_high_72bar` | Close divided by prior 72-bar high minus one | null if the window is incomplete |
| `feature_distance_rolling_low_72bar` | Close divided by prior 72-bar low minus one | null if the window is incomplete |
| `feature_funding_rate` | Funding observation attached as-of to the latest prior bar | null if funding is unavailable |
| `feature_mark_index_basis` | Mark/index minus one | null and `feature_mark_index_missing=1` because historical series is unavailable |
| `feature_market_regime` | Deterministic trend/range bucket from past slope and MA distance | `UNKNOWN` until the windows are complete |
| time features | UTC time-of-day and day-of-week encodings | always known from decision timestamp |

## Account and behavior features

These use prior decisions, prior closed cycles, prior fills, and the position immediately before the decision. `feature_current_normalized_exposure` is contract quantity divided by the fixed XBTUSD contract scale of 10,000,000; it is not a BTC or USD notional claim.

`feature_fee_accumulation_raw` uses prior `execComm_raw` values; `feature_funding_accumulation_raw` uses prior closed-cycle funding values. Current decision action/order confidence is not used as a feature; the previous strictly earlier decision is used instead.
