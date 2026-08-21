from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .common import canonical_symbol, decimal, utc_datetime
from .order import OrderSide


@dataclass(frozen=True)
class Fill:
    event_id: str
    client_order_id: str
    symbol: str
    side: OrderSide
    quantity: Any
    price: Any
    fee: Any
    fee_currency: str
    timestamp: datetime
    exchange_fill_id: str | None = None

    def __post_init__(self) -> None:
        if not self.event_id or not self.client_order_id:
            raise ValueError("fill event_id and client_order_id are required")
        object.__setattr__(self, "symbol", canonical_symbol(self.symbol))
        object.__setattr__(self, "fee_currency", canonical_symbol(self.fee_currency))
        object.__setattr__(self, "quantity", decimal(self.quantity))
        object.__setattr__(self, "price", decimal(self.price))
        object.__setattr__(self, "fee", decimal(self.fee))
        object.__setattr__(self, "timestamp", utc_datetime(self.timestamp))
        if self.quantity <= 0 or self.price <= 0:
            raise ValueError("fill quantity and price must be positive")
