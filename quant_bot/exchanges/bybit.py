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

from .bybit_http import BybitCredentials, BybitDemoTransport, DEMO_REST_BASE_URL
from .bybit_ws import BybitDemoWebSocket
from .capabilities import ExchangeCapabilities
from .http import AdapterError, Transport


class BybitAdapter:
    name = "bybit-demo"
    capabilities = ExchangeCapabilities("bybit-demo", True, True, True, True, "DEMO", True, True, True, "hard-pinned api-demo.bybit.com and stream-demo.bybit.com")

    def __init__(self, transport: Transport, *, credentials: object | None = None, websocket: BybitDemoWebSocket | None = None) -> None:
        self.transport = transport
        self.credentials = credentials
        self.websocket = websocket
        self.connected = False
        self._order_symbols: dict[str, str] = {}
        self._symbol_categories: dict[str, str] = {}

    @classmethod
    def from_environment(cls) -> "BybitAdapter":
        credentials = BybitCredentials.from_environment()
        transport = BybitDemoTransport(credentials, base_url=DEMO_REST_BASE_URL)
        return cls(transport, credentials=credentials, websocket=BybitDemoWebSocket(credentials))

    def _private_guard(self) -> None:
        if self.credentials is None:
            raise AdapterError(self.name, "DEMO_CREDENTIALS_REQUIRED", "private Demo endpoint requires local credentials")

    @staticmethod
    def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
        if value in (None, ""):
            return default
        try:
            parsed = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return default
        return parsed if parsed.is_finite() else default

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def health_check(self) -> bool:
        try:
            self.load_instruments(category="linear")
            return True
        except AdapterError:
            return False

    def load_instruments(self, *, category: str = "linear") -> list[Instrument]:
        response = self.transport.request("GET", f"/v5/market/instruments-info?category={category}")
        self._check(response)
        instruments = [self._instrument(item, category) for item in response.get("result", {}).get("list", [])]
        for instrument in instruments:
            self._symbol_categories[instrument.canonical_symbol] = category
        return instruments

    def load_all_instruments(self) -> list[Instrument]:
        result: list[Instrument] = []
        for category in ("linear", "inverse", "spot"):
            try:
                result.extend(self.load_instruments(category=category))
            except (AdapterError, KeyError):
                continue
        return result

    def _instrument(self, item: dict[str, Any], category: str = "linear") -> Instrument:
        filters = item.get("lotSizeFilter", {})
        price_filter = item.get("priceFilter", {})
        if category == "spot":
            step = self._decimal(filters.get("basePrecision", filters.get("qtyStep", "0")))
            minimum = self._decimal(filters.get("minOrderQty"), step)
            multiplier = Decimal("1")
            instrument_type = InstrumentType.SPOT
        else:
            step = self._decimal(filters.get("qtyStep"))
            minimum = self._decimal(filters.get("minOrderQty"), step)
            raw_multiplier = item.get("contractMultiplier", item.get("contractValue", ""))
            multiplier = abs(self._decimal(raw_multiplier, Decimal("1"))) if raw_multiplier not in (None, "", "0", 0) else Decimal("1")
            instrument_type = InstrumentType.INVERSE_PERPETUAL if category == "inverse" else InstrumentType.LINEAR_PERPETUAL
        tick = self._decimal(price_filter.get("tickSize"))
        terms_complete = bool(item.get("symbol")) and tick > 0 and step > 0 and minimum > 0
        return Instrument(
            str(item["symbol"]), instrument_type, str(item.get("baseCoin") or item.get("baseCurrency") or "BTC"),
            str(item.get("quoteCoin") or "USDT"), str(item.get("settleCoin") or item.get("quoteCoin") or "USDT"),
            tick or Decimal("0.01"), step or Decimal("1"), minimum or Decimal("1"),
            self._decimal(filters.get("minNotionalValue")), contract_multiplier=multiplier,
            terms_complete=terms_complete, metadata={"category": category, "status": item.get("status"), "raw_multiplier": item.get("contractMultiplier", item.get("contractValue", "")), "multiplier_source": "BYBIT_V5_CATEGORY_UNIT_SEMANTICS", "raw": item},
        )

    def _category_for(self, symbol: str) -> str:
        return self._symbol_categories.get(symbol.upper(), "linear")

    @staticmethod
    def _check(response: dict[str, Any]) -> None:
        if not isinstance(response, dict) or str(response.get("retCode", "0")) != "0":
            raise AdapterError("bybit-demo", str(response.get("retCode", "SCHEMA")) if isinstance(response, dict) else "SCHEMA", str(response.get("retMsg", "invalid response")) if isinstance(response, dict) else "invalid response")

    @staticmethod
    def _status(value: Any) -> OrderStatus:
        return {"Created": OrderStatus.NEW, "New": OrderStatus.OPEN, "PartiallyFilled": OrderStatus.PARTIALLY_FILLED, "Filled": OrderStatus.FILLED, "Cancelled": OrderStatus.CANCELED, "Rejected": OrderStatus.REJECTED}.get(str(value), OrderStatus.UNKNOWN)

    @staticmethod
    def _side(value: Any) -> OrderSide:
        return OrderSide.BUY if str(value).lower() == "buy" else OrderSide.SELL

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        if value in (None, ""):
            return datetime.now(timezone.utc)
        try:
            return datetime.fromtimestamp(int(value) / 1000, timezone.utc)
        except (TypeError, ValueError):
            return datetime.fromisoformat(str(value).replace("Z", "+00:00")).astimezone(timezone.utc)

    def _order(self, item: dict[str, Any]) -> Order:
        client_id = str(item.get("orderLinkId") or item.get("orderId") or "remote-order")
        symbol = str(item.get("symbol") or "")
        self._order_symbols[client_id] = symbol
        quantity = abs(Decimal(str(item.get("qty") or item.get("leavesQty") or "0"))) or Decimal("1")
        return Order(client_id, symbol, self._side(item.get("side")), OrderType.MARKET if str(item.get("orderType", "")).lower() == "market" else OrderType.LIMIT, quantity, self._timestamp(item.get("updatedTime") or item.get("createdTime")), price=Decimal(str(item["price"])) if item.get("price") not in (None, "") else None, reduce_only=str(item.get("reduceOnly", "false")).lower() == "true", post_only=str(item.get("timeInForce", "")).lower() == "postonly", status=self._status(item.get("orderStatus")), exchange_order_id=str(item.get("orderId")) if item.get("orderId") else None, metadata={"raw": item})

    def fetch_equity(self) -> Decimal:
        self._private_guard()
        response = self.transport.request("GET", "/v5/account/wallet-balance?accountType=UNIFIED", private=True)
        self._check(response)
        accounts = response.get("result", {}).get("list", [])
        if not accounts or accounts[0].get("totalEquity") in (None, ""):
            raise AdapterError(self.name, "EQUITY_UNRESOLVED", "Unified Demo account returned no totalEquity")
        return self._decimal(accounts[0]["totalEquity"])

    def fetch_balances(self) -> list[Balance]:
        self._private_guard()
        response = self.transport.request("GET", "/v5/account/wallet-balance?accountType=UNIFIED", private=True)
        self._check(response)
        accounts = response.get("result", {}).get("list", [])
        if not accounts:
            raise AdapterError(self.name, "SCHEMA", "wallet balance returned no account")
        result = [Balance("USD", self._decimal(accounts[0].get("totalEquity")), self._decimal(accounts[0].get("totalAvailableBalance"), self._decimal(accounts[0].get("totalEquity"))))]
        for coin in accounts[0].get("coin", []):
            currency = str(coin.get("coin") or "").upper()
            if currency and coin.get("walletBalance") not in (None, ""):
                result.append(Balance(currency, self._decimal(coin["walletBalance"]), self._decimal(coin.get("availableToWithdraw"), self._decimal(coin["walletBalance"]))))
        return result

    def fetch_positions(self) -> list[Position]:
        self._private_guard()
        result = []
        for category in ("linear", "inverse"):
            suffix = "&settleCoin=USDT" if category == "linear" else ""
            response = self.transport.request("GET", f"/v5/position/list?category={category}{suffix}", private=True)
            self._check(response)
            for row in response.get("result", {}).get("list", []):
                size = self._decimal(row.get("size"))
                if size == 0 or not row.get("symbol"):
                    continue
                signed = size if str(row.get("side", "Buy")).lower() == "buy" else -size
                result.append(Position(str(row["symbol"]), str(row.get("settleCoin") or "USDT"), signed, self._decimal(row.get("avgPrice")) if row.get("avgPrice") else None, self._decimal(row.get("cumRealisedPnl"))))
        return result

    def fetch_open_orders(self) -> list[Order]:
        self._private_guard()
        orders: list[Order] = []
        for category in ("linear", "inverse"):
            suffix = "&settleCoin=USDT" if category == "linear" else ""
            response = self.transport.request("GET", f"/v5/order/realtime?category={category}{suffix}", private=True)
            self._check(response)
            orders.extend(self._order(row) for row in response.get("result", {}).get("list", []))
        return orders

    def fetch_recent_fills(self) -> list[Fill]:
        self._private_guard()
        result = []
        for category in ("linear", "inverse"):
            response = self.transport.request("GET", f"/v5/execution/list?category={category}&limit=100", private=True)
            self._check(response)
            for row in response.get("result", {}).get("list", []):
                quantity = abs(self._decimal(row.get("execQty")))
                price = self._decimal(row.get("execPrice"))
                if quantity <= 0 or price <= 0:
                    continue
                client_id = str(row.get("orderLinkId") or row.get("orderId") or row.get("execId"))
                result.append(Fill(str(row.get("execId") or row.get("orderId")), client_id, str(row.get("symbol") or ""), self._side(row.get("side")), quantity, price, abs(self._decimal(row.get("execFee"))), str(row.get("feeCurrency") or row.get("execFeeCurrency") or "USDT"), self._timestamp(row.get("execTime")), str(row.get("execId")) if row.get("execId") else None))
        return result

    def fetch_closed_bars(self, symbol: str, *, category: str | None = None, limit: int = 100) -> list[MarketBar]:
        category = category or self._category_for(symbol)
        response = self.transport.request("GET", f"/v5/market/kline?category={category}&symbol={symbol}&interval=60&limit={limit}")
        self._check(response)
        bars: list[MarketBar] = []
        for row in reversed(response.get("result", {}).get("list", [])):
            if len(row) < 6:
                continue
            bar_time = datetime.fromtimestamp(int(row[0]) / 1000, timezone.utc)
            if bar_time.timestamp() + 3600 >= datetime.now(timezone.utc).timestamp():
                continue
            bars.append(MarketBar(symbol, bar_time, row[1], row[2], row[3], row[4], row[5], source="bybit-demo-rest-closed-1h"))
        return bars

    def fetch_quote(self, symbol: str, *, category: str | None = None) -> tuple[Decimal, Decimal]:
        category = category or self._category_for(symbol)
        response = self.transport.request("GET", f"/v5/market/tickers?category={category}&symbol={symbol}")
        self._check(response)
        rows = response.get("result", {}).get("list", [])
        if not rows or rows[0].get("bid1Price") in (None, "") or rows[0].get("ask1Price") in (None, ""):
            raise AdapterError(self.name, "QUOTE_UNRESOLVED", f"no two-sided quote for {symbol}")
        bid = Decimal(str(rows[0]["bid1Price"]))
        ask = Decimal(str(rows[0]["ask1Price"]))
        if bid <= 0 or ask <= 0 or ask < bid:
            raise AdapterError(self.name, "QUOTE_INVALID", f"invalid quote for {symbol}")
        return bid, ask

    def place_order(self, order: Order) -> Order:
        self._private_guard()
        category = self._category_for(order.symbol)
        body: dict[str, Any] = {"category": category, "symbol": order.symbol, "side": order.side.value.title(), "orderType": order.order_type.value.title(), "qty": str(order.quantity), "orderLinkId": order.client_order_id}
        if order.price is not None:
            body["price"] = str(order.price)
        if order.post_only:
            body["timeInForce"] = "PostOnly"
        if order.reduce_only:
            body["reduceOnly"] = True
        response = self.transport.request("POST", "/v5/order/create", private=True, body=body)
        self._check(response)
        order_id = response.get("result", {}).get("orderId")
        if not order_id:
            raise AdapterError(self.name, "SCHEMA", "order response missing orderId")
        self._order_symbols[order.client_order_id] = order.symbol
        return Order(order.client_order_id, order.symbol, order.side, order.order_type, order.quantity, order.created_at, order.price, order.reduce_only, order.post_only, OrderStatus.OPEN, str(order_id), metadata={"raw": response})

    def amend_order(self, client_order_id: str, changes: dict[str, object]) -> Any:
        self._private_guard()
        symbol = self._order_symbols.get(client_order_id, str(changes.get("symbol", "")))
        return self.transport.request("POST", "/v5/order/amend", private=True, body={"category": self._category_for(symbol), "symbol": symbol, "orderLinkId": client_order_id, **changes})

    def cancel_order(self, client_order_id: str) -> Any:
        self._private_guard()
        symbol = self._order_symbols.get(client_order_id, "")
        return self.transport.request("POST", "/v5/order/cancel", private=True, body={"category": self._category_for(symbol), "symbol": symbol, "orderLinkId": client_order_id})

    def cancel_all(self) -> Any:
        self._private_guard()
        responses = []
        for category in ("linear", "inverse"):
            responses.append(self.transport.request("POST", "/v5/order/cancel-all", private=True, body={"category": category}))
        return responses

    def cancel_all_after(self, timeout_ms: int = 60_000) -> dict[str, Any]:
        if timeout_ms < 1_000 or timeout_ms > 600_000:
            raise ValueError("local watchdog timeout must be between 1000 and 600000 ms")
        return {"supported": False, "mode": "LOCAL_CANCEL_ON_DISCONNECT", "timeout_ms": timeout_ms}

    def reconcile_state(self) -> dict[str, Any]:
        return {"ok": True, "balances": self.fetch_balances(), "positions": self.fetch_positions(), "open_orders": self.fetch_open_orders(), "recent_fills": self.fetch_recent_fills()}

    def get_server_time(self) -> datetime:
        response = self.transport.request("GET", "/v5/market/time")
        self._check(response)
        timestamp = response.get("time") or response.get("result", {}).get("timeNano", "")
        if not timestamp:
            raise AdapterError(self.name, "SCHEMA", "Bybit Demo returned no server time")
        return datetime.fromtimestamp(int(str(timestamp)[:13]) / 1000, timezone.utc)

    def get_rate_limit_state(self) -> object:
        return getattr(self.transport, "last_rate_limit", {})

    async def stream_messages(self, stop: Any, on_message: Any) -> None:
        if self.websocket is None:
            raise AdapterError(self.name, "WEBSOCKET_NOT_CONFIGURED", "Demo websocket is not configured")
        await self.websocket.run(on_message, stop, ["order", "execution", "position", "wallet"])

    def stream_market_data(self, symbol: str) -> Any:
        return iter(self.fetch_closed_bars(symbol))

    def normalize_error(self, payload: dict[str, Any]) -> AdapterError:
        return AdapterError(self.name, str(payload.get("retCode", "UNKNOWN")), str(payload.get("retMsg", payload)), retryable=False)
