from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quant_bot.domain.fill import Fill


@dataclass(frozen=True)
class FillAggregate:
    client_order_id: str
    filled_quantity: Decimal
    average_price: Decimal | None
    fee_total: Decimal
    fill_count: int


class FillTracker:
    def __init__(self) -> None:
        self._fills: dict[str, list[Fill]] = {}

    def add(self, fill: Fill) -> bool:
        bucket = self._fills.setdefault(fill.client_order_id, [])
        if any(existing.event_id == fill.event_id for existing in bucket):
            return False
        bucket.append(fill)
        return True

    def aggregate(self, client_order_id: str) -> FillAggregate:
        fills = self._fills.get(client_order_id, [])
        quantity = sum((fill.quantity for fill in fills), Decimal("0"))
        notional = sum((fill.quantity * fill.price for fill in fills), Decimal("0"))
        return FillAggregate(client_order_id, quantity, notional / quantity if quantity else None, sum((fill.fee for fill in fills), Decimal("0")), len(fills))
