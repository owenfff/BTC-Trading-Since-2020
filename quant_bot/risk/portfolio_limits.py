from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True)
class LimitResult:
    allowed: bool
    reasons: tuple[str, ...]


def check_portfolio_limits(order_notional: Decimal, symbol_exposure: Decimal, total_exposure: Decimal, leverage: Decimal, *, max_order_notional: Decimal, max_symbol_exposure: Decimal, max_total_exposure: Decimal, max_leverage: Decimal) -> LimitResult:
    reasons: list[str] = []
    if order_notional > max_order_notional:
        reasons.append("MAX_ORDER_NOTIONAL")
    if abs(symbol_exposure) > max_symbol_exposure:
        reasons.append("MAX_SYMBOL_EXPOSURE")
    if abs(total_exposure) > max_total_exposure:
        reasons.append("MAX_TOTAL_EXPOSURE")
    if leverage > max_leverage:
        reasons.append("MAX_LEVERAGE")
    return LimitResult(not reasons, tuple(reasons))
