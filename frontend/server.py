#!/usr/bin/env python3
"""Operator dashboard server with loopback-only local control.

This process never imports an exchange adapter. The public/read-only surface
serves sanitized runtime artifacts; the optional loopback control surface may
write one selected Demo/Testnet credential set to a mode-600 local file and
pass it only to a local child process.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import signal
import shlex
import subprocess
import sys
import tempfile
import threading
from datetime import datetime, timezone
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlsplit


FRONTEND_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = FRONTEND_ROOT.parent
CONTROL_ENABLED = False
CONTROL_HOST = "127.0.0.1"
CONTROL_LOCK = threading.RLock()
CONTROL_PROCESS: subprocess.Popen[Any] | None = None
CONTROL_META: dict[str, Any] = {}
CONTROL_CREDENTIALS_PATH: Path | None = None
KILL_SWITCH_PATH = PROJECT_ROOT / "quant" / "outputs" / "okx_demo_kill_switch.json"
REPLAY_LOCK = threading.RLock()
REPLAY_CACHE: dict[str, dict[str, Any]] = {}

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


def _kill_switch_engaged() -> bool:
    return KILL_SWITCH_PATH.exists()


def _artifact_sha(path: Path) -> str | None:
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return None
    return digest


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


def _parse_time_ms(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp() * 1000)
    except (TypeError, ValueError, OverflowError):
        return None


RUNTIME_HEARTBEAT_MAX_AGE_SECONDS = 30


def _runtime_source_timestamp(runtime: dict[str, Any], account: dict[str, Any]) -> str | None:
    """Return the node's last write time, never the dashboard request time."""

    value = runtime.get("updated_at_utc")
    if value:
        return str(value)
    value = account.get("captured_at_utc")
    return str(value) if value else None


def _runtime_age_seconds(timestamp: str | None) -> float | None:
    parsed = _parse_time_ms(timestamp)
    if parsed is None:
        return None
    return (datetime.now(timezone.utc).timestamp() * 1000 - parsed) / 1000


