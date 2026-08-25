from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any

from quant_bot.domain.balance import Balance
from quant_bot.domain.fill import Fill
from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.market_data import MarketBar
from quant_bot.domain.order import Order, OrderSide, OrderStatus, OrderType
from quant_bot.domain.position import Position

from .binance_http import BinanceSpotTestnetTransport, BinanceTestnetCredentials
from .capabilities import ExchangeCapabilities
from .http import AdapterError, Transport


class BinanceSpotAdapter:
    name = "binance-spot-testnet"
    capabilities = ExchangeCapabilities("binance-spot-testnet", True, True, True, True, "TESTNET", True, False, False, "native Spot Testnet REST; reduce-only is not a Spot capability")

    def __init__(self, transport: Transport, *, credentials: object | None = None) -> None:
        self.transport = transport
        self.credentials = credentials
        self._order_symbols: dict[str, str] = {}
        self._tracked_symbols: tuple[str, ...] = ()

    @classmethod
    def from_environment(cls) -> "BinanceSpotAdapter":
        credentials = BinanceTestnetCredentials.from_environment()
        return cls(BinanceSpotTestnetTransport(credentials), credentials=credentials)

    def _private_guard(self) -> None:
        if self.credentials is None:
            raise AdapterError(self.name, "TESTNET_CREDENTIALS_REQUIRED", "Binance Spot Testnet private endpoints require local credentials")

    @staticmethod
    def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
        if value in (None, ""):
            return default
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return default
        return parsed if parsed.is_finite() else default

    @staticmethod
    def _check(response: dict[str, Any]) -> None:
        if not isinstance(response, dict) or "code" in response and int(response.get("code", 0)) < 0:
            raise AdapterError("binance-spot-testnet", str(response.get("code", "SCHEMA")) if isinstance(response, dict) else "SCHEMA", str(response.get("msg", "invalid response")) if isinstance(response, dict) else "invalid response")

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc) if value not in (None, "") else datetime.now(timezone.utc)

    @staticmethod
    def _status(value: Any) -> OrderStatus:
        return {"NEW": OrderStatus.OPEN, "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED, "FILLED": OrderStatus.FILLED, "CANCELED": OrderStatus.CANCELED, "REJECTED": OrderStatus.REJECTED, "EXPIRED": OrderStatus.CANCELED}.get(str(value), OrderStatus.UNKNOWN)

    @staticmethod
    def _side(value: Any) -> OrderSide:
        return OrderSide.BUY if str(value).upper() == "BUY" else OrderSide.SELL

    @staticmethod
    def _filter(item: dict[str, Any], name: str) -> dict[str, Any]:
        return next((row for row in item.get("filters", []) if row.get("filterType") == name), {})

    def _instrument(self, item: dict[str, Any]) -> Instrument:
        price_filter = self._filter(item, "PRICE_FILTER")
        quantity_filter = self._filter(item, "LOT_SIZE")
        notional_filter = self._filter(item, "NOTIONAL") or self._filter(item, "MIN_NOTIONAL")
        tick = self._decimal(price_filter.get("tickSize"))
        lot = self._decimal(quantity_filter.get("stepSize"))
        minimum = self._decimal(quantity_filter.get("minQty"), lot)
        minimum_notional = self._decimal(notional_filter.get("minNotional"))
        return Instrument(str(item["symbol"]), InstrumentType.SPOT, str(item.get("baseAsset") or ""), str(item.get("quoteAsset") or "USDT"), str(item.get("quoteAsset") or "USDT"), tick or Decimal("0.01"), lot or Decimal("0.00000001"), minimum or lot or Decimal("0.00000001"), minimum_notional, terms_complete=bool(item.get("symbol") and tick > 0 and lot > 0 and minimum > 0), metadata={"status": item.get("status"), "raw": item})

    def load_instruments(self) -> list[Instrument]:
        response = self.transport.request("GET", "/api/v3/exchangeInfo")
        self._check(response)
        return [self._instrument(item) for item in response.get("symbols", []) if item.get("status") == "TRADING" and item.get("isSpotTradingAllowed", True)]

    def load_all_instruments(self) -> list[Instrument]:
        return self.load_instruments()

    def fetch_equity(self) -> Decimal:
        self._private_guard()
        response = self.transport.request("GET", "/api/v3/account", private=True)
        self._check(response)
        usdt = next((item for item in response.get("balances", []) if str(item.get("asset", "")).upper() == "USDT"), None)
        if usdt is None:
            raise AdapterError(self.name, "EQUITY_UNRESOLVED", "Binance Spot Testnet account returned no USDT balance")
        return self._decimal(usdt.get("free")) + self._decimal(usdt.get("locked"))

    def fetch_balances(self) -> list[Balance]:
        self._private_guard()
        response = self.transport.request("GET", "/api/v3/account", private=True)
        self._check(response)
        return [Balance(str(item.get("asset")), self._decimal(item.get("free")) + self._decimal(item.get("locked")), self._decimal(item.get("free"))) for item in response.get("balances", []) if item.get("asset") and self._decimal(item.get("free")) + self._decimal(item.get("locked")) != 0]

    def fetch_positions(self) -> list[Position]:
        # Spot holdings are represented by balances; there is no leveraged position endpoint.
        return []

    def _order(self, item: dict[str, Any]) -> Order:
        client_id = str(item.get("clientOrderId") or item.get("orderId") or "remote-order")
        symbol = str(item.get("symbol") or "")
        self._order_symbols[client_id] = symbol
        order_type = str(item.get("type", "LIMIT")).upper()
        return Order(client_id, symbol, self._side(item.get("side")), OrderType.MARKET if order_type == "MARKET" else OrderType.LIMIT, self._decimal(item.get("origQty") or item.get("executedQty")), self._timestamp(item.get("time") or item.get("updateTime")), price=self._decimal(item.get("price")) if item.get("price") not in (None, "") else None, post_only=order_type == "LIMIT_MAKER", status=self._status(item.get("status")), exchange_order_id=str(item.get("orderId")) if item.get("orderId") else None, metadata={"raw": item})

    def fetch_open_orders(self) -> list[Order]:
        self._private_guard()
        response = self.transport.request("GET", "/api/v3/openOrders", private=True)
        self._check(response)
        return [self._order(item) for item in response]

    def fetch_recent_fills(self) -> list[Fill]:
        self._private_guard()
        result: list[Fill] = []
        for symbol in self._tracked_symbols:
            response = self.transport.request("GET", f"/api/v3/myTrades?symbol={symbol}&limit=100", private=True)
            self._check(response)
            for item in response:
                quantity = self._decimal(item.get("qty"))
                price = self._decimal(item.get("price"))
                if quantity <= 0 or price <= 0:
                    continue
                result.append(Fill(str(item.get("id") or item.get("orderId")), str(item.get("clientOrderId") or item.get("orderId")), symbol, OrderSide.SELL if item.get("isBuyer") is False else OrderSide.BUY, quantity, price, abs(self._decimal(item.get("commission"))), str(item.get("commissionAsset") or "USDT"), self._timestamp(item.get("time")), str(item.get("id")) if item.get("id") else None))
        return result

    def fetch_closed_bars(self, symbol: str, *, limit: int = 100) -> list[MarketBar]:
        response = self.transport.request("GET", f"/api/v3/klines?symbol={symbol}&interval=1h&limit={limit}")
        self._check(response)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        return [MarketBar(symbol, self._timestamp(row[0]), row[1], row[2], row[3], row[4], row[5], source="binance-spot-testnet-rest-closed-1h") for row in response if len(row) >= 7 and int(row[6]) < now_ms]

    def fetch_quote(self, symbol: str) -> tuple[Decimal, Decimal]:
        response = self.transport.request("GET", f"/api/v3/ticker/bookTicker?symbol={symbol}")
        self._check(response)
        bid, ask = self._decimal(response.get("bidPrice")), self._decimal(response.get("askPrice"))
        if bid <= 0 or ask <= 0 or ask < bid:
            raise AdapterError(self.name, "QUOTE_INVALID", f"invalid quote for {symbol}")
        return bid, ask

    def place_order(self, order: Order) -> Order:
        self._private_guard()
        if order.reduce_only:
            raise AdapterError(self.name, "REDUCE_ONLY_UNSUPPORTED", "Binance Spot has no reduceOnly order flag; balance-aware sell handling is required")
        order_type = "LIMIT_MAKER" if order.post_only else "LIMIT" if order.order_type == OrderType.LIMIT else "MARKET"
        body: dict[str, Any] = {"symbol": order.symbol, "side": order.side.value, "type": order_type, "quantity": str(order.quantity), "newClientOrderId": order.client_order_id}
        if order.price is not None:
            body["price"] = str(order.price)
        if order_type == "LIMIT":
            body["timeInForce"] = "GTC"
        response = self.transport.request("POST", "/api/v3/order", body=body, private=True)
        self._check(response)
        if not response.get("orderId"):
            raise AdapterError(self.name, "SCHEMA", "order response missing orderId")
        self._order_symbols[order.client_order_id] = order.symbol
        return Order(order.client_order_id, order.symbol, order.side, order.order_type, order.quantity, order.created_at, order.price, order.reduce_only, order.post_only, OrderStatus.OPEN, str(response["orderId"]), metadata={"raw": response})

    def cancel_order(self, client_order_id: str) -> Any:
        self._private_guard()
        symbol = self._order_symbols.get(client_order_id, "")
        response = self.transport.request("DELETE", f"/api/v3/order?symbol={symbol}&origClientOrderId={client_order_id}", private=True)
        self._check(response)
        return response

    def cancel_all(self) -> Any:
        return [self.cancel_order(order.client_order_id) for order in self.fetch_open_orders()]

    def reconcile_state(self) -> dict[str, Any]:
        return {"ok": True, "balances": self.fetch_balances(), "positions": self.fetch_positions(), "open_orders": self.fetch_open_orders(), "recent_fills": self.fetch_recent_fills()}

    def get_server_time(self) -> datetime:
        before = int(datetime.now(timezone.utc).timestamp() * 1000)
        response = self.transport.request("GET", "/api/v3/time")
        after = int(datetime.now(timezone.utc).timestamp() * 1000)
        self._check(response)
        if not response.get("serverTime"):
            raise AdapterError(self.name, "SCHEMA", "Binance returned no server time")
        server_ms = int(response["serverTime"])
        if hasattr(self.transport, "set_clock_offset_ms"):
            self.transport.set_clock_offset_ms(server_ms - ((before + after) // 2))
        return self._timestamp(server_ms)

    def set_tracked_symbols(self, symbols: list[str] | tuple[str, ...]) -> None:
        self._tracked_symbols = tuple(str(symbol).upper() for symbol in symbols)


__all__ = ["BinanceSpotAdapter"]
