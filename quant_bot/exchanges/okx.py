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

from .capabilities import ExchangeCapabilities
from .http import AdapterError, Transport
from .okx_http import OKXDemoCredentials, OKXDemoTransport


class OKXAdapter:
    name = "okx-demo"
    capabilities = ExchangeCapabilities("okx-demo", True, True, True, True, "DEMO", True, True, False, "x-simulated-trading=1 and OKX Demo REST/WS endpoints")

    def __init__(self, transport: Transport, *, credentials: object | None = None) -> None:
        self.transport = transport
        self.credentials = credentials
        self._order_symbols: dict[str, str] = {}
        self._instrument_types: dict[str, str] = {}

    @classmethod
    def from_environment(cls) -> "OKXAdapter":
        credentials = OKXDemoCredentials.from_environment()
        return cls(OKXDemoTransport(credentials), credentials=credentials)

    def _private_guard(self) -> None:
        if self.credentials is None:
            raise AdapterError(self.name, "DEMO_CREDENTIALS_REQUIRED", "OKX Demo private endpoints require local credentials")

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
        if not isinstance(response, dict) or str(response.get("code", "0")) != "0":
            raise AdapterError("okx-demo", str(response.get("code", "SCHEMA")) if isinstance(response, dict) else "SCHEMA", str(response.get("msg", "invalid response")) if isinstance(response, dict) else "invalid response")

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc) if value not in (None, "") else datetime.now(timezone.utc)

    @staticmethod
    def _status(value: Any) -> OrderStatus:
        return {"live": OrderStatus.OPEN, "partially_filled": OrderStatus.PARTIALLY_FILLED, "filled": OrderStatus.FILLED, "canceled": OrderStatus.CANCELED, "mmp_canceled": OrderStatus.CANCELED}.get(str(value), OrderStatus.UNKNOWN)

    @staticmethod
    def _side(value: Any) -> OrderSide:
        return OrderSide.BUY if str(value).lower() == "buy" else OrderSide.SELL

    def _instrument(self, item: dict[str, Any]) -> Instrument:
        inst_type = str(item.get("instType", ""))
        raw_id = str(item.get("instId", ""))
        spot = inst_type == "SPOT"
        instrument_type = InstrumentType.SPOT if spot else InstrumentType.LINEAR_PERPETUAL
        base = str(item.get("baseCcy") or raw_id.split("-")[0])
        quote = str(item.get("quoteCcy") or (raw_id.split("-")[1] if "-" in raw_id else "USDT"))
        settle = str(item.get("settleCcy") or quote)
        tick = self._decimal(item.get("tickSz"))
        lot = self._decimal(item.get("lotSz"), Decimal("1"))
        minimum = self._decimal(item.get("minSz"), lot)
        multiplier = Decimal("1") if spot else abs(self._decimal(item.get("ctVal"), Decimal("1")))
        instrument = Instrument(raw_id, instrument_type, base, quote, settle, tick or Decimal("0.01"), lot, minimum, Decimal("0"), contract_multiplier=multiplier, terms_complete=bool(raw_id and tick > 0 and lot > 0 and minimum > 0), metadata={"inst_type": inst_type, "state": item.get("state"), "raw": item})
        self._instrument_types[instrument.canonical_symbol] = inst_type
        return instrument

    def load_instruments(self, *, inst_type: str = "SPOT") -> list[Instrument]:
        response = self.transport.request("GET", f"/api/v5/public/instruments?instType={inst_type}")
        self._check(response)
        return [self._instrument(item) for item in response.get("data", []) if str(item.get("state", "live")) in {"live", "preopen"}]

    def load_all_instruments(self) -> list[Instrument]:
        result: list[Instrument] = []
        for inst_type in ("SPOT", "SWAP"):
            result.extend(self.load_instruments(inst_type=inst_type))
        return result

    def fetch_equity(self) -> Decimal:
        self._private_guard()
        response = self.transport.request("GET", "/api/v5/account/balance", private=True)
        self._check(response)
        rows = response.get("data", [])
        if not rows or rows[0].get("totalEq") in (None, ""):
            raise AdapterError(self.name, "EQUITY_UNRESOLVED", "OKX Demo returned no totalEq")
        return self._decimal(rows[0]["totalEq"])

    def fetch_balances(self) -> list[Balance]:
        self._private_guard()
        response = self.transport.request("GET", "/api/v5/account/balance", private=True)
        self._check(response)
        rows = response.get("data", [])
        if not rows:
            raise AdapterError(self.name, "SCHEMA", "OKX balance returned no account")
        result: list[Balance] = []
        for item in rows[0].get("details", []):
            currency = str(item.get("ccy") or "").upper()
            if currency:
                result.append(Balance(currency, self._decimal(item.get("eq")), self._decimal(item.get("availEq"), self._decimal(item.get("eq")))))
        return result

    def fetch_positions(self) -> list[Position]:
        self._private_guard()
        response = self.transport.request("GET", "/api/v5/account/positions?instType=SWAP", private=True)
        self._check(response)
        result: list[Position] = []
        for item in response.get("data", []):
            quantity = self._decimal(item.get("pos"))
            if quantity == 0 or not item.get("instId"):
                continue
            if str(item.get("posSide", "net")).lower() == "short":
                quantity = -abs(quantity)
            result.append(Position(str(item["instId"]), str(item.get("settleCcy") or "USDT"), quantity, self._decimal(item.get("avgPx")) if item.get("avgPx") else None, self._decimal(item.get("realizedPnl"))))
        return result

    def _order(self, item: dict[str, Any]) -> Order:
        client_id = str(item.get("clOrdId") or item.get("ordId") or "remote-order")
        symbol = str(item.get("instId") or "")
        self._order_symbols[client_id] = symbol
        order_type = str(item.get("ordType", "limit")).lower()
        return Order(client_id, symbol, self._side(item.get("side")), OrderType.MARKET if order_type == "market" else OrderType.LIMIT, self._decimal(item.get("sz")), self._timestamp(item.get("uTime") or item.get("cTime")), price=self._decimal(item.get("px")) if item.get("px") not in (None, "") else None, reduce_only=str(item.get("reduceOnly", "false")).lower() == "true", post_only=order_type == "post_only", status=self._status(item.get("state")), exchange_order_id=str(item.get("ordId")) if item.get("ordId") else None, metadata={"inst_type": item.get("instType"), "raw": item})

    def fetch_open_orders(self) -> list[Order]:
        self._private_guard()
        result: list[Order] = []
        for inst_type in ("SPOT", "SWAP"):
            response = self.transport.request("GET", f"/api/v5/trade/orders-pending?instType={inst_type}", private=True)
            self._check(response)
            result.extend(self._order(item) for item in response.get("data", []))
        return result

    def fetch_recent_fills(self) -> list[Fill]:
        self._private_guard()
        result: list[Fill] = []
        for inst_type in ("SPOT", "SWAP"):
            response = self.transport.request("GET", f"/api/v5/trade/fills?instType={inst_type}&limit=100", private=True)
            self._check(response)
            for item in response.get("data", []):
                quantity = abs(self._decimal(item.get("fillSz")))
                price = self._decimal(item.get("fillPx"))
                if quantity <= 0 or price <= 0:
                    continue
                client_id = str(item.get("clOrdId") or item.get("ordId") or item.get("tradeId"))
                result.append(Fill(str(item.get("tradeId") or item.get("ordId")), client_id, str(item.get("instId") or ""), self._side(item.get("side")), quantity, price, abs(self._decimal(item.get("fee"))), str(item.get("feeCcy") or "USDT"), self._timestamp(item.get("ts")), str(item.get("tradeId")) if item.get("tradeId") else None))
        return result

    def fetch_closed_bars(self, symbol: str, *, limit: int = 100) -> list[MarketBar]:
        response = self.transport.request("GET", f"/api/v5/market/candles?instId={symbol}&bar=1H&limit={limit}")
        self._check(response)
        result: list[MarketBar] = []
        for row in reversed(response.get("data", [])):
            if len(row) < 6 or (len(row) > 8 and str(row[8]) != "1"):
                continue
            result.append(MarketBar(symbol, self._timestamp(row[0]), row[1], row[2], row[3], row[4], row[5], source="okx-demo-rest-closed-1h"))
        return result

    def fetch_quote(self, symbol: str) -> tuple[Decimal, Decimal]:
        response = self.transport.request("GET", f"/api/v5/market/ticker?instId={symbol}")
        self._check(response)
        rows = response.get("data", [])
        if not rows or rows[0].get("bidPx") in (None, "") or rows[0].get("askPx") in (None, ""):
            raise AdapterError(self.name, "QUOTE_UNRESOLVED", f"no two-sided quote for {symbol}")
        bid, ask = self._decimal(rows[0]["bidPx"]), self._decimal(rows[0]["askPx"])
        if bid <= 0 or ask <= 0 or ask < bid:
            raise AdapterError(self.name, "QUOTE_INVALID", f"invalid quote for {symbol}")
        return bid, ask

    def place_order(self, order: Order) -> Order:
        self._private_guard()
        inst_type = self._instrument_types.get(order.symbol, "SPOT")
        body: dict[str, Any] = {"instId": order.symbol, "tdMode": "cash" if inst_type == "SPOT" else "cross", "side": order.side.value.lower(), "ordType": "post_only" if order.post_only else "limit" if order.order_type == OrderType.LIMIT else "market", "sz": str(order.quantity), "clOrdId": order.client_order_id}
        if order.price is not None:
            body["px"] = str(order.price)
        if order.reduce_only:
            body["reduceOnly"] = "true"
        response = self.transport.request("POST", "/api/v5/trade/order", body=body, private=True)
        self._check(response)
        rows = response.get("data", [])
        if not rows or not rows[0].get("ordId") or str(rows[0].get("sCode", "0")) != "0":
            raise AdapterError(self.name, str(rows[0].get("sCode", "SCHEMA")) if rows else "SCHEMA", str(rows[0].get("sMsg", "order response missing ordId")) if rows else "order response missing ordId")
        self._order_symbols[order.client_order_id] = order.symbol
        return Order(order.client_order_id, order.symbol, order.side, order.order_type, order.quantity, order.created_at, order.price, order.reduce_only, order.post_only, OrderStatus.OPEN, str(rows[0]["ordId"]), metadata={"raw": response})

    def cancel_order(self, client_order_id: str) -> Any:
        self._private_guard()
        symbol = self._order_symbols.get(client_order_id, "")
        body = {"instId": symbol, "clOrdId": client_order_id}
        response = self.transport.request("POST", "/api/v5/trade/cancel-order", body=body, private=True)
        self._check(response)
        return response

    def cancel_all(self) -> Any:
        return [self.cancel_order(order.client_order_id) for order in self.fetch_open_orders()]

    def reconcile_state(self) -> dict[str, Any]:
        return {"ok": True, "balances": self.fetch_balances(), "positions": self.fetch_positions(), "open_orders": self.fetch_open_orders(), "recent_fills": self.fetch_recent_fills()}

    def get_server_time(self) -> datetime:
        before = datetime.now(timezone.utc)
        response = self.transport.request("GET", "/api/v5/public/time")
        after = datetime.now(timezone.utc)
        self._check(response)
        rows = response.get("data", [])
        if not rows or not rows[0].get("ts"):
            raise AdapterError(self.name, "SCHEMA", "OKX returned no server time")
        server = self._timestamp(rows[0]["ts"])
        if hasattr(self.transport, "set_clock_offset_ms"):
            midpoint = before + (after - before) / 2
            self.transport.set_clock_offset_ms(int((server - midpoint).total_seconds() * 1000))
        return server

    def load_all_instruments_for_preflight(self) -> list[Instrument]:
        return self.load_all_instruments()


__all__ = ["OKXAdapter"]