def _runtime_is_live(runtime: dict[str, Any], account: dict[str, Any]) -> bool:
    status = str(runtime.get("status", "")).upper()
    age = _runtime_age_seconds(_runtime_source_timestamp(runtime, account))
    return status in {"RUNNING", "RUNNING_READ_ONLY"} and age is not None and 0 <= age <= RUNTIME_HEARTBEAT_MAX_AGE_SECONDS


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _downsample(rows: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    """Uniformly downsample a time-ordered series without losing its endpoints."""

    limit = max(2, min(limit, 1600))
    if len(rows) <= limit:
        return rows
    indexes = {round(index * (len(rows) - 1) / (limit - 1)) for index in range(limit)}
    return [rows[index] for index in sorted(indexes)]


def _read_replay_dataset(symbol: str, venue: str = "bitmex") -> dict[str, Any]:
    """Load a compact historical replay view from local, already-derived outputs.

    This intentionally reads no credentials and no exchange endpoint.  The panel
    labels the lower series as analytical realised PnL because it is derived from
    the repository's trade-cycle accounting, not from a live account equity curve.
    """

    output_root = PROJECT_ROOT / "quant" / "outputs"
    normalized_venue = venue.strip().lower()
    if normalized_venue in {"hyperliquid", "hl"}:
        compact_path = output_root / "replay_dashboard_hyperliquid_btc.json"
    else:
        compact_path = output_root / f"replay_dashboard_{symbol.lower()}.json"
    if compact_path.exists():
        compact = _read_json(compact_path)
        if isinstance(compact.get("bars"), list) and isinstance(compact.get("orders"), list) and isinstance(compact.get("pnl"), list):
            return {
                "symbol": symbol,
                "venue": compact.get("venue", normalized_venue.upper()),
                "bars": compact["bars"],
                "orders": compact["orders"],
                "pnl": compact["pnl"],
                "available": bool(compact.get("available", True)),
                "start_ts": compact.get("full_start_ts") or compact.get("start_ts"),
                "end_ts": compact.get("full_end_ts") or compact.get("end_ts"),
                "pnl_unit": compact.get("pnl_unit", "analytical realised PnL"),
                "source": compact.get("source", "local compact replay snapshot"),
                "source_repository": compact.get("source_repository"),
                "source_revision": compact.get("source_revision"),
                "indicator_policy": compact.get("indicator_policy", "causal closed-bar indicators"),
            }
    bars: list[dict[str, Any]] = []
    bars_path = output_root / "market_bars_1h.csv"
    if bars_path.exists():
        with bars_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("symbol") != symbol:
                    continue
                timestamp = _parse_time_ms(row.get("timestamp") or row.get("bar_end_time_utc"))
                close = _number(row.get("close"))
                if timestamp is None or close is None:
                    continue
                bars.append(
                    {
                        "ts": timestamp,
                        "open": _number(row.get("open")),
                        "high": _number(row.get("high")),
                        "low": _number(row.get("low")),
                        "close": close,
                        "volume": _number(row.get("volume")) or 0.0,
                    }
                )

    orders: list[dict[str, Any]] = []
    orders_path = output_root / "order_episodes.csv"
    if orders_path.exists():
        with orders_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("symbol") != symbol:
                    continue
                start_ts = _parse_time_ms(row.get("first_event_time"))
                end_ts = _parse_time_ms(row.get("last_event_time")) or start_ts
                if start_ts is None or end_ts is None:
                    continue
                filled = _number(row.get("filled_qty")) or 0.0
                leaves = _number(row.get("leavesQty_last"))
                orders.append(
                    {
                        "start_ts": start_ts,
                        "end_ts": end_ts,
                        "side": row.get("side") or "UNKNOWN",
                        "action": row.get("action") or "UNKNOWN",
                        "status": row.get("ordStatus") or "UNKNOWN",
                        "filled": filled,
                        "order_qty": _number(row.get("orderQty")) or 0.0,
                        "leaves": leaves,
                        "price": _number(row.get("limit_price")) or _number(row.get("weighted_execution_price")),
                        "position_before": _number(row.get("position_before")),
                        "position_after": _number(row.get("position_after")),
                        "order_id": row.get("orderID") or "",
                        "is_filled": (row.get("ordStatus") or "").lower() == "filled" or (leaves == 0 and filled > 0),
                    }
                )

    pnl: list[dict[str, Any]] = []
    pnl_total = 0.0
    pnl_currency = ""
    pnl_scale: int | None = None
    cycles_path = output_root / "trade_cycles.csv"
    if cycles_path.exists():
        cycle_rows: list[tuple[int, float]] = []
        with cycles_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            for row in csv.DictReader(handle):
                if row.get("symbol") != symbol:
                    continue
                pnl_currency = pnl_currency or (row.get("pnl_currency") or "")
                timestamp = _parse_time_ms(row.get("close_time")) or _parse_time_ms(row.get("open_time"))
                value = _number(row.get("gross_pnl_analytical"))
                if timestamp is not None and value is not None:
                    cycle_rows.append((timestamp, value))
        scale_path = PROJECT_ROOT / "quant" / "reports" / "currency_scale_coverage.csv"
        if scale_path.exists() and pnl_currency:
            with scale_path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
                for row in csv.DictReader(handle):
                    if row.get("currency") != pnl_currency:
                        continue
                    try:
                        pnl_scale = int(row.get("asset_scale", ""))
                    except ValueError:
                        pnl_scale = None
                    break
        display_scale = 10**pnl_scale if pnl_scale is not None else 1
        for timestamp, value in sorted(cycle_rows):
            pnl_total += value / display_scale
            pnl.append({"ts": timestamp, "value": pnl_total})

    bars.sort(key=lambda item: item["ts"])
    orders.sort(key=lambda item: (item["start_ts"], item["end_ts"], item["order_id"]))
    pnl.sort(key=lambda item: item["ts"])
    all_timestamps = [item["ts"] for item in bars]
    all_timestamps.extend(item["start_ts"] for item in orders)
    return {
        "symbol": symbol,
        "venue": normalized_venue.upper(),
        "bars": bars,
        "orders": orders,
        "pnl": pnl,
        "available": bool(bars or orders or pnl),
        "start_ts": min(all_timestamps) if all_timestamps else None,
        "end_ts": max(all_timestamps) if all_timestamps else None,
        "pnl_unit": (
            f"{pnl_currency} (scale {pnl_scale}) analytical realised PnL"
            if pnl_currency and pnl_scale is not None
            else "raw analytical realised PnL (scale unresolved)"
        ),
        "source": "local derived replay outputs",
        "indicator_policy": "causal closed-bar indicators",
    }


def _replay_dataset(symbol: str, venue: str = "bitmex") -> dict[str, Any]:
    cache_key = f"{venue.lower()}:{symbol.upper()}"
    with REPLAY_LOCK:
        # Keep compatibility with older tests/tools that keyed the original
        # BitMEX replay cache by symbol only.
        if venue.lower() == "bitmex" and symbol.upper() in REPLAY_CACHE:
            return REPLAY_CACHE[symbol.upper()]
        if cache_key not in REPLAY_CACHE:
            REPLAY_CACHE[cache_key] = _read_replay_dataset(symbol) if venue.lower() == "bitmex" else _read_replay_dataset(symbol, venue)
        return REPLAY_CACHE[cache_key]


def replay_payload(query: dict[str, list[str]]) -> dict[str, Any]:
    venue = (query.get("venue") or ["bitmex"])[0].strip().lower() or "bitmex"
    symbol_default = "HL-BTC-PERP" if venue in {"hyperliquid", "hl"} else "XBTUSD"
    symbol = (query.get("symbol") or [symbol_default])[0].strip().upper() or symbol_default
    dataset = _replay_dataset(symbol, venue)
    try:
        limit = int((query.get("limit") or ["900"])[0])
    except ValueError:
        limit = 900
    start = _number((query.get("start") or [""])[0])
    end = _number((query.get("end") or [""])[0])
    if start is None:
        start = dataset.get("start_ts")
    if end is None:
        end = dataset.get("end_ts")
    if start is None or end is None:
        return {
            "status": "WAITING",
            "venue": dataset.get("venue", venue.upper()),
            "symbol": symbol,
            "available": False,
            "bars": [],
            "orders": [],
            "pnl": [],
            "source": dataset.get("source"),
            "indicator_policy": dataset.get("indicator_policy"),
        }
    if start > end:
        start, end = end, start
    bars = [row for row in dataset["bars"] if start <= row["ts"] <= end]
    orders = [row for row in dataset["orders"] if row["end_ts"] >= start and row["start_ts"] <= end]
    pnl = [row for row in dataset["pnl"] if start <= row["ts"] <= end]
    return {
        "status": "READY" if dataset["available"] else "WAITING",
        "venue": dataset.get("venue", venue.upper()),
        "symbol": symbol,
        "available": dataset["available"],
        "start_ts": start,
        "end_ts": end,
        "full_start_ts": dataset.get("start_ts"),
        "full_end_ts": dataset.get("end_ts"),
        "bars": _downsample(bars, limit),
        "orders": _downsample(orders, min(limit, 700)),
        "pnl": _downsample(pnl, min(limit, 700)),
        "counts": {"bars": len(bars), "orders": len(orders), "pnl_points": len(pnl)},
        "pnl_unit": dataset["pnl_unit"],
        "source": dataset["source"],
        "source_repository": dataset.get("source_repository"),
        "source_revision": dataset.get("source_revision"),
        "indicator_policy": dataset.get("indicator_policy"),
    }


def _venue_payload(name: str, label: str, preflight: dict[str, Any], runtime: dict[str, Any], mapping: dict[str, Any]) -> dict[str, Any]:
    account = _account_payload(runtime, preflight)
    runtime_live = _runtime_is_live(runtime, account)
    runtime_age = _runtime_age_seconds(_runtime_source_timestamp(runtime, account))
    raw_runtime_status = str(runtime.get("status", "NOT_RUNNING"))
    effective_runtime_status = raw_runtime_status
    if raw_runtime_status.upper() in {"RUNNING", "RUNNING_READ_ONLY"} and not runtime_live:
        effective_runtime_status = "STALE"
    has_preflight = str(preflight.get("status", "")) == "PASS"
    market_live = bool(runtime_live and runtime.get("market_connected", runtime.get("websocket_connected", False)))
    return {
        "venue": name,
        "label": label,
        "feed_status": "CONNECTED" if market_live else "DEGRADED" if runtime_live else "READY" if has_preflight else "WAITING",
        "preflight_status": preflight.get("status", "NOT_RECEIVED"),
        "runtime_status": effective_runtime_status,
        "raw_runtime_status": raw_runtime_status,
        "runtime_live": runtime_live,
        "runtime_age_seconds": runtime_age,
        "last_source_update_utc": _runtime_source_timestamp(runtime, account),
        "market_connection": runtime.get("market_connection", "NONE") if runtime_live else "STALE",
        "market_connected": market_live,
        "private_stream_seen": bool(runtime_live and runtime.get("private_stream_seen", runtime.get("websocket_connected", False))),
        "order_submission_enabled": bool(runtime_live and runtime.get("order_submission_enabled", False)),
        "equity": account.get("equity"),
        "equity_unit": account.get("equity_unit"),
        "reconciliation_ok": account.get("reconciliation_ok", False),
        "plans": runtime.get("plans", 0),
        "submitted_orders": runtime.get("submitted", []),
        "open_order_count": len(account.get("open_orders", [])),
        "position_count": len(account.get("positions", [])),
        "fill_count": len(account.get("recent_fills", [])),
        "account": account,
        "risk": runtime.get("risk", {}),
        "clock_drift_seconds": runtime.get("clock_drift_seconds"),
        "latest_feedback_at": (runtime.get("behavior_state") or {}).get("latest_feedback_at"),
        "oldest_active_order_age_seconds": runtime.get("oldest_active_order_age_seconds"),
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
    # Prefer a genuinely live runtime.  A stale artifact must never win over
    # a current venue merely because its old status says RUNNING.
    active_name = next((item["venue"] for item in venue_states if item["runtime_live"]), None)
    if active_name is None:
        preferred_order = ("okx-demo", "binance-futures-testnet", "binance-spot-testnet", "bybit-demo")
        ready_names = {item["venue"] for item in venue_states if item["preflight_status"] == "PASS"}
        active_name = next((venue for venue in preferred_order if venue in ready_names), "okx-demo")
    preflight, runtime, mapping = raw_states[active_name]
    account = _account_payload(runtime, preflight)
    runtime_live = _runtime_is_live(runtime, account)
    source_timestamp = _runtime_source_timestamp(runtime, account)
    runtime_age = _runtime_age_seconds(source_timestamp)
    mapping_rows = mapping.get("symbols", []) if isinstance(mapping.get("symbols"), list) else []
    blocked_by_symbol = runtime.get("blocked", {}) if isinstance(runtime.get("blocked", {}), dict) else {}
    order_block_reasons = sorted({
        str(reason)
        for reasons in blocked_by_symbol.values()
        if isinstance(reasons, list)
        for reason in reasons
    })
    blocked_symbols = sorted(str(symbol) for symbol in blocked_by_symbol)
    deployment_path = PROJECT_ROOT / "quant" / "outputs" / "cross_asset_deployment_model_v3.json"
    if not deployment_path.exists():
        deployment_path = PROJECT_ROOT / "quant" / "outputs" / "cross_asset_deployment_model.json"
    deployment = _read_json(deployment_path)
    active_model_version = (
        runtime.get("model_version")
        or deployment.get("model_version")
        or preflight.get("model_version")
        or "behavioral-distillation-v2-cross-asset-deploy"
    )
    active_feature_contract = (
        runtime.get("feature_contract_version")
        or deployment.get("feature_contract_version")
        or preflight.get("feature_contract_version")
        or "m13-v2-cross-asset"
    )
    model_sha = runtime.get("model_sha256") or preflight.get("model_sha256") or deployment.get("model_sha256")
    if not model_sha:
        model_sha = _artifact_sha(deployment_path)
    return {
        "dashboard_role": "FRONTEND_ONLY",
        "exchange_connection": "NONE_FROM_THIS_SERVER",
        "trading_enabled_here": False,
        "feed_status": "CONNECTED" if runtime_live and runtime.get("market_connected", runtime.get("websocket_connected", False)) else "DEGRADED" if runtime_live else "READY" if preflight.get("status") == "PASS" else "WAITING_FOR_TRADING_NODE",
        "updated_at_utc": source_timestamp,
        "server_observed_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "model": {
            "version": active_model_version,
            "feature_contract_version": active_feature_contract,
            "fidelity": "BEHAVIORAL_APPROXIMATION",
            "online_training": False,
            "sha256": model_sha,
            "data_frozen_cutoff": deployment.get("frozen_cutoff"),
            "training_data_sha256": deployment.get("training_data_sha256"),
            "code_commit": deployment.get("code_commit"),
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
            "status": "STALE" if str(runtime.get("status", "")).upper() in {"RUNNING", "RUNNING_READ_ONLY"} and not runtime_live else runtime.get("status", "NOT_RUNNING"),
            "raw_status": runtime.get("status", "NOT_RUNNING"),
            "live": runtime_live,
            "age_seconds": runtime_age,
            "updated_at_utc": source_timestamp,
            "selected_symbols": runtime.get("selected_symbols", []),
            "submitted_orders": runtime.get("submitted", []),
            "websocket_connected": bool(runtime_live and runtime.get("websocket_connected", False)),
            "market_connection": runtime.get("market_connection", "NONE"),
            "market_connected": bool(runtime_live and runtime.get("market_connected", runtime.get("websocket_connected", False))),
            "private_stream_seen": bool(runtime_live and runtime.get("private_stream_seen", runtime.get("websocket_connected", False))),
            "order_submission_enabled": bool(runtime_live and runtime.get("order_submission_enabled", False) and not order_block_reasons),
            "risk_configuration_verified": runtime.get("risk_configuration_verified"),
            "plans": runtime.get("plans", 0),
            "portfolio_target_scale": runtime.get("portfolio_target_scale", "1"),
            "order_errors": runtime.get("order_errors", {}),
            "stop_reason": runtime.get("stop_reason"),
            "last_error": runtime.get("last_error"),
            "risk": runtime.get("risk", {}),
            "order_block_reasons": order_block_reasons,
            "blocked_symbols": blocked_symbols,
            "clock_drift_seconds": runtime.get("clock_drift_seconds"),
            "market_context": runtime.get("market_context", {}),
            "signals": runtime.get("signals", {}),
            "latest_feedback_at": (runtime.get("behavior_state") or {}).get("latest_feedback_at"),
            "oldest_active_order_age_seconds": runtime.get("oldest_active_order_age_seconds"),
            "behavior_state": {symbol: {key: value for key, value in state.items() if key in {"latest_action", "add_count", "reduce_count", "flip_count", "latest_decision", "latest_market_context_status"}} for symbol, state in dict((runtime.get("behavior_state") or {}).get("engine_state", {})).items()},
        },
        "account": account,
        "activity": {
            "position_count": len(account["positions"]),
            "open_order_count": len(account["open_orders"]),
            "recent_fill_count": len(account["recent_fills"]),
        },
        "historical_replay": {
            "available": (PROJECT_ROOT / "quant" / "outputs" / "market_bars_1h.csv").exists(),
            "symbols": ["XBTUSD"],
            "layers": ["market_and_orders", "position", "analytical_realised_pnl"],
            "source": "local derived replay outputs",
        },
        "active_venue": active_name,
        "venues": venue_states,
        "operator_note": (
            "美国服务器可只托管这个只读面板；交易引擎和本机控制面板可运行在上海等能访问目标交易所的节点。"
        ),
            "control": control_payload(),
    }


def control_payload() -> dict[str, Any]:
    """Expose only local controller state; never expose credential values."""

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
            "credential_setup_available": _file_credentials_supported(),
            "credential_status": _credential_status(CONTROL_META.get("venue") or "okx-demo"),
            "credential_statuses": {venue: _credential_status(venue) for venue in CREDENTIAL_NAMES},
            "kill_switch_engaged": _kill_switch_engaged(),
        }


