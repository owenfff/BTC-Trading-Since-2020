# Long-Term Autonomous Program V4

## Scope

Build an auditable, BTC-first behavioral approximation from public trade records. The program proceeds through accounting foundation, wallet reconciliation, behavioral episodes/cycles, public market context, leakage-safe features and labels, interpretable strategy distillation, walk-forward research, exchange-neutral paper/shadow infrastructure, risk controls, adapters, and clean-room release checks.

## Current stage

Phases 1 through 11 are complete. M5 evaluated the frequency baseline, deterministic rules, NumPy Logistic Regression, and a depth-limited NumPy Decision Tree; all fidelity remains `BEHAVIORAL_APPROXIMATION`. M6 completed parity, three chronological walk-forward windows, and robustness tests with research status `RESEARCH_ONLY`; no stable profitability claim is made. Phases 8–10 added exchange-neutral domain objects, fail-closed risk controls, offline shadow mode, and local paper mode. Phase 11 added capability records plus credential-gated BitMEX/Bybit mock adapters. Phase 12 clean-room checks pass for framework compilation, shadow, and paper smoke paths; full research requires rehydrating verified ignored market and behavior outputs. Real private endpoints remain `DEMO_CREDENTIALS_REQUIRED` and live mode remains disabled.

## Stop conditions

Stop only for a real credential/funds request, paid data, CAPTCHA/manual login, destructive raw-data operation, unresolvable Git conflict, repeated infrastructure failure, unavailable public market data, or forced environment interruption. Live trading is never enabled automatically; the highest allowed final status is `LIVE_READY_PENDING_HUMAN_APPROVAL`.

## Shared strategy contract

The eventual Strategy Core must emit `strategy_version`, `signal_timestamp`, `target_exposure`, `target_position_notional`, `action`, `confidence`, `valid_until`, `max_slippage`, `execution_preference`, and `risk_tags`. It must be shared by backtest, shadow, paper, and demo modes and must not call exchange SDKs directly.
