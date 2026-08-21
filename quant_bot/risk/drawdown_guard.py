from __future__ import annotations

from decimal import Decimal


def drawdown_is_safe(drawdown: Decimal, maximum_drawdown: Decimal) -> bool:
    return abs(Decimal(str(drawdown))) <= Decimal(str(maximum_drawdown))