def _json_error(message: str, status: int = 400) -> tuple[int, dict[str, Any]]:
    return status, {"status": "BLOCKED", "error": message, "control": control_payload()}


CREDENTIAL_NAMES = {
    "okx-demo": ("OKX_DEMO_API_KEY", "OKX_DEMO_API_SECRET", "OKX_DEMO_API_PASSPHRASE"),
    "binance-spot-testnet": ("BINANCE_TESTNET_API_KEY", "BINANCE_TESTNET_API_SECRET"),
    "binance-futures-testnet": ("BINANCE_FUTURES_TESTNET_API_KEY", "BINANCE_FUTURES_TESTNET_API_SECRET"),
}


def _file_credentials_supported() -> bool:
    return os.name != "nt"


def _credential_file_path() -> Path:
    if CONTROL_CREDENTIALS_PATH is not None:
        return CONTROL_CREDENTIALS_PATH
    config_home = os.environ.get("XDG_CONFIG_HOME")
    if config_home:
        return Path(config_home) / "quant-bot" / "credentials.env"
    return Path.home() / ".config" / "quant-bot" / "credentials.env"


def _parse_credential_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError, UnicodeDecodeError):
        return values
    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        name, raw = stripped.split("=", 1)
        name = name.strip()
        if name not in {item for group in CREDENTIAL_NAMES.values() for item in group}:
            continue
        try:
            parsed = shlex.split(raw, posix=True)
        except ValueError:
            parsed = []
        values[name] = parsed[0] if parsed else raw.strip().strip("\"'")
    return values


