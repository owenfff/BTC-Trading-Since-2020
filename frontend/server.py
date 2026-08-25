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


def _account_payload(runtime: dict[str, Any], preflight: dict[str, Any]) -> dict[str, Any]:
    """Return only whitelisted account telemetry for the public read-only UI."""

    source = runtime.get("account") if isinstance(runtime.get("account"), dict) else None
    source_name = "RUNTIME" if source else "PREFLIGHT"
    if not source:
        source = preflight.get("account") if isinstance(preflight.get("account"), dict) else {}

    def rows(name: str) -> list[dict[str, Any]]:
        value = source.get(name, [])
        return [item for item in value[:100] if isinstance(item, dict)] if isinstance(value, list) else []

    return {
        "source": source_name if source else "NONE",
        "equity": source.get("equity") if source else None,
        "equity_unit": source.get("equity_unit", "USD_EQUIVALENT") if source else "USD_EQUIVALENT",
        "captured_at_utc": source.get("captured_at_utc") if source else None,
        "reconciliation_ok": bool(source.get("reconciliation_ok")) if source else False,
        "balances": rows("balances"),
        "positions": rows("positions"),
        "open_orders": rows("open_orders"),
        "recent_fills": rows("recent_fills"),
    }


VENUE_FILES = {
    "bybit-demo": ("Bybit Demo", "bybit_demo_preflight.json", "bybit_demo_runtime_state.json", "bybit_demo_symbol_mapping.json"),
    "okx-demo": ("OKX Demo", "okx_demo_preflight.json", "okx_demo_runtime_state.json", "okx_demo_symbol_mapping.json"),
    "binance-spot-testnet": ("Binance Spot Testnet", "binance_spot_testnet_preflight.json", "binance_spot_testnet_runtime_state.json", "binance_spot_testnet_symbol_mapping.json"),
}


def _venue_payload(name: str, label: str, preflight: dict[str, Any], runtime: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    account = _account_payload(runtime, preflight)
    has_feed = bool(preflight or runtime or mapping)
    return {
        "venue": name,
        "label": label,
        "feed_status": "CONNECTED" if has_feed else "WAITING",
        "preflight_status": preflight.get("status", "NOT_RECEIVED"),
        "runtime_status": runtime.get("status", "NOT_RUNNING"),
        "market_connection": runtime.get("market_connection", "NONE"),
        "market_connected": runtime.get("market_connected", runtime.get("websocket_connected", False)),
        "private_stream_seen": runtime.get("private_stream_seen", runtime.get("websocket_connected", False)),
        "order_submission_enabled": bool(runtime.get("order_submission_enabled", False)),
        "equity": account.get("equity"),
        "equity_unit": account.get("equity_unit"),
        "reconciliation_ok": account.get("reconciliation_ok", False),
        "plans": runtime.get("plans", 0),
        "submitted_orders": runtime.get("submitted", []),
        "open_order_count": len(account.get("open_orders", [])),
        "position_count": len(account.get("positions", [])),
        "fill_count": len(account.get("recent_fills", [])),
        "account": account,
        "mapping": {
            "allowed_count": mapping.get("allowed_count", 0),
            "monitor_only_count": mapping.get("monitor_only_count", 0),
            "blocked_count": mapping.get("blocked_count", 0),
            "unavailable_count": mapping.get("unavailable_count", 0),
        },
    }


def status_payload() -> dict[str, Any]:
    venue_states: list[dict[str, Any]] = []
    raw_states: dict[str, tuple[dict[str, Any], dict[str, Any], dict[str, Any]]] = {}
    for name, (label, preflight_name, runtime_name, mapping_name) in VENUE_FILES.items():
        preflight = _read_json(PROJECT_ROOT / "quant" / "outputs" / preflight_name)
        runtime = _read_json(PROJECT_ROOT / "quant" / "outputs" / runtime_name)
        mapping = _read_json(PROJECT_ROOT / "quant" / "reports" / mapping_name)
        raw_states[name] = (preflight, runtime, mapping)
        venue_states.append(_venue_payload(name, label, preflight, runtime, mapping))
    # Preserve the original single-venue dashboard fields by selecting the
    # first venue with a runtime/preflight feed, while exposing every venue in
    # the new `venues` collection.
    active_name = next((item["venue"] for item in venue_states if item["runtime_status"] not in {"NOT_RUNNING", ""} or item["preflight_status"] not in {"NOT_RECEIVED", ""}), "bybit-demo")
    preflight, runtime, mapping = raw_states[active_name]
    has_feed = bool(preflight or runtime or mapping)
    account = _account_payload(runtime, preflight)
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
                    "symbol": row.get("symbol", row.get("historical_symbol", "")),
                    "venue_symbol": row.get("bybit_symbol", row.get("venue_symbol", "")),
                    "status": row.get("status", "UNKNOWN"),
                }
                for row in mapping_rows[:100]
                if isinstance(row, dict)
            ],
        },
        "runtime": {
            "status": runtime.get("status", "NOT_RUNNING"),
            "selected_symbols": runtime.get("selected_symbols", []),
            "submitted_orders": runtime.get("submitted", []),
            "websocket_connected": runtime.get("websocket_connected", False),
            "market_connection": runtime.get("market_connection", "NONE"),
            "market_connected": runtime.get("market_connected", runtime.get("websocket_connected", False)),
            "private_stream_seen": runtime.get("private_stream_seen", runtime.get("websocket_connected", False)),
            "order_submission_enabled": runtime.get("order_submission_enabled", False),
            "plans": runtime.get("plans", 0),
            "portfolio_target_scale": runtime.get("portfolio_target_scale", "1"),
            "order_errors": runtime.get("order_errors", {}),
            "stop_reason": runtime.get("stop_reason"),
            "last_error": runtime.get("last_error"),
        },
        "account": account,
        "activity": {
            "position_count": len(account["positions"]),
            "open_order_count": len(account["open_orders"]),
            "recent_fill_count": len(account["recent_fills"]),
        },
        "active_venue": active_name,
        "venues": venue_states,
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
