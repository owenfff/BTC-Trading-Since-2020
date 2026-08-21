from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quant_bot.domain.risk import RiskConfig, RiskDecision, RiskState


@dataclass(frozen=True)
class RiskCheck:
    decision: RiskDecision
    reasons: tuple[str, ...]


def pre_trade_check(config: RiskConfig, state: RiskState, order_notional: Decimal, symbol_exposure: Decimal, total_exposure: Decimal) -> RiskCheck:
    reasons: list[str] = []
    if not config.live_enabled:
        reasons.append("LIVE_DISABLED")
    if config.maximum_live_risk <= 0 or config.maximum_live_notional <= 0:
        reasons.append("LIVE_LIMIT_ZERO")
    if state.kill_switch_engaged:
        reasons.append("KILL_SWITCH_ENGAGED")
    if state.circuit_breaker_open:
        reasons.append("CIRCUIT_BREAKER_OPEN")
    if state.stale_market_data:
        reasons.append("STALE_MARKET_DATA")
    if not state.reconciliation_ok:
        reasons.append("RECONCILIATION_NOT_OK")
    if not state.websocket_connected:
        reasons.append("WEBSOCKET_NOT_CONNECTED")
    if order_notional > config.max_order_notional:
        reasons.append("MAX_ORDER_NOTIONAL")
    if abs(symbol_exposure) > config.max_symbol_exposure:
        reasons.append("MAX_SYMBOL_EXPOSURE")
    if abs(total_exposure) > config.max_total_exposure:
        reasons.append("MAX_TOTAL_EXPOSURE")
    return RiskCheck(RiskDecision.BLOCK if reasons else RiskDecision.ALLOW, tuple(reasons))
