from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from typing import Any, Iterable

from quant_bot.domain.balance import Balance
from quant_bot.domain.fill import Fill
from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.market_data import MarketBar, MarketContext, MarketQuote
from quant_bot.domain.order import Order, OrderSide, OrderStatus, OrderType
from quant_bot.domain.position import Position

from .capabilities import ExchangeCapabilities
from .http import AdapterError, Transport
from .okx_http import OKXDemoCredentials, OKXDemoTransport
from .okx_ws import OKXDemoWebSocket


class OKXAdapter:
    name = "okx-demo"
    capabilities = ExchangeCapabilities("okx-demo", True, True, True, True, "DEMO", True, True, False, "x-simulated-trading=1 and OKX Demo REST/WS endpoints")

    def __init__(self, transport: Transport, *, credentials: object | None = None, websocket: OKXDemoWebSocket | None = None) -> None:
        self.transport = transport
        self.credentials = credentials
        self.websocket = websocket
        self._order_symbols: dict[str, str] = {}
        self._instrument_types: dict[str, str] = {}
        self.margin_mode: str | None = None
        self.required_margin_mode = "isolated"
        self.order_margin_mode = "isolated"
        self.max_position_leverage: Decimal | None = None
        self.risk_configuration_verified = False
        self.risk_configuration_at: datetime | None = None
        self.risk_configuration_by_symbol: dict[str, bool] = {}
        self.risk_configuration_reason_by_symbol: dict[str, tuple[str, ...]] = {}
        self.leverage_by_symbol: dict[str, Decimal] = {}
        self.margin_mode_by_symbol: dict[str, str] = {}

    @classmethod
    def from_environment(cls) -> "OKXAdapter":
        credentials = OKXDemoCredentials.from_environment()
        adapter = cls(OKXDemoTransport(credentials), credentials=credentials, websocket=OKXDemoWebSocket(credentials))
        adapter.order_margin_mode = "isolated"
        return adapter

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
            if isinstance(response, dict):
                code = str(response.get("code", "SCHEMA"))
                message = str(response.get("msg", "invalid response"))
                rows = response.get("data")
                if isinstance(rows, list) and rows and isinstance(rows[0], dict):
                    detail_code = rows[0].get("sCode")
                    detail_message = rows[0].get("sMsg")
                    if detail_code not in (None, "", "0") or detail_message:
                        message = f"{message}; detail={detail_code or 'SCHEMA'}:{detail_message or 'missing detail'}"
                raise AdapterError("okx-demo", code, message)
            raise AdapterError("okx-demo", "SCHEMA", "invalid response")

    @staticmethod
    def _timestamp(value: Any) -> datetime:
        return datetime.fromtimestamp(int(value) / 1000, timezone.utc) if value not in (None, "") else datetime.now(timezone.utc)

    @staticmethod
    def _status(value: Any) -> OrderStatus:
        return {"live": OrderStatus.OPEN, "partially_filled": OrderStatus.PARTIALLY_FILLED, "filled": OrderStatus.FILLED, "canceled": OrderStatus.CANCELED, "mmp_canceled": OrderStatus.CANCELED}.get(str(value), OrderStatus.UNKNOWN)

    @staticmethod
    def _side(value: Any) -> OrderSide:
        return OrderSide.BUY if str(value).lower() == "buy" else OrderSide.SELL

    @staticmethod
    def _client_order_id(value: str) -> str:
        """Return an OKX-compatible id while preserving planner uniqueness.

        The shared planner uses separators for readability, while OKX accepts
        only alphanumeric client order ids.  Removing separators keeps the
        digest unique and makes the id safe for both submit and cancel calls.
        """

        normalized = re.sub(r"[^A-Za-z0-9]", "", str(value))
        if not normalized or not normalized[0].isalpha():
            normalized = f"qbot{normalized}"
        return normalized[:32]

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
        modes: set[str] = set()
        leverages: list[Decimal] = []
        for item in response.get("data", []):
            quantity = self._decimal(item.get("pos"))
            if quantity == 0 or not item.get("instId"):
                continue
            symbol = str(item["instId"])
            if str(item.get("posSide", "net")).lower() == "short":
                quantity = -abs(quantity)
            margin_mode = str(item.get("mgnMode") or "").lower() or None
            if margin_mode:
                modes.add(margin_mode)
            leverage = self._decimal(item.get("lever")) if item.get("lever") not in (None, "") else None
            if leverage is not None and leverage > 0:
                leverages.append(leverage)
                self.leverage_by_symbol[symbol] = leverage
            if margin_mode:
                self.margin_mode_by_symbol[symbol] = margin_mode
            position_reasons: list[str] = []
            if margin_mode != self.required_margin_mode:
                position_reasons.append("MARGIN_MODE_NOT_ALLOWED")
            if leverage is None or leverage <= 0 or leverage > Decimal("2"):
                position_reasons.append("LEVERAGE_LIMIT_OR_UNVERIFIED")
            self.risk_configuration_by_symbol[symbol] = not position_reasons
            self.risk_configuration_reason_by_symbol[symbol] = tuple(position_reasons)
            result.append(Position(
                symbol,
                str(item.get("settleCcy") or "USDT"),
                quantity,
                self._decimal(item.get("avgPx")) if item.get("avgPx") else None,
                self._decimal(item.get("realizedPnl")),
                leverage,
                margin_mode,
                mark_price=self._decimal(item.get("markPx")) if item.get("markPx") not in (None, "") else None,
                unrealized_pnl=self._decimal(item.get("upl")) if item.get("upl") not in (None, "") else None,
                notional=self._decimal(item.get("notionalUsd") or item.get("notional")) if item.get("notionalUsd") not in (None, "") or item.get("notional") not in (None, "") else None,
                margin_used=self._decimal(item.get("imr") or item.get("margin")) if item.get("imr") not in (None, "") or item.get("margin") not in (None, "") else None,
            ))
        if modes:
            self.margin_mode = next(iter(modes)) if len(modes) == 1 else "MIXED"
        elif not self.risk_configuration_verified:
            self.margin_mode = None
        if leverages:
            self.max_position_leverage = max(leverages)
        elif not self.risk_configuration_verified:
            self.max_position_leverage = None
        if self.risk_configuration_by_symbol:
            self.risk_configuration_verified = all(self.risk_configuration_by_symbol.values())
        return result

    def verify_risk_configuration(
        self,
        symbols: Iterable[str],
        *,
        max_leverage: Decimal = Decimal("2"),
        required_margin_mode: str = "isolated",
    ) -> dict[str, Any]:
        """Verify OKX account settings before the first derivative order.

        This is intentionally read-only.  The bot never silently changes an
        account's margin mode or leverage; an operator must configure those in
        OKX first.  A flat account is valid once ``leverage-info`` confirms
        the requested isolated setting for each symbol.
        """

        self._private_guard()
        requested = tuple(dict.fromkeys(str(symbol) for symbol in symbols if str(symbol)))
        if not requested:
            self.risk_configuration_verified = True
            self.margin_mode = required_margin_mode
            self.max_position_leverage = max_leverage
            self.risk_configuration_at = datetime.now(timezone.utc)
            return {"verified": True, "symbols": [], "margin_mode": required_margin_mode, "max_leverage": str(max_leverage)}
        config = self.transport.request("GET", "/api/v5/account/config", private=True)
        self._check(config)
        config_rows = config.get("data", [])
        if not config_rows or not isinstance(config_rows[0], dict):
            raise AdapterError(self.name, "RISK_CONFIGURATION_UNVERIFIED", "OKX account configuration is unavailable")
        account_config = dict(config_rows[0])
        observed: list[Decimal] = []
        self.required_margin_mode = required_margin_mode
        self.order_margin_mode = required_margin_mode
        self.risk_configuration_by_symbol = {}
        self.risk_configuration_reason_by_symbol = {}
        self.leverage_by_symbol = {}
        self.margin_mode_by_symbol = {}
        for start in range(0, len(requested), 20):
            chunk = requested[start:start + 20]
            path = f"/api/v5/account/leverage-info?instId={','.join(chunk)}&mgnMode={required_margin_mode}"
            response = self.transport.request("GET", path, private=True)
            self._check(response)
            rows = [item for item in response.get("data", []) if isinstance(item, dict)]
            for symbol in chunk:
                matches = [item for item in rows if str(item.get("instId")) == symbol]
                reasons: list[str] = []
                if not matches:
                    reasons.append("RISK_CONFIGURATION_UNVERIFIED")
                for item in matches:
                    if str(item.get("mgnMode", "")).lower() != required_margin_mode.lower():
                        reasons.append("MARGIN_MODE_NOT_ALLOWED")
                        continue
                    self.margin_mode_by_symbol[symbol] = required_margin_mode
                    leverage = self._decimal(item.get("lever"))
                    if leverage <= 0:
                        reasons.append("LEVERAGE_LIMIT_OR_UNVERIFIED")
                        continue
                    self.leverage_by_symbol[symbol] = max(self.leverage_by_symbol.get(symbol, Decimal("0")), leverage)
                    if leverage > max_leverage:
                        reasons.append("LEVERAGE_LIMIT_OR_UNVERIFIED")
                        continue
                    observed.append(leverage)
                self.risk_configuration_by_symbol[symbol] = not reasons
                self.risk_configuration_reason_by_symbol[symbol] = tuple(dict.fromkeys(reasons))
        self.margin_mode = required_margin_mode
        self.max_position_leverage = max(observed) if observed else max_leverage
        self.risk_configuration_verified = bool(requested) and all(self.risk_configuration_by_symbol.get(symbol) is True for symbol in requested)
        self.risk_configuration_at = datetime.now(timezone.utc)
        return {
            "verified": self.risk_configuration_verified,
            "account_level": account_config.get("acctLv"),
            "position_mode": account_config.get("posMode"),
            "symbols": list(requested),
            "margin_mode": required_margin_mode,
            "max_leverage": str(self.max_position_leverage),
            "symbol_results": {
                symbol: {
                    "verified": self.risk_configuration_by_symbol.get(symbol, False),
                    "reasons": list(self.risk_configuration_reason_by_symbol.get(symbol, ())),
                }
                for symbol in requested
            },
        }

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
        row = self._fetch_ticker(symbol)
        bid, ask = self._decimal(row.get("bidPx")), self._decimal(row.get("askPx"))
        if bid <= 0 or ask <= 0 or ask < bid:
            raise AdapterError(self.name, "QUOTE_INVALID", f"invalid quote for {symbol}")
        return bid, ask

    def _fetch_ticker(self, symbol: str) -> dict[str, Any]:
        response = self.transport.request("GET", f"/api/v5/market/ticker?instId={symbol}")
        self._check(response)
        rows = response.get("data", [])
        if not rows or rows[0].get("bidPx") in (None, "") or rows[0].get("askPx") in (None, ""):
            raise AdapterError(self.name, "QUOTE_UNRESOLVED", f"no two-sided quote for {symbol}")
        return dict(rows[0])

    def _optional_public(self, path: str) -> dict[str, Any] | None:
        try:
            response = self.transport.request("GET", path)
            self._check(response)
            rows = response.get("data", [])
            return dict(rows[0]) if rows and isinstance(rows[0], dict) else None
        except Exception:  # noqa: BLE001 - optional public coverage must not block quote retrieval
            return None

    def fetch_market_context(self, symbol: str, *, bars: list[MarketBar] | None = None) -> MarketContext:
        """Read all as-of market inputs without turning unavailable data into zero."""

        observed_at = datetime.now(timezone.utc)
        ticker = self._fetch_ticker(symbol)
        quote_time = self._timestamp(ticker.get("ts")) if ticker.get("ts") not in (None, "") else observed_at
        quote = MarketQuote(symbol, self._decimal(ticker.get("bidPx")), self._decimal(ticker.get("askPx")), quote_time, "okx-demo-rest-ticker")
        instrument_type = self._instrument_types.get(symbol, "SWAP")
        funding_rate: Decimal | None = None
        funding_time: datetime | None = None
        mark_price: Decimal | None = None
        index_price: Decimal | None = None
        mark_source_time: datetime | None = None
        index_source_time: datetime | None = None
        coverage: dict[str, str] = {"quote": "OK", "closed_bar": "OK" if bars else "MISSING"}
        if instrument_type == "SPOT":
            coverage.update({"funding": "NOT_APPLICABLE", "mark_price": "NOT_APPLICABLE", "index_price": "NOT_APPLICABLE"})
        else:
            funding = self._optional_public(f"/api/v5/public/funding-rate?instId={symbol}")
            if funding and funding.get("fundingRate") not in (None, ""):
                funding_rate = self._decimal(funding.get("fundingRate"))
                funding_time = self._timestamp(funding.get("fundingTime") or funding.get("ts")) if funding.get("fundingTime") or funding.get("ts") else None
                coverage["funding"] = "OK" if funding_time is None or funding_time <= observed_at else "FUTURE_REJECTED"
                if coverage["funding"] == "FUTURE_REJECTED":
                    funding_rate = None
                    funding_time = None
            else:
                coverage["funding"] = "MISSING"
            mark = self._optional_public(f"/api/v5/public/mark-price?instType=SWAP&instId={symbol}")
            if mark and mark.get("markPx") not in (None, ""):
                mark_price = self._decimal(mark.get("markPx"))
                mark_source_time = self._timestamp(mark.get("ts")) if mark.get("ts") not in (None, "") else observed_at
                if mark_source_time > observed_at:
                    mark_price = None
                    mark_source_time = None
                    coverage["mark_price"] = "FUTURE_REJECTED"
                else:
                    coverage["mark_price"] = "OK"
            else:
                coverage["mark_price"] = "MISSING"
            index = self._optional_public(f"/api/v5/market/index-tickers?instId={symbol}")
            if index and index.get("idxPx") not in (None, ""):
                index_price = self._decimal(index.get("idxPx"))
                index_source_time = self._timestamp(index.get("ts")) if index.get("ts") not in (None, "") else observed_at
                if index_source_time > observed_at:
                    index_price = None
                    index_source_time = None
                    coverage["index_price"] = "FUTURE_REJECTED"
                else:
                    coverage["index_price"] = "OK"
            else:
                coverage["index_price"] = "MISSING"
        return MarketContext(symbol, quote, bars[-1].timestamp + __import__("datetime").timedelta(hours=1) if bars else None, funding_rate, funding_time, mark_price, index_price, observed_at, coverage, mark_source_time, index_source_time)

    def place_order(self, order: Order) -> Order:
        self._private_guard()
        inst_type = self._instrument_types.get(order.symbol, "SPOT")
        symbol_verified = self.risk_configuration_by_symbol.get(order.symbol)
        if inst_type != "SPOT" and symbol_verified is False:
            reasons = ",".join(self.risk_configuration_reason_by_symbol.get(order.symbol, ())) or "RISK_CONFIGURATION_UNVERIFIED"
            raise AdapterError(self.name, "RISK_CONFIGURATION_UNVERIFIED", f"OKX derivative order blocked for {order.symbol}: {reasons}")
        if inst_type != "SPOT" and symbol_verified is None and not self.risk_configuration_verified:
            raise AdapterError(self.name, "RISK_CONFIGURATION_UNVERIFIED", "verify isolated margin and leverage before placing a derivative order")
        if inst_type != "SPOT" and self.order_margin_mode != self.required_margin_mode:
            raise AdapterError(self.name, "MARGIN_MODE_NOT_ALLOWED", "OKX derivative orders must use the configured isolated margin mode")
        client_order_id = self._client_order_id(order.client_order_id)
        body: dict[str, Any] = {"instId": order.symbol, "tdMode": "cash" if inst_type == "SPOT" else self.order_margin_mode, "side": order.side.value.lower(), "ordType": "post_only" if order.post_only else "limit" if order.order_type == OrderType.LIMIT else "market", "sz": str(order.quantity), "clOrdId": client_order_id}
        if order.price is not None:
            body["px"] = str(order.price)
        if order.reduce_only:
            body["reduceOnly"] = "true"
        response = self.transport.request("POST", "/api/v5/trade/order", body=body, private=True)
        self._check(response)
        rows = response.get("data", [])
        if not rows or not rows[0].get("ordId") or str(rows[0].get("sCode", "0")) != "0":
            raise AdapterError(self.name, str(rows[0].get("sCode", "SCHEMA")) if rows else "SCHEMA", str(rows[0].get("sMsg", "order response missing ordId")) if rows else "order response missing ordId")
        self._order_symbols[client_order_id] = order.symbol
        return Order(client_order_id, order.symbol, order.side, order.order_type, order.quantity, order.created_at, order.price, order.reduce_only, order.post_only, OrderStatus.OPEN, str(rows[0]["ordId"]), metadata={"raw": response})

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

    def _server_time_sample(self) -> tuple[datetime, Decimal]:
        before = datetime.now(timezone.utc)
        response = self.transport.request("GET", "/api/v5/public/time")
        after = datetime.now(timezone.utc)
        self._check(response)
        rows = response.get("data", [])
        if not rows or not rows[0].get("ts"):
            raise AdapterError(self.name, "SCHEMA", "OKX returned no server time")
        server = self._timestamp(rows[0]["ts"])
        midpoint = before + (after - before) / 2
        drift = Decimal(str((server - midpoint).total_seconds()))
        if hasattr(self.transport, "set_clock_offset_ms"):
            offset_ms = int((server - midpoint).total_seconds() * 1000)
            self.transport.set_clock_offset_ms(offset_ms)
            if self.websocket is not None:
                self.websocket.set_clock_offset_ms(offset_ms)
        return server, drift

    def get_server_time_drift_seconds(self) -> Decimal:
        _server, drift = self._server_time_sample()
        return drift

    def get_server_time(self) -> datetime:
        server, _drift = self._server_time_sample()
        return server

    def load_all_instruments_for_preflight(self) -> list[Instrument]:
        return self.load_all_instruments()

    async def stream_messages(self, stop: Any, on_message: Any, on_error: Any | None = None) -> None:
        if self.websocket is None:
            raise AdapterError(self.name, "WEBSOCKET_NOT_CONFIGURED", "OKX Demo private WebSocket is not configured")
        # OKX requires instType on position/order subscriptions. The Demo
        # account may not be entitled to the fills channel; executions are
        # still reconciled from the authenticated REST fills endpoint.
        channels = [
            {"channel": "account"},
            {"channel": "positions", "instType": "SWAP"},
            {"channel": "orders", "instType": "SWAP"},
        ]
        await self.websocket.run(on_message, stop, channels, on_error=on_error)


__all__ = ["OKXAdapter"]
