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

The loopback-only control panel can now select exactly one OKX Demo, Binance
Spot Testnet, or Binance USDⓈ-M Futures Testnet node and start/stop its local
launcher. The browser sends only venue, mode and explicit testnet confirmation;
credentials never enter the browser. This panel is suitable for a Shanghai
trading node reached through an SSH tunnel, while the US dashboard remains
frontend-only.

## Shanghai node deployment

The verified runtime bundle from code commit `0ef2df42e9b1817c636df70c8656fdc142924eb6`
is deployed at `/home/ubuntu/apps/btc-current` on the Shanghai Ubuntu 24.04
node. The `quant-local-control-panel.service` system service is enabled and
active, listens only on `127.0.0.1:8080`, and is reachable through an SSH
tunnel. Python 3.12.3, NumPy 2.3.5 and WebSockets 15.0.1 are installed; the
frozen model loads successfully with 66 symbols. The local credential helper
uses hidden terminal input and writes only mode-600 credentials; no credential
has been installed and no order has been submitted. Current state is therefore
`WAITING_FOR_TRADING_NODE` until one Demo/Testnet venue is configured locally.

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

- Code commit: `cdbdc62d2e47003d2455a3e993ccbb099fc52c28`.
- Loopback dashboard control commit: `75e0bf8`.
- Local credential setup helper commit: `195d3d9`; shell line-ending fix:
  `0ef2df4`.
- Follow-up stack launcher commit: `ad7b8ec4f9ba603a7e08a8b6736244e3f56b1849`.
- Single-venue selection commit: `2e0e82b794f4412256b330dc4e4c4a04f4b27f0c`.
- The stack defaults to OKX; Binance Spot or Binance Futures is selected by the
  operator. Simultaneous supervision remains an explicit opt-in only.
- Full repository test suite: `324 passed` in 137.84 seconds, zero warnings.
- Current follow-up full repository test suite: `327 passed`; this includes the
  external public-source behavior-profile test.
- Latest full repository test suite: `330 passed`; this includes the loopback
  credential setup and platform-boundary tests.
- Binance Futures targeted suite: `5 passed`; adapter/runtime targeted suite: `16 passed`.
- Read-only dashboard venue coverage targeted suite: `6 passed`; the
  dashboard now exposes Binance USDⓈ-M Futures state alongside OKX, Binance
  Spot and Bybit without importing adapters or credentials.
- Local control-panel targeted suite: `6 passed`; credential-shaped fields are
  rejected, non-loopback control is rejected, only one local venue can run,
  and Testnet confirmation is mandatory.
- Unified supervisor targeted suite: `4 passed`.
- Unified runtime lifecycle/restart suite: `3 passed`.
- `python -m compileall -q frontend quant_bot`: passed.
- `git diff --check`: passed.
- All seven PowerShell launchers: parsed successfully.
- Shanghai deployment checks: Bash syntax passed, model load passed, systemd
  panel service `active` and `enabled`, loopback status API returned 200.
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

.\deploy\start-local-control-panel.ps1
```

On Linux trading nodes, use `./deploy/start-local-control-panel.sh`. The
control panel is deliberately loopback-only; expose it through an SSH tunnel,
not a public listener.

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
