from __future__ import annotations

from dataclasses import dataclass

from quant_bot.domain.risk import RiskState


@dataclass(frozen=True)
class HealthSnapshot:
    status: str
    reasons: tuple[str, ...]


def evaluate_health(state: RiskState) -> HealthSnapshot:
    reasons: list[str] = []
    if state.stale_market_data:
        reasons.append("STALE_MARKET_DATA")
    if not state.reconciliation_ok:
        reasons.append("RECONCILIATION_NOT_OK")
    if not state.websocket_connected:
        reasons.append("WEBSOCKET_NOT_CONNECTED")
    if state.kill_switch_engaged:
        reasons.append("KILL_SWITCH_ENGAGED")
    return HealthSnapshot("BLOCKED" if reasons else "READY", tuple(reasons))
