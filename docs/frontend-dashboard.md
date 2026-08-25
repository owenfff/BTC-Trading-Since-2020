# Read-only operator dashboard

The `frontend/` directory is a read-only monitoring surface. It does not
import an exchange adapter, read API credentials, submit orders, or proxy
private exchange requests.

## Local read-only run

From the repository root:

```powershell
python frontend/server.py --host 127.0.0.1 --port 8080
```

Open <http://127.0.0.1:8080>.

## Local control panel

The control panel can start exactly one OKX or Binance node, but it must be
bound to loopback. The browser never accepts API keys. On Windows, the start
button opens the existing local PowerShell credential flow; on Linux it starts
the Python runner using credentials already supplied by the local service
environment.

Windows:

```powershell
.\deploy\start-local-control-panel.ps1
```

Linux:

```bash
./deploy/start-local-control-panel.sh
```

To configure exactly one Demo/Testnet venue without putting credentials in the
browser, run the local prompt on the trading node:

```bash
./deploy/configure-demo-credentials.sh okx-demo
# or: binance-futures-testnet / binance-spot-testnet
sudo systemctl restart quant-local-control-panel.service
```

The prompt writes only the selected venue to
`~/.config/quant-bot/credentials.env` with mode `600`. It never prints or
commits the values.

If the panel is on a remote Shanghai server, access it through an SSH tunnel
such as `ssh -L 8080:127.0.0.1:8080 user@server`; do not expose the control
panel directly to the public internet. The US server remains frontend-only.

The dashboard reads only these optional, sanitized local artifacts:

- `quant/outputs/bybit_demo_preflight.json`
- `quant/outputs/bybit_demo_runtime_state.json`
- `quant/reports/bybit_demo_symbol_mapping.json`
- `quant/outputs/okx_demo_preflight.json`
- `quant/outputs/okx_demo_runtime_state.json`
- `quant/reports/okx_demo_symbol_mapping.json`
- `quant/outputs/binance_spot_testnet_preflight.json`
- `quant/outputs/binance_spot_testnet_runtime_state.json`
- `quant/reports/binance_spot_testnet_symbol_mapping.json`
- `quant/outputs/binance_futures_testnet_preflight.json`
- `quant/outputs/binance_futures_testnet_runtime_state.json`
- `quant/reports/binance_futures_testnet_symbol_mapping.json`

The account section is read-only and shows the latest sanitized snapshot:

- total equity as the exchange-reported USD-equivalent value;
- currency balances and available amounts;
- current non-zero positions;
- open orders;
- the latest execution records returned by the trading node.

Before the trading node runs, the dashboard intentionally shows empty account
and activity sections. A successful preflight does not submit orders. Once the
Demo runtime is explicitly started, it rewrites its venue-specific
`*_runtime_state.json` after each loop. Those files may be copied to this host
by a separately secured status-sync process; they must remain sanitized and
must never contain API credentials or raw authenticated payloads. The API
exposes all supported venue states in `venues` while retaining legacy
single-active-venue fields for the existing UI.

If no artifacts are present it stays in `WAITING_FOR_TRADING_NODE` mode. The
trading runtime must run on a separate local or non-US node that can reach its
target exchange. A separate status-sync mechanism can later copy sanitized
state files to this server; API keys must never be copied to the frontend host.

## US server deployment

The checked-in service template is
`deploy/bybit-dashboard.service`. It listens on port `8080` and is independent
of the Bybit trading service. Add HTTPS and authentication before exposing
account-level telemetry publicly.

The dashboard is an observability surface only. It remains
`BEHAVIORAL_APPROXIMATION` and makes no profitability claim.
