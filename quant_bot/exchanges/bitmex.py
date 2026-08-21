from __future__ import annotations

from decimal import Decimal
from typing import Any

from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.order import Order, OrderSide, OrderStatus, OrderType

from .capabilities import ExchangeCapabilities
from .http import AdapterError, Transport


class BitmexAdapter:
    name = "bitmex"
    capabilities = ExchangeCapabilities("bitmex", True, True, True, True, "TESTNET", True, True, True, "REST/WS endpoints require injected transport and credentials")

    def __init__(self, transport: Transport, *, credentials: object | None = None) -> None:
        self.transport = transport
        self.credentials = credentials

    def load_instruments(self) -> list[Instrument]:
        response = self.transport.request("GET", "/api/v1/instrument")
        if not isinstance(response, list):
            raise AdapterError(self.name, "SCHEMA", "instrument response must be a list")
        return [self._instrument(item) for item in response]

    def _instrument(self, item: dict[str, Any]) -> Instrument:
        typ = str(item.get("typ", ""))
        instrument_type = InstrumentType.INVERSE_PERPETUAL if typ == "FFWCSX" else InstrumentType.LINEAR_PERPETUAL
        settlement = str(item.get("settlCurrency") or item.get("settleCurrency") or "XBT")
        return Instrument(str(item["symbol"]), instrument_type, str(item.get("underlying") or "XBT"), str(item.get("quoteCurrency") or "USD"), settlement, Decimal(str(item.get("tickSize", "0.1"))), Decimal(str(item.get("lotSize", "1"))), Decimal(str(item.get("lotSize", "1"))), Decimal("0"))

    def place_order(self, order: Order) -> Order:
        if self.credentials is None:
            raise AdapterError(self.name, "DEMO_CREDENTIALS_REQUIRED", "private order endpoint requires injected credentials")
        response = self.transport.request("POST", "/api/v1/order", private=True, body={"symbol": order.symbol, "side": order.side.value, "orderQty": str(order.quantity), "ordType": order.order_type.value.title(), "clOrdID": order.client_order_id})
        if not isinstance(response, dict) or "orderID" not in response:
            raise AdapterError(self.name, "SCHEMA", "order response missing orderID")
        return Order(order.client_order_id, order.symbol, order.side, order.order_type, order.quantity, order.created_at, order.price, order.reduce_only, order.post_only, OrderStatus.OPEN, str(response["orderID"]))

    def normalize_error(self, payload: dict[str, Any]) -> AdapterError:
        return AdapterError(self.name, str(payload.get("error", {}).get("name", "UNKNOWN")), str(payload.get("error", {}).get("message", payload)), retryable=False)
