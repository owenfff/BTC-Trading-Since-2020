from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .common import canonical_symbol, decimal


@dataclass
class Balance:
    currency: str
    total: Decimal = Decimal("0")
    available: Decimal = Decimal("0")
    reserved: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        self.currency = canonical_symbol(self.currency)
        self.total = decimal(self.total)
        self.available = decimal(self.available)
        self.reserved = decimal(self.reserved)
        if self.total < 0 or self.available < 0 or self.reserved < 0:
            raise ValueError("balances cannot be negative")
