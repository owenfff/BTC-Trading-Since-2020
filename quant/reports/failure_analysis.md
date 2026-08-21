# Failure Analysis

- Research status is `RESEARCH_ONLY`; no claim of stable sample-out performance is made.
- The backtest uses a normalized exposure-return proxy because historical account currency, inverse contract payout, and wallet PnL are not interchangeable.
- Historical mark/index observations are unavailable and remain missing; trade prices are never used to invent them.
- The fee rate is an observed blended XBTUSD ratio from `execComm_raw` and `execCost_raw`; it is not a promise of future maker/taker pricing.
- Tick size uses the frozen XBTUSD snapshot value `0.1`; historical tick changes are a documented caveat.
- Funding is applied only when the verified public context contains an as-of funding rate.
- Teacher historical trajectory is descriptive and must not be interpreted as a deployable signal.
- Cycle-removal tests remove frozen teacher cycle intervals from the result series; they are sensitivity diagnostics, not causal counterfactuals.
- No API key, private account, exchange SDK, order submission, live capital, or automated trading path was used.
