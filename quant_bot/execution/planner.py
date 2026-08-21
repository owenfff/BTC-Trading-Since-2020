from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quant_bot.domain.instrument import Instrument
from quant_bot.domain.order import OrderSide, OrderType


@dataclass(frozen=True)
class PlannedOrder:
    client_order_id: str
    symbol: str
    side: OrderSide
    order_type: OrderType
    quantity: Decimal
    price: Decimal | None
    reduce_only: bool
    post_only: bool
    reason: str


def plan_delta(instrument: Instrument, client_order_id: str, current_quantity: Decimal, target_quantity: Decimal, *, price: Decimal | None = None, reduce_only: bool = False, post_only: bool = True) -> PlannedOrder | None:
    delta = target_quantity - current_quantity
    quantity = instrument.normalize_quantity(delta)
    if quantity == 0:
        return None
    side = OrderSide.BUY if delta > 0 else OrderSide.SELL
    normalized_price = instrument.normalize_price(price) if price is not None else None
    return PlannedOrder(client_order_id, instrument.canonical_symbol, side, OrderType.LIMIT if normalized_price is not None else OrderType.MARKET, quantity, normalized_price, reduce_only, post_only, "TARGET_DELTA")
