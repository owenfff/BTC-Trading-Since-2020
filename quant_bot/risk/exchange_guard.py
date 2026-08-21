from __future__ import annotations


def exchange_state_is_safe(*, websocket_connected: bool, reconciliation_ok: bool) -> bool:
    return bool(websocket_connected and reconciliation_ok)
