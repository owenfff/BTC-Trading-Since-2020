from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from enum import StrEnum


class RiskDecision(StrEnum):
    ALLOW = "ALLOW"
    BLOCK = "BLOCK"


@dataclass(frozen=True)
class RiskConfig:
    live_enabled: bool = False
    maximum_live_risk: Decimal = Decimal("0")
    maximum_live_notional: Decimal = Decimal("0")
    max_order_notional: Decimal = Decimal("0")
    max_symbol_exposure: Decimal = Decimal("0")
    max_total_exposure: Decimal = Decimal("0")
    max_leverage: Decimal = Decimal("0")
    max_daily_loss: Decimal = Decimal("0")
    max_drawdown: Decimal = Decimal("0")
    max_consecutive_losses: int = 0
    stale_after_seconds: int = 0
    max_clock_drift_seconds: int = 0

    def __post_init__(self) -> None:
        for name in ("maximum_live_risk", "maximum_live_notional", "max_order_notional", "max_symbol_exposure", "max_total_exposure", "max_leverage", "max_daily_loss", "max_drawdown"):
            value = getattr(self, name)
            if value < 0:
                raise ValueError(f"risk parameter cannot be negative: {name}")
        if self.live_enabled and (self.maximum_live_risk <= 0 or self.maximum_live_notional <= 0):
            raise ValueError("live mode requires explicit non-zero live risk limits")


@dataclass(frozen=True)
class RiskState:
    stale_market_data: bool = True
    clock_drift_seconds: Decimal = Decimal("0")
    reconciliation_ok: bool = False
    websocket_connected: bool = False
    circuit_breaker_open: bool = True
    kill_switch_engaged: bool = True
    daily_loss: Decimal = Decimal("0")
    drawdown: Decimal = Decimal("0")
    consecutive_losses: int = 0
