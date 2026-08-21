from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quant_bot.domain.risk import RiskState
from quant_bot.strategy.base import StrategySignal


@dataclass
class PaperState:
    position: Decimal = Decimal("0")
    cash: Decimal = Decimal("1")
    fees: Decimal = Decimal("0")
    funding: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    filled_orders: int = 0
    partial_orders: int = 0
    canceled_orders: int = 0
    rejected_orders: int = 0


class PaperTradingEngine:
    def __init__(self, *, fee_rate: Decimal = Decimal("0.0005"), slippage_rate: Decimal = Decimal("0.0001"), fill_ratio: Decimal = Decimal("0.5")) -> None:
        self.fee_rate = fee_rate
        self.slippage_rate = slippage_rate
        self.fill_ratio = fill_ratio
        self.state = PaperState()

    def apply_signal(self, signal: StrategySignal, *, reference_price: Decimal, funding_rate: Decimal = Decimal("0"), risk_state: RiskState | None = None) -> None:
        if risk_state is not None and (risk_state.kill_switch_engaged or risk_state.stale_market_data):
            self.state.rejected_orders += 1
            return
        target = Decimal(str(signal.target_exposure))
        delta = target - self.state.position
        if delta == 0:
            return
        filled_delta = delta * self.fill_ratio
        if abs(filled_delta) < abs(delta):
            self.state.partial_orders += 1
        else:
            self.state.filled_orders += 1
        self.state.position += filled_delta
        self.state.fees += abs(filled_delta) * self.fee_rate
        self.state.slippage += abs(filled_delta) * self.slippage_rate
        self.state.funding += self.state.position * funding_rate
        self.state.cash -= abs(filled_delta) * self.fee_rate + abs(filled_delta) * self.slippage_rate + self.state.position * funding_rate

    def cancel_all(self) -> None:
        self.state.canceled_orders += 1

    def snapshot(self) -> dict[str, str | int]:
        return {
            "position": str(self.state.position),
            "cash": str(self.state.cash),
            "fees": str(self.state.fees),
            "funding": str(self.state.funding),
            "slippage": str(self.state.slippage),
            "filled_orders": self.state.filled_orders,
            "partial_orders": self.state.partial_orders,
            "canceled_orders": self.state.canceled_orders,
            "rejected_orders": self.state.rejected_orders,
        }
