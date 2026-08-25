# OKX Demo and Binance Spot Testnet

The strategy artifact is trained from the repository's historical data and is
loaded read-only at runtime. It remains a `BEHAVIORAL_APPROXIMATION`; it is not
a claim that the original trader's private rules have been recovered.

## Local-only credentials

OKX Demo reads:

```powershell
$env:OKX_DEMO_API_KEY="..."
$env:OKX_DEMO_API_SECRET="..."
$env:OKX_DEMO_API_PASSPHRASE="..."
```

Binance Spot Testnet reads:

```powershell
$env:BINANCE_TESTNET_API_KEY="..."
$env:BINANCE_TESTNET_API_SECRET="..."
```

The values are never written to Git, reports, dashboard state, or chat.

The PowerShell launchers cache them encrypted with Windows-user DPAPI after
the first prompt, so later starts do not require retyping them:

```powershell
.\deploy\start-okx-demo.ps1 -Mode readonly
.\deploy\start-binance-testnet.ps1 -Mode readonly
```

Use `-ForgetCredentials` to remove the local cache. The cache is tied to the
same Windows user and cannot be decrypted by another account.

## Preflight

From the repository root, using the project's Python runtime:

```powershell
python -m quant_bot preflight --venue okx-demo
python -m quant_bot preflight --venue binance-spot-testnet
```

Preflight does not submit orders. It verifies credentials, server time,
account reconciliation, instruments, and the historical-to-current symbol
mapping.

## Read-only runtime

```powershell
python -m quant_bot run --venue okx-demo --mode testnet --symbols auto --once
python -m quant_bot run --venue binance-spot-testnet --mode testnet --symbols auto --once --allow-spot-approximation
```

The long-running form replaces `--once` with `--poll-seconds 60`. State is
written under `quant/outputs/` and is intended for the dashboard, not for
source control.

## Unified launcher

When both local credential caches are available, one PowerShell process can
supervise both non-production venues:

```powershell
.\deploy\start-multivenue.ps1 -Mode readonly
```

It keeps separate REST reconciliation, private WebSocket health, symbol
mapping and runtime state for OKX and Binance. A failure on one venue is
reported under that venue and never silently treated as a successful order.
The first run asks for each credential locally and stores an encrypted
Windows-user DPAPI cache under ignored `quant/outputs/`; later runs reuse it.

To start the read-only dashboard and one selected venue:

```powershell
 .\deploy\start-quant-stack.ps1 -Venue okx-demo -Mode readonly
```

Use `-Venue binance-spot-testnet` to select Binance. `-Venue both` is an
explicit optional supervisor mode; it is never the default. The dashboard is
intentionally frontend-only and is stopped when the stack process exits. Use
`-DashboardHost 0.0.0.0` only on a private/local network; do not put exchange
credentials on a public frontend host.

## Explicit Demo/Testnet orders

Only after preflight and a read-only run are understood:

```powershell
python -m quant_bot run --venue okx-demo --mode testnet --symbols auto --enable-orders --confirm-testnet --poll-seconds 60
python -m quant_bot run --venue binance-spot-testnet --mode testnet --symbols auto --enable-orders --confirm-testnet --allow-spot-approximation --poll-seconds 60
```

The equivalent unified testnet command is:

```powershell
.\deploy\start-multivenue.ps1 -Mode testnet -ConfirmTestnet -AllowSpotApproximation
```

The commands are hard-pinned to non-production endpoints. A mainnet URL is
rejected by the connector. The runtime reconciles by REST and also starts the
venue's private WebSocket; order submission is blocked until that stream is
healthy. Binance Spot is not a leveraged short venue, so the explicit
approximation flag is required and negative targets are treated as a request
to flatten the base-asset balance.
