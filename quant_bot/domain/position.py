from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .common import canonical_symbol, decimal
from .fill import Fill
from .order import OrderSide


@dataclass
class Position:
    symbol: str
    settlement_currency: str
    quantity: Decimal = Decimal("0")
    average_entry_price: Decimal | None = None
    realized_pnl: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        self.symbol = canonical_symbol(self.symbol)
        self.settlement_currency = canonical_symbol(self.settlement_currency)
        self.quantity = decimal(self.quantity)
        self.realized_pnl = decimal(self.realized_pnl)
        if self.average_entry_price is not None:
            self.average_entry_price = decimal(self.average_entry_price)

    def apply_fill(self, fill: Fill) -> None:
        signed = fill.quantity if fill.side == OrderSide.BUY else -fill.quantity
        previous = self.quantity
        new_quantity = previous + signed
        if previous == 0 or (previous > 0 and signed > 0) or (previous < 0 and signed < 0):
            old_abs = abs(previous)
            add_abs = abs(signed)
            prior_price = self.average_entry_price or fill.price
            self.average_entry_price = (old_abs * prior_price + add_abs * fill.price) / (old_abs + add_abs)
        elif previous != 0 and ((previous > 0 > new_quantity) or (previous < 0 < new_quantity)):
            self.average_entry_price = fill.price if new_quantity != 0 else None
        elif new_quantity == 0:
            self.average_entry_price = None
        self.quantity = new_quantity

