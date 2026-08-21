from __future__ import annotations

from decimal import Decimal
from typing import Any

from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.order import Order, OrderStatus

from .capabilities import ExchangeCapabilities
from .http import AdapterError, Transport


class BybitAdapter:
    name = "bybit"
    capabilities = ExchangeCapabilities("bybit", True, True, True, True, "TESTNET", True, True, False, "Testnet endpoint documented; transport and credentials are injected")

    def __init__(self, transport: Transport, *, credentials: object | None = None) -> None:
        self.transport = transport
        self.credentials = credentials

    def load_instruments(self) -> list[Instrument]:
        response = self.transport.request("GET", "/v5/market/instruments-info?category=linear")
        self._check(response)
        return [self._instrument(item) for item in response.get("result", {}).get("list", [])]

    def _instrument(self, item: dict[str, Any]) -> Instrument:
        filters = item.get("lotSizeFilter", {})
        price_filter = item.get("priceFilter", {})
        step = Decimal(str(filters.get("qtyStep", "1")))
        return Instrument(str(item["symbol"]), InstrumentType.LINEAR_PERPETUAL, str(item.get("baseCoin") or "BTC"), str(item.get("quoteCoin") or "USDT"), str(item.get("settleCoin") or "USDT"), Decimal(str(price_filter.get("tickSize", "0.01"))), step, Decimal(str(filters.get("minOrderQty", step))), Decimal(str(filters.get("minNotionalValue", "0"))))

    def place_order(self, order: Order) -> Order:
        if self.credentials is None:
            raise AdapterError(self.name, "DEMO_CREDENTIALS_REQUIRED", "private order endpoint requires injected credentials")
        response = self.transport.request("POST", "/v5/order/create", private=True, body={"category": "linear", "symbol": order.symbol, "side": order.side.value.title(), "orderType": order.order_type.value.title(), "qty": str(order.quantity), "orderLinkId": order.client_order_id})
        self._check(response)
        order_id = response.get("result", {}).get("orderId")
        if not order_id:
            raise AdapterError(self.name, "SCHEMA", "order response missing orderId")
        return Order(order.client_order_id, order.symbol, order.side, order.order_type, order.quantity, order.created_at, order.price, order.reduce_only, order.post_only, OrderStatus.OPEN, str(order_id))

    def _check(self, response: dict[str, Any]) -> None:
        if str(response.get("retCode", "0")) != "0":
            raise AdapterError(self.name, str(response.get("retCode")), str(response.get("retMsg", "unknown")), retryable=False)

    def normalize_error(self, payload: dict[str, Any]) -> AdapterError:
        return AdapterError(self.name, str(payload.get("retCode", "UNKNOWN")), str(payload.get("retMsg", payload)), retryable=False)
