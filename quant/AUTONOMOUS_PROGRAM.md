# Long-Term Autonomous Program V4

## Scope

Build an auditable, BTC-first behavioral approximation from public trade records. The program proceeds through accounting foundation, wallet reconciliation, behavioral episodes/cycles, public market context, leakage-safe features and labels, interpretable strategy distillation, walk-forward research, exchange-neutral paper/shadow infrastructure, risk controls, adapters, and clean-room release checks.

## Current stage

Phases 1 through 3 are complete. `currentCost` and AEP residuals remain visible but are not a global blocker; wallet reconciliation and behavior data are frozen with explicit warnings. The next work package is public BTC canonical market context.

## Stop conditions

Stop only for a real credential/funds request, paid data, CAPTCHA/manual login, destructive raw-data operation, unresolvable Git conflict, repeated infrastructure failure, unavailable public market data, or forced environment interruption. Live trading is never enabled automatically; the highest allowed final status is `LIVE_READY_PENDING_HUMAN_APPROVAL`.

## Shared strategy contract

The eventual Strategy Core must emit `strategy_version`, `signal_timestamp`, `target_exposure`, `target_position_notional`, `action`, `confidence`, `valid_until`, `max_slippage`, `execution_preference`, and `risk_tags`. It must be shared by backtest, shadow, paper, and demo modes and must not call exchange SDKs directly.
