# Architecture

`Strategy Core → portfolio allocator → risk engine → execution planner → adapter → order manager → fill tracker → reconciliation`.

The Strategy Core emits target exposure and never imports an exchange SDK. Domain objects use `Decimal`, UTC timestamps, canonical symbols, and explicit settlement currencies. The backtest, offline paper runtime, and future adapters share the same signal and order contracts. The current branch contains no live network connector.
