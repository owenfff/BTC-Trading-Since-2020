from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal

from .balance import Balance
from .position import Position


@dataclass
class Portfolio:
    positions: dict[str, Position] = field(default_factory=dict)
    balances: dict[str, Balance] = field(default_factory=dict)
    as_of_timestamp: object | None = None

    def net_quantity(self, symbol: str) -> Decimal:
        position = self.positions.get(symbol.upper())
        return position.quantity if position else Decimal("0")

    def balance(self, currency: str) -> Balance:
        key = currency.upper()
        if key not in self.balances:
            self.balances[key] = Balance(key)
        return self.balances[key]
