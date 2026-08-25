#!/usr/bin/env python3
"""Read-only operator dashboard server.

This process never imports an exchange adapter and never reads exchange
credentials. It serves the dashboard plus sanitized local runtime artifacts.
"""

from __future__ import annotations

import argparse
import json
import os
import signal
import subprocess
import sys
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any


FRONTEND_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = FRONTEND_ROOT.parent
CONTROL_ENABLED = False
CONTROL_HOST = "127.0.0.1"
CONTROL_LOCK = threading.RLock()
CONTROL_PROCESS: subprocess.Popen[Any] | None = None
CONTROL_META: dict[str, Any] = {}

CONTROL_LAUNCHERS = {
    "okx-demo": "start-okx-demo.ps1",
    "binance-spot-testnet": "start-binance-testnet.ps1",
    "binance-futures-testnet": "start-binance-futures-testnet.ps1",
}


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
    "binance-futures-testnet": ("Binance USDⓈ-M Futures Testnet", "binance_futures_testnet_preflight.json", "binance_futures_testnet_runtime_state.json", "binance_futures_testnet_symbol_mapping.json"),
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
            "美国服务器可只托管这个只读面板；交易引擎和本机控制面板可运行在上海等能访问目标交易所的节点。"
        ),
        "control": control_payload(),
    }


def control_payload() -> dict[str, Any]:
    """Expose only local controller state; never expose command credentials."""

    with CONTROL_LOCK:
        process = CONTROL_PROCESS
        running = bool(process is not None and process.poll() is None)
        return {
            "enabled": CONTROL_ENABLED,
            "local_only": CONTROL_ENABLED and CONTROL_HOST in {"127.0.0.1", "localhost", "::1"},
            "running": running,
            "pid": process.pid if running and process is not None else None,
            "venue": CONTROL_META.get("venue") if running else None,
            "mode": CONTROL_META.get("mode") if running else None,
            "exit_code": None if running or process is None else process.poll(),
            "credentials_in_browser": False,
        }


def _json_error(message: str, status: int = 400) -> tuple[int, dict[str, Any]]:
    return status, {"status": "BLOCKED", "error": message, "control": control_payload()}


def _control_command(venue: str, mode: str, confirm: bool) -> tuple[list[str], dict[str, Any]]:
    """Build a credential-free local command for Windows or Linux nodes."""

    if os.name == "nt":
        launcher = PROJECT_ROOT / "deploy" / CONTROL_LAUNCHERS[venue]
        launcher_mode = "demo" if venue == "okx-demo" and mode == "testnet" else mode
        arguments = ["-NoLogo", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher), "-Mode", launcher_mode]
        if mode == "testnet":
            arguments.append("-ConfirmTestnet")
        if venue == "binance-spot-testnet":
            arguments.append("-AllowSpotApproximation")
        flags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        return ["powershell.exe", *arguments], {"creationflags": flags}

    command = [sys.executable, "-m", "quant_bot", "run", "--venue", venue, "--mode", "testnet", "--symbols", "auto", "--poll-seconds", "60"]
    if venue == "binance-spot-testnet":
        command.append("--allow-spot-approximation")
    if mode == "testnet":
        command.extend(("--enable-orders", "--confirm-testnet"))
    return command, {"start_new_session": True}


def start_control(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Start exactly one local launcher without accepting credentials."""

    global CONTROL_PROCESS, CONTROL_META
    if not CONTROL_ENABLED or CONTROL_HOST not in {"127.0.0.1", "localhost", "::1"}:
        return _json_error("LOCAL_CONTROL_DISABLED", 403)
    if not isinstance(payload, dict):
        return _json_error("JSON_OBJECT_REQUIRED")
    if any(key.lower() in {"api_key", "api_secret", "secret", "passphrase", "password", "key"} for key in payload):
        return _json_error("CREDENTIALS_MUST_NOT_BE_SENT_TO_DASHBOARD")
    venue = str(payload.get("venue", "")).strip().lower()
    mode = str(payload.get("mode", "readonly")).strip().lower()
    confirm = payload.get("confirm_testnet") is True
    if venue not in CONTROL_LAUNCHERS:
        return _json_error("UNSUPPORTED_SINGLE_VENUE")
    if mode not in {"readonly", "testnet"}:
        return _json_error("MODE_MUST_BE_READONLY_OR_TESTNET")
    if mode == "testnet" and not confirm:
        return _json_error("TESTNET_CONFIRMATION_REQUIRED")
    with CONTROL_LOCK:
        if CONTROL_PROCESS is not None and CONTROL_PROCESS.poll() is None:
            return _json_error("LOCAL_VENUE_ALREADY_RUNNING", 409)
        launcher = PROJECT_ROOT / "deploy" / CONTROL_LAUNCHERS[venue]
        if os.name == "nt" and not launcher.exists():
            return _json_error("LAUNCHER_NOT_FOUND", 500)
        command, popen_options = _control_command(venue, mode, confirm)
        try:
            CONTROL_PROCESS = subprocess.Popen(
                command,
                cwd=str(PROJECT_ROOT),
                **popen_options,
            )
        except OSError as error:
            CONTROL_PROCESS = None
            return _json_error(f"LOCAL_LAUNCH_FAILED:{type(error).__name__}", 500)
        CONTROL_META = {"venue": venue, "mode": mode}
    return 202, {"status": "STARTING_LOCAL", "control": control_payload()}


def stop_control() -> tuple[int, dict[str, Any]]:
    global CONTROL_PROCESS, CONTROL_META
    if not CONTROL_ENABLED or CONTROL_HOST not in {"127.0.0.1", "localhost", "::1"}:
        return _json_error("LOCAL_CONTROL_DISABLED", 403)
    with CONTROL_LOCK:
        process = CONTROL_PROCESS
        if process is None or process.poll() is not None:
            return _json_error("NO_LOCAL_VENUE_RUNNING", 409)
        try:
            if hasattr(signal, "CTRL_BREAK_EVENT"):
                process.send_signal(signal.CTRL_BREAK_EVENT)
            else:
                process.terminate()
        except OSError:
            process.terminate()
        CONTROL_META = {}
    return 202, {"status": "STOP_REQUESTED", "control": control_payload()}


def _stop_control_at_exit() -> None:
    if CONTROL_ENABLED:
        try:
            stop_control()
        except Exception:  # noqa: BLE001 - process shutdown must not mask exit
            pass


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

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path not in {"/api/control/start", "/api/control/stop"}:
            self.send_error(404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            status, response = _json_error("INVALID_JSON")
        else:
            status, response = start_control(payload) if path.endswith("/start") else stop_control()
        body = json.dumps(response, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format: str, *args: Any) -> None:
        print(f"[dashboard] {self.address_string()} - {format % args}", flush=True)


def main() -> None:
    global CONTROL_ENABLED, CONTROL_HOST
    parser = argparse.ArgumentParser(description="Serve the read-only operator dashboard")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--control", action="store_true", help="enable local-only start/stop controls; credentials are entered by the launcher, never by the browser")
    args = parser.parse_args()
    CONTROL_HOST = str(args.host).lower()
    if args.control and CONTROL_HOST not in {"127.0.0.1", "localhost", "::1"}:
        parser.error("--control is allowed only on a loopback host")
    CONTROL_ENABLED = bool(args.control)
    if CONTROL_ENABLED:
        import atexit

        atexit.register(_stop_control_at_exit)
    server = ThreadingHTTPServer((args.host, args.port), DashboardHandler)
    suffix = " with LOCAL CONTROL" if CONTROL_ENABLED else ""
    print(f"dashboard listening on http://{args.host}:{args.port}{suffix}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
