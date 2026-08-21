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
