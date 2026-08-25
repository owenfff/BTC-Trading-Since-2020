# Autonomous Quant Bot Readiness

## Current conclusion

The repository has a runnable, exchange-neutral behavioral-approximation bot
with separate non-production adapters for OKX Demo, Binance Spot Testnet and
Binance USDⓈ-M Futures Testnet. It is **ready for credential-gated
non-production preflight**, but it is not yet verified for a real Demo/Testnet
order lifecycle and is not approved for mainnet or real funds.

## Strategy foundation

- Source: historical BitMEX order, execution, position, wallet and instrument records.
- Strategy fidelity: `BEHAVIORAL_APPROXIMATION`.
- Runtime model: `behavioral-distillation-v2-cross-asset-deploy`.
- Runtime inputs: closed 1-hour market bars plus reconciled account state.
- Online training: disabled.
- Spot and leveraged derivatives: separate position semantics.
- The public Hyperliquid reference snapshot is audited separately and is not a
  training label for the BitMEX teacher model.

## Implemented venue paths

| Venue | Mode | Order path | Mainnet guard | Credentials |
| --- | --- | --- | --- | --- |
| OKX | Demo | REST + private WebSocket health | enforced | local only |
| Binance Spot | Testnet | REST + private WebSocket health | enforced | local only |
| Binance USDⓈ-M Futures | Testnet | REST + private WebSocket health | enforced | local only |

The bot supports one selected venue by default. Multi-venue supervision is
explicit opt-in and keeps each venue's state, reconciliation and failures
separate.

## One-time local credential setup

The Shanghai Linux loopback control panel now has a local credential form. It
accepts only the selected venue's Demo/Testnet fields, requires the explicit
local-control header, clears the browser fields after saving, atomically writes
`~/.config/quant-bot/credentials.env` with mode `600`, and passes the selected
values only to the local child runtime. The status API exposes only
`CONFIGURED`/`NOT_CONFIGURED`, never credential values.

Windows keeps the existing DPAPI launcher path. The public/US frontend cannot
use the credential endpoint because the control server is loopback-only.

## Verified locally

- Full test suite: `330 passed`.
- Model loading and feature contract: passed.
- Target planning, Decimal quantity/price conversion and reduce-only logic:
  passed.
- Idempotency, restart recovery, reconciliation, kill switch and stale-data
  guards: passed.
- OKX/Binance venue adapter and runtime targeted tests: passed.
- No-credential preflight for all three venues: returned structured
  `*_CREDENTIALS_REQUIRED`, submitted zero orders.
- Mainnet/untrusted endpoint rejection: tested.
- No API key or secret was used in the verification run.

## What remains before non-production trading

The code cannot verify private account connectivity or a real order lifecycle
without local exchange credentials. One venue must be selected, then its
credentials must be installed on the trading node using the local credential
helper. The required sequence is:

1. install credentials locally on the Shanghai trading node;
2. run read-only preflight;
3. run one order-enabled Demo/Testnet lifecycle with the explicit confirmation
   flag;
4. verify account/position/order/fill reconciliation, reconnect behavior and
   cancellation on shutdown;
5. leave the bot in paper/Demo mode until the soak and risk review pass.

Credentials must never be sent in chat, stored in Git, entered in the browser,
or installed on the US frontend host. Mainnet URLs and real-money modes remain
rejected by design.

## Operational commands

```powershell
python -m quant_bot preflight --venue okx-demo
python -m quant_bot run --venue okx-demo --mode testnet --symbols auto --once

python -m quant_bot preflight --venue binance-futures-testnet
python -m quant_bot run --venue binance-futures-testnet --mode testnet --symbols auto --once
```

For the browser dashboard, expose only the Shanghai loopback control panel
through an SSH tunnel. The frontend never receives or reads credentials.

To synchronize the panel from a normal SSH login, use
`.\deploy\sync-shanghai-panel.ps1` in PowerShell (or
`./deploy/sync-shanghai-panel.sh` in Git Bash). It uploads only the four panel files,
verifies SHA256 and Python compilation remotely, then restarts the loopback
service; it never handles exchange credentials.
