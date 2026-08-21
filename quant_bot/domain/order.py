from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any

from .common import canonical_symbol, decimal, utc_datetime


class OrderSide(StrEnum):
    BUY = "BUY"
    SELL = "SELL"


class OrderType(StrEnum):
    MARKET = "MARKET"
    LIMIT = "LIMIT"


class OrderStatus(StrEnum):
    NEW = "NEW"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class Order:
    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Any
    created_at: datetime
    price: Any | None = None
    reduce_only: bool = False
    post_only: bool = False
    status: OrderStatus = OrderStatus.NEW
    exchange_order_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.client_order_id:
            raise ValueError("client_order_id is required for idempotency")
        object.__setattr__(self, "symbol", canonical_symbol(self.symbol))
        object.__setattr__(self, "quantity", decimal(self.quantity))
        if self.quantity <= 0:
            raise ValueError("order quantity must be positive")
        object.__setattr__(self, "created_at", utc_datetime(self.created_at))
        if self.price is not None:
            object.__setattr__(self, "price", decimal(self.price))
