# M15.25 Runtime Safety Patch

- Status: `IMPLEMENTED_NOT_DEMO_AUTHORIZED`
- Code commit: `4470871` (`Harden demo runtime safety and liveness`)
- Completed at: `2026-08-27T03:30:58.7482394Z`
- Strategy fidelity: `BEHAVIORAL_APPROXIMATION`
- Trading boundary: Demo/Testnet only; no credentials used; no orders submitted.

## Changes

- Disabled the legacy Bybit order runtime from the `run --mode testnet` CLI path. Missing venue selection now fails closed.
- Added source-heartbeat freshness to the dashboard. A stale `RUNNING` artifact is exposed as `STALE`, never as live; the dashboard no longer uses its own response time as the node heartbeat.
- Made the dashboard venue badge follow the active venue instead of hard-coding OKX.
- Added read-only OKX account configuration and per-instrument isolated-leverage verification before derivative orders. The bot never changes account settings automatically.
- Added equivalent one-way/isolated/leverage verification for Binance USDⓈ-M Futures Testnet.
- Added exchange-reported mark price, unrealised PnL, notional and margin fields to position snapshots and risk metrics, with explicit source labels for fallbacks.
- Preserved active orders in local state when cancellation fails and surfaced `BOT_ORDER_CANCEL_FAILED` instead of silently hiding remote risk.
- Made injected WebSocket test transports independent of the installed WebSocket package.

## Verification

```text
pytest quant/tests -q
427 passed
```

Raw root CSV/JSON inputs were not changed. The active strategy model was not replaced, and no new Demo order was authorized.

## Remaining gates

Strict autonomous replay remains blocked by the existing research evidence: the active strategy is diagnostic only, not an approved profitable policy. A real Demo lifecycle and the 14-day observation requirement remain open.
