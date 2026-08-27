from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from quant_bot.domain.balance import Balance
from quant_bot.domain.fill import Fill
from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.market_data import MarketBar
from quant_bot.domain.order import Order, OrderSide, OrderStatus, OrderType
from quant_bot.domain.position import Position

from .binance_futures_http import BinanceFuturesTestnetCredentials, BinanceFuturesTestnetTransport
from .binance_futures_ws import BinanceFuturesTestnetWebSocket
from .capabilities import ExchangeCapabilities
from .http import AdapterError, Transport


class BinanceFuturesAdapter:
    name = "binance-futures-testnet"
    capabilities = ExchangeCapabilities("binance-futures-testnet", True, True, True, True, "TESTNET", False, True, False, "native USDⓈ-M Futures Testnet REST/WS; linear USDT perpetuals only")

    def __init__(self, transport: Transport, *, credentials: object | None = None, websocket: BinanceFuturesTestnetWebSocket | None = None) -> None:
        self.transport = transport
        self.credentials = credentials
        self.websocket = websocket
        self._order_symbols: dict[str, str] = {}
        self._tracked_symbols: tuple[str, ...] = ()
        self.required_margin_mode = "isolated"
        self.margin_mode: str | None = None
        self.max_position_leverage: Decimal | None = None
        self.risk_configuration_verified = False

    @classmethod
    def from_environment(cls) -> "BinanceFuturesAdapter":
        credentials = BinanceFuturesTestnetCredentials.from_environment()
        transport = BinanceFuturesTestnetTransport(credentials)
        return cls(transport, credentials=credentials, websocket=BinanceFuturesTestnetWebSocket(transport))

    def _private_guard(self) -> None:
        if self.credentials is None:
            raise AdapterError(self.name, "TESTNET_CREDENTIALS_REQUIRED", "Binance USDⓈ-M Futures Testnet private endpoints require local credentials")

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
    def _check(response: Any) -> None:
        if isinstance(response, dict) and "code" in response and int(response.get("code", 0)) < 0:
            raise AdapterError("binance-futures-testnet", str(response.get("code")), str(response.get("msg", "invalid response")))
        if not isinstance(response, (dict, list)):
            raise AdapterError("binance-futures-testnet", "SCHEMA", "Binance Futures returned an invalid response")

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc) if value not in (None, "") else datetime.now(timezone.utc)

    @staticmethod
    def _status(value: Any) -> OrderStatus:
        return {"NEW": OrderStatus.OPEN, "PARTIALLY_FILLED": OrderStatus.PARTIALLY_FILLED, "FILLED": OrderStatus.FILLED, "CANCELED": OrderStatus.CANCELED, "REJECTED": OrderStatus.REJECTED, "EXPIRED": OrderStatus.CANCELED, "EXPIRED_IN_MATCH": OrderStatus.CANCELED}.get(str(value), OrderStatus.UNKNOWN)

    @staticmethod
    def _side(value: Any) -> OrderSide:
        return OrderSide.BUY if str(value).upper() == "BUY" else OrderSide.SELL

    @staticmethod
    def _filter(item: dict[str, Any], name: str) -> dict[str, Any]:
        return next((row for row in item.get("filters", []) if row.get("filterType") == name), {})

    def _instrument(self, item: dict[str, Any]) -> Instrument:
        price_filter = self._filter(item, "PRICE_FILTER")
        quantity_filter = self._filter(item, "LOT_SIZE") or self._filter(item, "MARKET_LOT_SIZE")
        notional_filter = self._filter(item, "NOTIONAL") or self._filter(item, "MIN_NOTIONAL")
        tick = self._decimal(price_filter.get("tickSize"))
        lot = self._decimal(quantity_filter.get("stepSize"))
        minimum = self._decimal(quantity_filter.get("minQty"), lot)
        minimum_notional = self._decimal(notional_filter.get("notional") or notional_filter.get("minNotional"))
        return Instrument(str(item["symbol"]), InstrumentType.LINEAR_PERPETUAL, str(item.get("baseAsset") or ""), str(item.get("quoteAsset") or "USDT"), str(item.get("marginAsset") or "USDT"), tick or Decimal("0.01"), lot or Decimal("0.001"), minimum or lot or Decimal("0.001"), minimum_notional, contract_multiplier=Decimal("1"), terms_complete=bool(item.get("symbol") and tick > 0 and lot > 0 and minimum > 0 and str(item.get("contractType", "")) == "PERPETUAL"), metadata={"status": item.get("status"), "contract_type": item.get("contractType"), "raw": item})

    def load_instruments(self) -> list[Instrument]:
        response = self.transport.request("GET", "/fapi/v1/exchangeInfo")
        self._check(response)
        return [self._instrument(item) for item in response.get("symbols", []) if item.get("status") == "TRADING" and item.get("contractType") == "PERPETUAL" and item.get("quoteAsset") == "USDT" and item.get("marginAsset", "USDT") == "USDT"]

    def load_all_instruments(self) -> list[Instrument]:
        return self.load_instruments()

    def fetch_equity(self) -> Decimal:
        self._private_guard()
        response = self.transport.request("GET", "/fapi/v2/account", private=True)
        self._check(response)
        value = response.get("totalMarginBalance") or response.get("totalWalletBalance")
        if value in (None, ""):
            raise AdapterError(self.name, "EQUITY_UNRESOLVED", "Binance Futures Testnet account returned no USDT-equivalent margin balance")
        return self._decimal(value)

    def fetch_balances(self) -> list[Balance]:
        self._private_guard()
        response = self.transport.request("GET", "/fapi/v2/balance", private=True)
        self._check(response)
        result: list[Balance] = []
        for item in response:
            currency = str(item.get("asset") or "").upper()
            total = self._decimal(item.get("balance"))
            available = self._decimal(item.get("availableBalance"), total)
            if currency and total != 0:
                result.append(Balance(currency, total, available))
        return result

    def fetch_positions(self) -> list[Position]:
        self._private_guard()
        response = self.transport.request("GET", "/fapi/v2/positionRisk", private=True)
        self._check(response)
        result: list[Position] = []
        modes: set[str] = set()
        leverages: list[Decimal] = []
        for item in response:
            quantity = self._decimal(item.get("positionAmt"))
            if str(item.get("isolated", "")).lower() in {"true", "false"}:
                modes.add("isolated" if str(item.get("isolated")).lower() == "true" else "cross")
            leverage = self._decimal(item.get("leverage")) if item.get("leverage") not in (None, "") else None
            if leverage is not None and leverage > 0:
                leverages.append(leverage)
            if quantity == 0 or not item.get("symbol"):
                continue
            result.append(Position(
                str(item["symbol"]),
                "USDT",
                quantity,
                self._decimal(item.get("entryPrice")) or None,
                self._decimal(item.get("realizedPnl")),
                leverage,
                "isolated" if str(item.get("isolated", "")).lower() == "true" else "cross" if str(item.get("isolated", "")).lower() == "false" else None,
                mark_price=self._decimal(item.get("markPrice")) if item.get("markPrice") not in (None, "") else None,
                unrealized_pnl=self._decimal(item.get("unRealizedProfit")) if item.get("unRealizedProfit") not in (None, "") else None,
                notional=self._decimal(item.get("notional")) if item.get("notional") not in (None, "") else None,
                margin_used=self._decimal(item.get("isolatedMargin")) if item.get("isolatedMargin") not in (None, "") else None,
            ))
        if modes:
            self.margin_mode = next(iter(modes)) if len(modes) == 1 else "MIXED"
            if any(mode != self.required_margin_mode for mode in modes):
                self.risk_configuration_verified = False
        elif not self.risk_configuration_verified:
            self.margin_mode = None
        if leverages:
            self.max_position_leverage = max(leverages)
            if self.max_position_leverage > Decimal("2"):
                self.risk_configuration_verified = False
        elif not self.risk_configuration_verified:
            self.max_position_leverage = None
        return result

    def verify_risk_configuration(
        self,
        symbols: Iterable[str],
        *,
        max_leverage: Decimal = Decimal("2"),
        required_margin_mode: str = "isolated",
    ) -> dict[str, Any]:
        """Read-only verification of one-way, isolated, low-leverage setup."""

        self._private_guard()
        requested = tuple(dict.fromkeys(str(symbol) for symbol in symbols if str(symbol)))
        mode_response = self.transport.request("GET", "/fapi/v1/positionSide/dual", private=True)
        self._check(mode_response)
        if str(mode_response.get("dualSidePosition", "true")).lower() != "false":
            raise AdapterError(self.name, "POSITION_MODE_NOT_ALLOWED", "Binance Futures must use one-way position mode for this runtime")
        observed: list[Decimal] = []
        for symbol in requested:
            response = self.transport.request("GET", f"/fapi/v2/positionRisk?symbol={symbol}", private=True)
            self._check(response)
            rows = [item for item in response if isinstance(item, dict) and str(item.get("symbol")) == symbol]
            if not rows:
                raise AdapterError(self.name, "RISK_CONFIGURATION_UNVERIFIED", f"no position configuration returned for {symbol}")
            for item in rows:
                if str(item.get("isolated", "")).lower() != "true":
                    raise AdapterError(self.name, "MARGIN_MODE_NOT_ALLOWED", f"Binance Futures {symbol} is not isolated")
                leverage = self._decimal(item.get("leverage"))
                if leverage <= 0 or leverage > max_leverage:
                    raise AdapterError(self.name, "LEVERAGE_LIMIT_OR_UNVERIFIED", f"Binance Futures leverage for {symbol} is not within the configured limit")
                observed.append(leverage)
        self.required_margin_mode = required_margin_mode
        self.margin_mode = required_margin_mode
        self.max_position_leverage = max(observed) if observed else max_leverage
        self.risk_configuration_verified = True
        return {"verified": True, "symbols": list(requested), "margin_mode": required_margin_mode, "max_leverage": str(self.max_position_leverage)}

    def _order(self, item: dict[str, Any]) -> Order:
        client_id = str(item.get("clientOrderId") or item.get("orderId") or "remote-order")
        symbol = str(item.get("symbol") or "")
        self._order_symbols[client_id] = symbol
        order_type = str(item.get("type", "LIMIT")).upper()
        return Order(client_id, symbol, self._side(item.get("side")), OrderType.MARKET if order_type == "MARKET" else OrderType.LIMIT, self._decimal(item.get("origQty") or item.get("executedQty")), self._timestamp(item.get("time") or item.get("updateTime")), price=self._decimal(item.get("price")) if item.get("price") not in (None, "") else None, reduce_only=str(item.get("reduceOnly", "false")).lower() == "true", post_only=str(item.get("timeInForce", "")).upper() == "GTX", status=self._status(item.get("status")), exchange_order_id=str(item.get("orderId")) if item.get("orderId") else None, metadata={"raw": item})

    def fetch_open_orders(self) -> list[Order]:
        self._private_guard()
        response = self.transport.request("GET", "/fapi/v1/openOrders", private=True)
        self._check(response)
        return [self._order(item) for item in response]

    def fetch_recent_fills(self) -> list[Fill]:
        self._private_guard()
        result: list[Fill] = []
        for symbol in self._tracked_symbols:
            response = self.transport.request("GET", f"/fapi/v1/userTrades?symbol={symbol}&limit=100", private=True)
            self._check(response)
            for item in response:
                quantity = abs(self._decimal(item.get("qty")))
                price = self._decimal(item.get("price"))
                if quantity <= 0 or price <= 0:
                    continue
                result.append(Fill(str(item.get("id") or item.get("orderId")), str(item.get("clientOrderId") or item.get("orderId")), symbol, self._side(item.get("side")), quantity, price, abs(self._decimal(item.get("commission"))), str(item.get("commissionAsset") or "USDT"), self._timestamp(item.get("time")), str(item.get("id")) if item.get("id") else None))
        return result

    def fetch_closed_bars(self, symbol: str, *, limit: int = 100) -> list[MarketBar]:
        response = self.transport.request("GET", f"/fapi/v1/klines?symbol={symbol}&interval=1h&limit={limit}")
        self._check(response)
        now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
        return [MarketBar(symbol, self._timestamp(row[0]), row[1], row[2], row[3], row[4], row[5], source="binance-futures-testnet-rest-closed-1h") for row in response if len(row) >= 7 and int(row[6]) < now_ms]

    def fetch_quote(self, symbol: str) -> tuple[Decimal, Decimal]:
        response = self.transport.request("GET", f"/fapi/v1/ticker/bookTicker?symbol={symbol}")
        self._check(response)
        bid, ask = self._decimal(response.get("bidPrice")), self._decimal(response.get("askPrice"))
        if bid <= 0 or ask <= 0 or ask < bid:
            raise AdapterError(self.name, "QUOTE_INVALID", f"invalid quote for {symbol}")
        return bid, ask

    def place_order(self, order: Order) -> Order:
        self._private_guard()
        if not self.risk_configuration_verified:
            raise AdapterError(self.name, "RISK_CONFIGURATION_UNVERIFIED", "verify one-way isolated margin and leverage before placing a futures order")
        order_type = "LIMIT" if order.order_type == OrderType.LIMIT else "MARKET"
        body: dict[str, Any] = {"symbol": order.symbol, "side": order.side.value, "type": order_type, "quantity": str(order.quantity), "newClientOrderId": order.client_order_id, "positionSide": "BOTH"}
        if order.price is not None:
            body["price"] = str(order.price)
        if order_type == "LIMIT":
            body["timeInForce"] = "GTX" if order.post_only else "GTC"
        if order.reduce_only:
            body["reduceOnly"] = "true"
        response = self.transport.request("POST", "/fapi/v1/order", body=body, private=True)
        self._check(response)
        if not response.get("orderId"):
            raise AdapterError(self.name, "SCHEMA", "Binance Futures order response missing orderId")
        self._order_symbols[order.client_order_id] = order.symbol
        return Order(order.client_order_id, order.symbol, order.side, order.order_type, order.quantity, order.created_at, order.price, order.reduce_only, order.post_only, OrderStatus.OPEN, str(response["orderId"]), metadata={"raw": response})

    def cancel_order(self, client_order_id: str) -> Any:
        self._private_guard()
        symbol = self._order_symbols.get(client_order_id, "")
        response = self.transport.request("DELETE", f"/fapi/v1/order?symbol={symbol}&origClientOrderId={client_order_id}", private=True)
        self._check(response)
        return response

    def cancel_all(self) -> Any:
        return [self.cancel_order(order.client_order_id) for order in self.fetch_open_orders()]

    def reconcile_state(self) -> dict[str, Any]:
        return {"ok": True, "balances": self.fetch_balances(), "positions": self.fetch_positions(), "open_orders": self.fetch_open_orders(), "recent_fills": self.fetch_recent_fills()}

    def get_server_time(self) -> datetime:
        before = int(datetime.now(timezone.utc).timestamp() * 1000)
        response = self.transport.request("GET", "/fapi/v1/time")
        after = int(datetime.now(timezone.utc).timestamp() * 1000)
        self._check(response)
        if not response.get("serverTime"):
            raise AdapterError(self.name, "SCHEMA", "Binance Futures returned no server time")
        server_ms = int(response["serverTime"])
        if hasattr(self.transport, "set_clock_offset_ms"):
            self.transport.set_clock_offset_ms(server_ms - ((before + after) // 2))
        return self._timestamp(server_ms)

    def set_tracked_symbols(self, symbols: list[str] | tuple[str, ...]) -> None:
        self._tracked_symbols = tuple(str(symbol).upper() for symbol in symbols)

    async def stream_messages(self, stop: Any, on_message: Any, on_error: Any | None = None) -> None:
        if self.websocket is None:
            raise AdapterError(self.name, "WEBSOCKET_NOT_CONFIGURED", "Binance Futures Testnet private WebSocket is not configured")
        await self.websocket.run(on_message, stop, on_error=on_error)


__all__ = ["BinanceFuturesAdapter"]
