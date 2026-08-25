# Multi-venue non-production runtime

## Status

The exchange-neutral Strategy Core can now drive the following credential-gated
non-production runtimes:

| Venue | Runtime | Orders | Position semantics |
|---|---|---:|---|
| Bybit Demo | existing REST + private WebSocket runner | supported | linear/inverse derivatives |
| OKX Demo | unified REST-polling runner | supported after explicit confirmation | SWAP derivatives |
| Binance Spot Testnet | unified REST-polling runner | supported after explicit confirmation and Spot flag | wallet balances only |

The runtime loads the frozen `behavioral-distillation-v2-cross-asset-deploy`
artifact. It does not train online, connect to a mainnet endpoint, or claim
exact recovery of the original trader's strategy.

## Safety boundary

- Credentials are read from local environment variables only.
- PowerShell launchers can cache credentials encrypted with the current
  Windows user's DPAPI; the encrypted files are ignored and never logged.
- Mainnet and untrusted endpoints are rejected by the transport constructors.
- Preflight performs no order submission.
- Every decision uses closed 1-hour bars and current reconciled account state.
- Risk limits come from the historical deployment envelope and the portfolio cap.
- Active-order checks, Decimal price/quantity normalization, reconciliation,
  duplicate client IDs, and cancellation on shutdown are shared by the runner.
- Binance Spot is never treated as a short or `reduceOnly` venue. A negative
  derivative-trained target is interpreted as a request to flatten its base
  balance, and the adaptation must be explicitly enabled.

## Operational limitation

OKX and Binance use bounded REST polling as the authoritative reconciliation
path and now also start authenticated private WebSocket streams for event
health and low-latency visibility. The output state records
`market_connection=PRIVATE_WEBSOCKET` only after a private message is seen.
Reconnects fail closed for order submission. A long-run soak test and a real
Demo/Testnet order lifecycle remain open before any claim of production
readiness.

## Verification

- Full repository test suite: `308 passed` (one pre-existing test-fixture
  resource warning).
- New adapter/runtime targeted suite: `15 passed`.
- `python -m compileall -q quant_bot`: passed.
- `git diff --check`: passed.
- No exchange credentials were used during these tests.
- PowerShell launcher syntax: parsed successfully for both venues.

## Commands

```powershell
python -m quant_bot preflight --venue okx-demo
python -m quant_bot run --venue okx-demo --mode testnet --symbols auto --once

python -m quant_bot preflight --venue binance-spot-testnet
python -m quant_bot run --venue binance-spot-testnet --mode testnet --symbols auto --once --allow-spot-approximation
```

The commands fail closed with a structured credential error when the local
credential variables are absent. The order-enabled form additionally requires
`--enable-orders --confirm-testnet`.
