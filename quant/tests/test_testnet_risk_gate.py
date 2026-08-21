from __future__ import annotations

from decimal import Decimal

from quant_bot.risk.testnet_gate import check_testnet_order


def envelope() -> dict[str, object]:
    return {"per_symbol_target_exposure": {"BTCUSDT": {"p99_abs_target_exposure": 0.25}}, "historical_simultaneous_total_exposure_cap": 0.5}


def test_testnet_gate_is_fail_closed_without_explicit_order_confirmation() -> None:
    decision = check_testnet_order(enable_orders=False, confirm_testnet=False, symbol="BTCUSDT", target_exposure=Decimal("0.1"), total_target_exposure=Decimal("0.1"), envelope=envelope(), reconciliation_ok=True, websocket_connected=True, market_fresh=True, clock_drift_seconds=Decimal("0"))
    assert not decision.allowed
    assert "ORDERS_DISABLED" in decision.reasons
    assert "TESTNET_CONFIRMATION_REQUIRED" in decision.reasons


def test_testnet_gate_allows_only_reconciled_fresh_within_historical_envelope() -> None:
    allowed = check_testnet_order(enable_orders=True, confirm_testnet=True, symbol="BTCUSDT", target_exposure=Decimal("0.1"), total_target_exposure=Decimal("0.1"), envelope=envelope(), reconciliation_ok=True, websocket_connected=True, market_fresh=True, clock_drift_seconds=Decimal("0"))
    assert allowed.allowed
    blocked = check_testnet_order(enable_orders=True, confirm_testnet=True, symbol="BTCUSDT", target_exposure=Decimal("0.3"), total_target_exposure=Decimal("0.3"), envelope=envelope(), reconciliation_ok=False, websocket_connected=False, market_fresh=False, clock_drift_seconds=Decimal("10"))
    assert not blocked.allowed
    assert {"HISTORICAL_SYMBOL_P99_EXCEEDED", "RECONCILIATION_NOT_OK", "WEBSOCKET_NOT_CONNECTED", "MARKET_DATA_STALE", "CLOCK_DRIFT"}.issubset(set(blocked.reasons))
