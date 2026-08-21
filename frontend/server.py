#!/usr/bin/env python3
"""Read-only operator dashboard server.

This process never imports an exchange adapter and never reads exchange
credentials. It serves the dashboard plus sanitized local runtime artifacts.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


FRONTEND_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = FRONTEND_ROOT.parent


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, OSError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def status_payload() -> dict[str, Any]:
    preflight = _read_json(PROJECT_ROOT / "quant" / "outputs" / "bybit_demo_preflight.json")
    runtime = _read_json(PROJECT_ROOT / "quant" / "outputs" / "bybit_demo_runtime_state.json")
    mapping = _read_json(PROJECT_ROOT / "quant" / "reports" / "bybit_demo_symbol_mapping.json")
    has_feed = bool(preflight or runtime or mapping)
    mapping_rows = mapping.get("symbols", []) if isinstance(mapping.get("symbols"), list) else []
    return {
        "dashboard_role": "FRONTEND_ONLY",
        "exchange_connection": "NONE_FROM_THIS_SERVER",
        "trading_enabled_here": False,
        "feed_status": "CONNECTED" if has_feed else "WAITING_FOR_TRADING_NODE",
        "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": {
            "version": preflight.get("model_version", "behavioral-distillation-v2-cross-asset-deploy"),
            "fidelity": "BEHAVIORAL_APPROXIMATION",
            "online_training": False,
        },
        "preflight": {
            "status": preflight.get("status", "NOT_RECEIVED"),
            "instrument_count": preflight.get("instrument_count", 0),
            "equity_available": preflight.get("equity_available", False),
            "reconciliation_ok": preflight.get("reconciliation_ok", False),
            "order_submission_performed": False,
        },
        "mapping": {
            "allowed_count": mapping.get("allowed_count", 0),
            "monitor_only_count": mapping.get("monitor_only_count", 0),
            "blocked_count": mapping.get("blocked_count", 0),
            "unavailable_count": mapping.get("unavailable_count", 0),
            "symbols": [
                {
                    "symbol": row.get("symbol", ""),
                    "venue_symbol": row.get("bybit_symbol", ""),
                    "status": row.get("status", "UNKNOWN"),
                }
                for row in mapping_rows[:100]
                if isinstance(row, dict)
            ],
        },
        "runtime": {
            "status": runtime.get("status", "NOT_RUNNING"),
            "selected_symbols": runtime.get("selected_symbols", []),
            "submitted_orders": [],
            "websocket_connected": runtime.get("websocket_connected", False),
        },
        "operator_note": (
            "美国服务器只托管这个只读面板。交易引擎必须运行在可访问目标交易所的本地或非美国节点。"
        ),
    }


class DashboardHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(FRONTEND_ROOT), **kwargs)

    def do_GET(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0] == "/api/status":
            body = json.dumps(status_payload(), ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        super().do_GET()

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[dashboard] {self.address_string()} - {format % args}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the read-only operator dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    print(f"dashboard listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
