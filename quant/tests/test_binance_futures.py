from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quant_bot.domain.order import Order, OrderSide, OrderType
from quant_bot.exchanges.binance_futures import BinanceFuturesAdapter
from quant_bot.exchanges.binance_futures_http import BinanceFuturesTestnetCredentials, BinanceFuturesTestnetTransport, assert_binance_futures_testnet_url, assert_binance_futures_testnet_ws_url, binance_futures_signature
from quant_bot.exchanges.binance_futures_ws import BinanceFuturesTestnetWebSocket
from quant_bot.exchanges.http import AdapterError, FakeTransport
from quant_bot.venue_runtime import build_venue_symbol_mapping


def _order(symbol: str = "BTCUSDT") -> Order:
    return Order("futures-client-1", symbol, OrderSide.BUY, OrderType.LIMIT, Decimal("0.001"), datetime(2024, 1, 1, tzinfo=timezone.utc), price=Decimal("100"), post_only=True)


def test_futures_signature_and_testnet_guards() -> None:
    assert binance_futures_signature("secret", "symbol=BTCUSDT&timestamp=1700000000000") == "6244d11c958f45ac56733152cb3cb1831d23a2b3709b3a88b8b42a072aceb410"
    assert_binance_futures_testnet_url()
    assert_binance_futures_testnet_ws_url()
    with pytest.raises(AdapterError) as error:
        assert_binance_futures_testnet_url("https://fapi.binance.com")
    assert error.value.code == "MAINNET_OR_UNTRUSTED_ENDPOINT"
    with pytest.raises(AdapterError):
        assert_binance_futures_testnet_ws_url("wss://fstream.binance.com/ws")


def test_futures_credentials_are_local_and_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BINANCE_FUTURES_TESTNET_API_KEY", raising=False)
    monkeypatch.delenv("BINANCE_FUTURES_TESTNET_API_SECRET", raising=False)
    with pytest.raises(AdapterError) as error:
        BinanceFuturesTestnetCredentials.from_environment()
    assert error.value.code == "TESTNET_CREDENTIALS_REQUIRED"
    assert "secret-value" not in repr(BinanceFuturesTestnetCredentials("key", "secret-value"))


def test_futures_adapter_maps_linear_perpetual_and_reduce_only_order() -> None:
    transport = FakeTransport({
        ("GET", "/fapi/v1/exchangeInfo"): {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING", "contractType": "PERPETUAL", "baseAsset": "BTC", "quoteAsset": "USDT", "marginAsset": "USDT", "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.1"}, {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"}, {"filterType": "MIN_NOTIONAL", "notional": "5"}]}]},
        ("POST", "/fapi/v1/order"): {"symbol": "BTCUSDT", "orderId": 456, "clientOrderId": "futures-client-1", "status": "NEW"},
    })
    adapter = BinanceFuturesAdapter(transport, credentials=BinanceFuturesTestnetCredentials("key", "secret"))
    instrument = adapter.load_instruments()[0]
    assert instrument.instrument_type.value == "LINEAR_PERPETUAL"
    assert instrument.contract_multiplier == Decimal("1")
    accepted = adapter.place_order(Order("futures-client-1", "BTCUSDT", OrderSide.SELL, OrderType.LIMIT, Decimal("0.001"), datetime(2024, 1, 1, tzinfo=timezone.utc), price=Decimal("100"), reduce_only=True, post_only=True))
    assert accepted.exchange_order_id == "456"
    body = transport.calls[-1][3]
    assert body["timeInForce"] == "GTX"
    assert body["reduceOnly"] == "true"
    assert body["positionSide"] == "BOTH"


def test_futures_private_stream_deduplicates_and_uses_testnet_listen_key() -> None:
    class ListenKeyTransport(FakeTransport):
        def request_api_key(self, method: str, path: str) -> object:
            return self.request(method, path, private=False)

    transport = ListenKeyTransport({("POST", "/fapi/v1/listenKey"): {"listenKey": "abc"}})
    adapter_ws = BinanceFuturesTestnetWebSocket(BinanceFuturesTestnetTransport(BinanceFuturesTestnetCredentials("key", "secret")))
    adapter_ws.transport = transport  # type: ignore[assignment]
    assert adapter_ws._create_listen_key() == "abc"
    message = {"e": "ORDER_TRADE_UPDATE", "i": 1}
    assert adapter_ws.accept_message(message) is True
    assert adapter_ws.accept_message(message) is False
    assert transport.calls[-1][1] == "/fapi/v1/listenKey"


def test_futures_mapping_never_marks_spot_as_derivative() -> None:
    class Bundle:
        symbols = ("XBTUSD",)
        symbol_policy = {"XBTUSD": {"instrument_class": "DERIVATIVE"}}

    mapping = build_venue_symbol_mapping(Bundle(), "binance-futures-testnet", [])
    assert mapping["allowed_count"] == 0
    assert mapping["symbols"][0]["status"] == "UNAVAILABLE_ON_VENUE"