def _credential_status(venue: str) -> str:
    if not _file_credentials_supported() or not CONTROL_ENABLED or CONTROL_HOST not in {"127.0.0.1", "localhost", "::1"}:
        return "UNAVAILABLE"
    names = CREDENTIAL_NAMES.get(venue, ())
    values = _parse_credential_file(_credential_file_path())
    return "CONFIGURED" if names and all(values.get(name) for name in names) else "NOT_CONFIGURED"


def _load_credentials_for_venue(venue: str) -> dict[str, str]:
    """Load only the selected venue's local credentials into a child environment."""

    names = CREDENTIAL_NAMES.get(venue, ())
    values = _parse_credential_file(_credential_file_path())
    if not names or not all(values.get(name) for name in names):
        return {}
    return {name: values[name] for name in names}


def _credential_value(payload: dict[str, Any], name: str, *, required: bool = True) -> str | None:
    value = payload.get(name)
    if value is None and not required:
        return None
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError(f"{name}_INVALID")
    if any(character in value for character in ("\x00", "\r", "\n")):
        raise ValueError(f"{name}_INVALID")
    try:
        value.encode("ascii")
    except UnicodeEncodeError as error:
        raise ValueError(f"{name}_MUST_BE_ASCII") from error
    return value


def configure_credentials(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Save one selected venue's credentials locally, never returning values."""

    if not _file_credentials_supported():
        return _json_error("WINDOWS_USE_DPAPI_LAUNCHER")
    if not CONTROL_ENABLED or CONTROL_HOST not in {"127.0.0.1", "localhost", "::1"}:
        return _json_error("LOCAL_CONTROL_DISABLED", 403)
    if not isinstance(payload, dict):
        return _json_error("JSON_OBJECT_REQUIRED")
    venue = str(payload.get("venue", "")).strip().lower()
    if venue not in CREDENTIAL_NAMES:
        return _json_error("UNSUPPORTED_CREDENTIAL_VENUE")
    allowed = {"venue", "api_key", "api_secret", "passphrase"}
    if set(payload) - allowed:
        return _json_error("UNSUPPORTED_CREDENTIAL_FIELDS")
    try:
        api_key = _credential_value(payload, "api_key")
        api_secret = _credential_value(payload, "api_secret")
        passphrase = _credential_value(payload, "passphrase", required=venue == "okx-demo")
    except ValueError as error:
        return _json_error(str(error))

    selected = {
        "okx-demo": {
            "OKX_DEMO_API_KEY": api_key,
            "OKX_DEMO_API_SECRET": api_secret,
            "OKX_DEMO_API_PASSPHRASE": passphrase,
        },
        "binance-spot-testnet": {
            "BINANCE_TESTNET_API_KEY": api_key,
            "BINANCE_TESTNET_API_SECRET": api_secret,
        },
        "binance-futures-testnet": {
            "BINANCE_FUTURES_TESTNET_API_KEY": api_key,
            "BINANCE_FUTURES_TESTNET_API_SECRET": api_secret,
        },
    }[venue]
    path = _credential_file_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        os.chmod(path.parent, 0o700)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix="credentials.", delete=False) as handle:
            temporary_path = Path(handle.name)
            handle.write("# Local Demo/Testnet credentials only. Never commit or paste this file.\n")
            for name in CREDENTIAL_NAMES[venue]:
                handle.write(f"{name}={shlex.quote(selected[name] or '')}\n")
        os.chmod(temporary_path, 0o600)
        temporary_path.replace(path)
    except OSError:
        try:
            temporary_path.unlink(missing_ok=True)
        except UnboundLocalError:
            pass
        return _json_error("CREDENTIAL_FILE_WRITE_FAILED", 500)
    return 200, {"status": "CREDENTIALS_SAVED", "venue": venue, "credential_status": "CONFIGURED", "control": control_payload()}


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

    command = [sys.executable, "-m", "quant_bot", "supervise", "--venue", venue, "--mode", "testnet", "--symbols", "auto", "--poll-seconds", "60"]
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
    if _kill_switch_engaged():
        return _json_error("MANUAL_KILL_SWITCH_ENGAGED", 409)
    if _file_credentials_supported() and mode == "testnet" and _credential_status(venue) != "CONFIGURED":
        return _json_error("LOCAL_CREDENTIALS_REQUIRED")
    with CONTROL_LOCK:
        if CONTROL_PROCESS is not None and CONTROL_PROCESS.poll() is None:
            return _json_error("LOCAL_VENUE_ALREADY_RUNNING", 409)
        launcher = PROJECT_ROOT / "deploy" / CONTROL_LAUNCHERS[venue]
        if os.name == "nt" and not launcher.exists():
            return _json_error("LAUNCHER_NOT_FOUND", 500)
        command, popen_options = _control_command(venue, mode, confirm)
        if os.name != "nt":
            child_environment = os.environ.copy()
            child_environment.update(_load_credentials_for_venue(venue))
            popen_options["env"] = child_environment
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


