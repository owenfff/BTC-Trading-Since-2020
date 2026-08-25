# Read-only operator dashboard

The `frontend/` directory is a read-only monitoring surface. It does not
import an exchange adapter, read API credentials, submit orders, or proxy
private exchange requests.

## Local run

From the repository root:

```powershell
python frontend/server.py --host 127.0.0.1 --port 8080
```

Open <http://127.0.0.1:8080>.

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
exposes all three venue states in `venues` while retaining legacy
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
