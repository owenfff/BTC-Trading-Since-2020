# Multi-venue non-production runtime

## Status

The exchange-neutral Strategy Core can now drive the following credential-gated
non-production runtimes:

| Venue | Runtime | Orders | Position semantics |
|---|---|---:|---|
| Bybit Demo | existing REST + private WebSocket runner | supported | linear/inverse derivatives |
| OKX Demo | unified REST-polling runner | supported after explicit confirmation | SWAP derivatives |
| Binance Spot Testnet | unified REST-polling runner | supported after explicit confirmation and Spot flag | wallet balances only |
| Binance USDⓈ-M Futures Testnet | unified REST-polling runner | supported after explicit confirmation | linear USDT perpetual positions |

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

The read-only dashboard API now aggregates the venue state files under
`venues`; the frontend server never imports exchange adapters and never reads
credentials.

The OKX/Binance launchers now resolve the repository-relative paths
correctly, and `deploy/start-multivenue.ps1` supervises both non-production
Spot/OKX venues from one local process. Binance USDⓈ-M Futures is selected as a
separate single-venue launcher. Each venue retains an independent account
snapshot, mapping report, runtime state and BLOCKED result. A missing
credential or venue-specific failure is not converted into a successful
multi-venue status.

The human-readable strategy summary is in
`quant/reports/strategy_rules.md`. It distinguishes the deterministic rule
baseline from the deployed cross-asset logistic artifact and lists the model's
zero flip-recall limitation.

## Verification

- Code commit: `79af72cf41c16cb32f8c19c1f2b1894e65da6733`.
- Follow-up stack launcher commit: `ad7b8ec4f9ba603a7e08a8b6736244e3f56b1849`.
- Single-venue selection commit: `2e0e82b794f4412256b330dc4e4c4a04f4b27f0c`.
- The stack defaults to OKX; Binance Spot or Binance Futures is selected by the
  operator. Simultaneous supervision remains an explicit opt-in only.
- Full repository test suite: `319 passed` in 132.78 seconds, zero warnings.
- Binance Futures targeted suite: `5 passed`; adapter/runtime targeted suite: `16 passed`.
- Unified supervisor targeted suite: `4 passed`.
- Unified runtime lifecycle/restart suite: `3 passed`.
- `python -m compileall -q quant_bot`: passed.
- `git diff --check`: passed.
- All five PowerShell launchers: parsed successfully.
- Credential-gated `run-all --once` without credentials returned structured
  `DEMO_CREDENTIALS_REQUIRED` / `TESTNET_CREDENTIALS_REQUIRED` results and
  submitted zero orders. Individual Binance Futures preflight and run also
  failed closed with `TESTNET_CREDENTIALS_REQUIRED` and submitted zero orders.
- No exchange credentials were used during these tests.
- Raw root CSV/JSON inputs were not modified.
- Remote branch parity was confirmed after pushing the code, report and state
  pointer commits.

## Commands

```powershell
python -m quant_bot preflight --venue okx-demo
python -m quant_bot run --venue okx-demo --mode testnet --symbols auto --once

python -m quant_bot preflight --venue binance-spot-testnet
python -m quant_bot run --venue binance-spot-testnet --mode testnet --symbols auto --once --allow-spot-approximation

python -m quant_bot preflight --venue binance-futures-testnet
python -m quant_bot run --venue binance-futures-testnet --mode testnet --symbols auto --once

.\deploy\start-binance-futures-testnet.ps1 -Mode readonly

.\deploy\start-multivenue.ps1 -Mode readonly
```

The commands fail closed with a structured credential error when the local
credential variables are absent. The order-enabled form additionally requires
`--enable-orders --confirm-testnet`.
- Remote branch parity was confirmed after pushing the code, report and state
  pointer commits.
- The stack defaults to OKX; Binance or explicit simultaneous mode must be
  selected by the operator.
- With all local credentials absent, individual OKX and Binance runs returned
  their own structured credential errors and submitted no orders.
- The single-venue gate and adapter/runtime tests returned `16 passed`.