def preflight_control(payload: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Run a credential-gated, order-free private venue preflight locally."""

    if not CONTROL_ENABLED or CONTROL_HOST not in {"127.0.0.1", "localhost", "::1"}:
        return _json_error("LOCAL_CONTROL_DISABLED", 403)
    if not isinstance(payload, dict):
        return _json_error("JSON_OBJECT_REQUIRED")
    if any(key.lower() in {"api_key", "api_secret", "secret", "passphrase", "password", "key"} for key in payload):
        return _json_error("CREDENTIALS_MUST_NOT_BE_SENT_TO_DASHBOARD")
    venue = str(payload.get("venue", "")).strip().lower()
    if venue not in CONTROL_LAUNCHERS:
        return _json_error("UNSUPPORTED_SINGLE_VENUE")
    if _file_credentials_supported() and _credential_status(venue) != "CONFIGURED":
        return _json_error("LOCAL_CREDENTIALS_REQUIRED")

    command = [sys.executable, "-m", "quant_bot", "preflight", "--venue", venue]
    child_environment = os.environ.copy()
    if _file_credentials_supported():
        child_environment.update(_load_credentials_for_venue(venue))
    try:
        completed = subprocess.run(
            command,
            cwd=str(PROJECT_ROOT),
            env=child_environment,
            capture_output=True,
            text=True,
            timeout=180,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        return _json_error(f"PREFLIGHT_LAUNCH_FAILED:{type(error).__name__}", 502)

    result: dict[str, Any] = {}
    for line in reversed(completed.stdout.splitlines()):
        try:
            candidate = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(candidate, dict):
            result = candidate
            break
    if completed.returncode != 0 or result.get("status") != "PASS":
        code = str(result.get("error_code") or "PREFLIGHT_FAILED")
        message = str(result.get("message") or result.get("error") or "private preflight failed")[:240]
        return 502, {"status": "BLOCKED", "error_code": code, "message": message, "control": control_payload()}

    return 200, {
        "status": "PREFLIGHT_PASS",
        "venue": venue,
        "instrument_count": result.get("instrument_count", 0),
        "reconciliation_ok": bool(result.get("reconciliation_ok")),
        "equity_unit": result.get("equity_unit"),
        "orders_submitted": bool(result.get("orders_submitted", False)),
        "control": control_payload(),
    }


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


def engage_kill_switch() -> tuple[int, dict[str, Any]]:
    if not CONTROL_ENABLED or CONTROL_HOST not in {"127.0.0.1", "localhost", "::1"}:
        return _json_error("LOCAL_CONTROL_DISABLED", 403)
    try:
        KILL_SWITCH_PATH.parent.mkdir(parents=True, exist_ok=True)
        KILL_SWITCH_PATH.write_text(json.dumps({"engaged": True, "engaged_at": datetime.now(timezone.utc).isoformat()}, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        return _json_error("KILL_SWITCH_WRITE_FAILED", 500)
    with CONTROL_LOCK:
        running = CONTROL_PROCESS is not None and CONTROL_PROCESS.poll() is None
    if running:
        stop_control()
    return 202, {"status": "KILL_SWITCH_ENGAGED", "positions_preserved": True, "control": control_payload()}


def clear_kill_switch() -> tuple[int, dict[str, Any]]:
    if not CONTROL_ENABLED or CONTROL_HOST not in {"127.0.0.1", "localhost", "::1"}:
        return _json_error("LOCAL_CONTROL_DISABLED", 403)
    try:
        KILL_SWITCH_PATH.unlink(missing_ok=True)
    except OSError:
        return _json_error("KILL_SWITCH_CLEAR_FAILED", 500)
    return 200, {"status": "KILL_SWITCH_CLEARED", "control": control_payload()}


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
        path = urlsplit(self.path)
        if path.path == "/api/status":
            response_payload = status_payload()
        elif path.path == "/api/replay":
            response_payload = replay_payload(parse_qs(path.query))
        else:
            super().do_GET()
            return
        if response_payload is not None:
            body = json.dumps(response_payload, ensure_ascii=False).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path not in {"/api/control/start", "/api/control/stop", "/api/control/preflight", "/api/control/credentials", "/api/control/kill-switch", "/api/control/kill-switch/clear"}:
            self.send_error(404)
            return
        if path.startswith("/api/control/kill-switch") and self.headers.get("X-Local-Control") != "1":
            status, response = _json_error("LOCAL_CONTROL_HEADER_REQUIRED", 403)
            body = json.dumps(response, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length > 8192:
                raise ValueError("REQUEST_TOO_LARGE")
            raw = self.rfile.read(length) if length else b"{}"
            payload = json.loads(raw.decode("utf-8"))
        except (ValueError, UnicodeDecodeError, json.JSONDecodeError):
            status, response = _json_error("INVALID_JSON")
        else:
            if path.endswith("/start"):
                status, response = start_control(payload)
            elif path.endswith("/stop"):
                status, response = stop_control()
            elif path.endswith("/preflight"):
                status, response = preflight_control(payload)
            elif path.endswith("/kill-switch/clear"):
                status, response = clear_kill_switch()
            elif path.endswith("/kill-switch"):
                status, response = engage_kill_switch()
            else:
                status, response = configure_credentials(payload)
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
    parser.add_argument("--control", action="store_true", help="enable loopback-only controls and local Demo/Testnet credential setup")
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
