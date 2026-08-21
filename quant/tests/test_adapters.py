from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from quant_bot.domain.order import Order, OrderSide, OrderType
from quant_bot.exchanges.bitmex import BitmexAdapter
from quant_bot.exchanges.bybit import BybitAdapter
from quant_bot.exchanges.http import AdapterError, FakeTransport


def order() -> Order:
    return Order("client-1", "XBTUSD", OrderSide.BUY, OrderType.LIMIT, Decimal("100"), datetime(2020, 1, 1, tzinfo=timezone.utc), price=Decimal("100"))


def test_bitmex_public_and_mock_private_normalization() -> None:
    transport = FakeTransport({("GET", "/api/v1/instrument"): [{"symbol": "XBTUSD", "typ": "FFWCSX", "underlying": "XBT", "quoteCurrency": "USD", "settlCurrency": "XBT", "tickSize": 0.1, "lotSize": 100}], ("POST", "/api/v1/order"): {"orderID": "ex-1"}})
    adapter = BitmexAdapter(transport)
    assert adapter.load_instruments()[0].instrument_type.value == "INVERSE_PERPETUAL"
    try:
        adapter.place_order(order())
    except AdapterError as error:
        assert error.code == "DEMO_CREDENTIALS_REQUIRED"
    else:
        raise AssertionError("private adapter call must require credentials")
    assert BitmexAdapter(transport, credentials="MOCK").place_order(order()).exchange_order_id == "ex-1"


def test_bybit_public_and_mock_private_error_normalization() -> None:
    transport = FakeTransport({("GET", "/v5/market/instruments-info?category=linear"): {"retCode": 0, "result": {"list": [{"symbol": "BTCUSDT", "baseCoin": "BTC", "quoteCoin": "USDT", "settleCoin": "USDT", "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001"}, "priceFilter": {"tickSize": "0.1"}}]}}, ("POST", "/v5/order/create"): {"retCode": 10001, "retMsg": "invalid request"}})
    adapter = BybitAdapter(transport)
    assert adapter.load_instruments()[0].canonical_symbol == "BTCUSDT"
    try:
        BybitAdapter(transport, credentials="MOCK").place_order(order())
    except AdapterError as error:
        assert error.code == "10001"
    else:
        raise AssertionError("mock error was not normalized")
