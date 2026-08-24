from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Mapping


@dataclass(frozen=True)
class TestnetRiskDecision:
    allowed: bool
    reasons: tuple[str, ...]


def portfolio_target_scale(total_target_exposure: Decimal, total_limit: Decimal) -> Decimal:
    """Return a proportional scale that fits a portfolio inside its cap."""

    if total_target_exposure <= 0 or total_limit <= 0:
        return Decimal("0")
    return min(Decimal("1"), total_limit / total_target_exposure)


def risk_envelope_for_symbol(envelope: Mapping[str, Any], symbol: str) -> Decimal:
    item = dict(envelope.get("per_symbol_target_exposure", {})).get(symbol, {})
    return Decimal(str(item.get("p99_abs_target_exposure", "0")))


def check_testnet_order(
    *,
    enable_orders: bool,
    confirm_testnet: bool,
    symbol: str,
    target_exposure: Decimal,
    total_target_exposure: Decimal,
    envelope: Mapping[str, Any],
    reconciliation_ok: bool,
    websocket_connected: bool,
    market_fresh: bool,
    clock_drift_seconds: Decimal,
    max_clock_drift_seconds: Decimal = Decimal("5"),
    consecutive_rejects: int = 0,
    max_consecutive_rejects: int = 3,
    drawdown: Decimal = Decimal("0"),
    max_drawdown: Decimal = Decimal("0"),
) -> TestnetRiskDecision:
    reasons: list[str] = []
    if not enable_orders:
        reasons.append("ORDERS_DISABLED")
    if not confirm_testnet:
        reasons.append("TESTNET_CONFIRMATION_REQUIRED")
    symbol_limit = risk_envelope_for_symbol(envelope, symbol)
    if symbol_limit <= 0:
        reasons.append("SYMBOL_NOT_IN_DEPLOYMENT_ENVELOPE")
    elif abs(target_exposure) > symbol_limit:
        reasons.append("HISTORICAL_SYMBOL_P99_EXCEEDED")
    total_limit = Decimal(str(envelope.get("historical_simultaneous_total_exposure_cap", "0")))
    if total_limit <= 0 or abs(total_target_exposure) > total_limit:
        reasons.append("HISTORICAL_TOTAL_EXPOSURE_EXCEEDED")
    if not reconciliation_ok:
        reasons.append("RECONCILIATION_NOT_OK")
    if not websocket_connected:
        reasons.append("WEBSOCKET_NOT_CONNECTED")
    if not market_fresh:
        reasons.append("MARKET_DATA_STALE")
    if abs(clock_drift_seconds) > max_clock_drift_seconds:
        reasons.append("CLOCK_DRIFT")
    if consecutive_rejects >= max_consecutive_rejects:
        reasons.append("CONSECUTIVE_REJECTS")
    if max_drawdown > 0 and drawdown >= max_drawdown:
        reasons.append("DRAWDOWN_LIMIT")
    return TestnetRiskDecision(not reasons, tuple(reasons))


__all__ = ["TestnetRiskDecision", "check_testnet_order", "portfolio_target_scale", "risk_envelope_for_symbol"]
