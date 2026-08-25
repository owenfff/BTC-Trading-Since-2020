from __future__ import annotations

from typing import Any

from .exchanges.binance import BinanceSpotAdapter
from .exchanges.http import AdapterError
from .exchanges.okx import OKXAdapter
from .strategy.deployment import load_deployment_bundle
from .venue_runtime import DEFAULT_ARTIFACT, build_venue_symbol_mapping


def preflight_venue(venue: str, *, artifact_path: str | None = None) -> dict[str, Any]:
    key = venue.strip().lower()
    if key == "okx-demo":
        adapter = OKXAdapter.from_environment()
    elif key == "binance-spot-testnet":
        adapter = BinanceSpotAdapter.from_environment()
    else:
        raise AdapterError(key, "UNSUPPORTED_VENUE", f"unsupported venue: {venue}")
    instruments = adapter.load_all_instruments()
    if not instruments:
        raise AdapterError(adapter.name, "NO_INSTRUMENTS", "venue returned no tradable instruments")
    server_time = adapter.get_server_time()
    state = adapter.reconcile_state()
    equity = adapter.fetch_equity()
    if equity <= 0:
        raise AdapterError(adapter.name, "EQUITY_UNRESOLVED", "venue returned non-positive quote equity")
    bundle = load_deployment_bundle(artifact_path or DEFAULT_ARTIFACT)
    mapping = build_venue_symbol_mapping(bundle, adapter.name, instruments)
    return {
        "status": "PASS",
        "venue": adapter.name,
        "instrument_count": len(instruments),
        "mapping": mapping,
        "server_time": server_time.isoformat(),
        "reconciliation_ok": bool(state.get("ok")),
        "equity": str(equity),
        "equity_unit": "USDT_EQUIVALENT" if adapter.name == "binance-spot-testnet" else "USD_EQUIVALENT",
        "balances": [{"currency": item.currency, "total": str(item.total), "available": str(item.available)} for item in state.get("balances", [])],
        "positions": len(state.get("positions", [])),
        "open_orders": len(state.get("open_orders", [])),
        "recent_fills": len(state.get("recent_fills", [])),
        "orders_submitted": False,
        "credentials": "READ_FROM_LOCAL_ENVIRONMENT_ONLY",
    }


__all__ = ["preflight_venue"]
