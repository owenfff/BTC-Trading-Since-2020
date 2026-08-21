from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.order import Order, OrderSide, OrderType
from quant_bot.execution.target_planner import plan_target_order
from quant_bot.exchanges.bybit import BybitAdapter
from quant_bot.exchanges.bybit_http import BybitCredentials, BybitDemoTransport, assert_demo_url, bybit_signature, bybit_websocket_signature
from quant_bot.exchanges.bybit_ws import BybitDemoWebSocket
from quant_bot.exchanges.http import AdapterError, FakeTransport


def _order() -> Order:
    return Order("client-1", "BTCUSDT", OrderSide.BUY, OrderType.LIMIT, Decimal("1"), datetime(2024, 1, 1, tzinfo=timezone.utc), price=Decimal("100"))


def test_bybit_signature_vector_and_demo_url_guard() -> None:
    assert bybit_signature("secret", 1700000000000, "key", 5000, "category=linear") == "e6c3e971c517d999338172674f1c633b9016addf8f8c632372232076767b4c07"
    with pytest.raises(AdapterError) as error:
        assert_demo_url("https://api.bybit.com")
    assert error.value.code == "MAINNET_OR_UNTRUSTED_ENDPOINT"
    assert bybit_websocket_signature("secret", 1700000000000) == "9baf584ddf7a063dffe910d97ce4eac0cf7064058356de8b8d92f028e5ad936f"


def test_missing_demo_credentials_and_repr_are_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BYBIT_DEMO_API_KEY", raising=False)
    monkeypatch.delenv("BYBIT_DEMO_API_SECRET", raising=False)
    with pytest.raises(AdapterError) as error:
        BybitCredentials.from_environment()
    assert error.value.code == "DEMO_CREDENTIALS_REQUIRED"
    assert "secret-value" not in repr(BybitCredentials("key-value", "secret-value"))
    assert "secret-value" not in str(error.value)


def test_bybit_region_block_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    class BlockedResponse:
        def read(self) -> bytes:
            return b'{"error":"The Amazon CloudFront distribution is configured to block access from your country."}'

    class BlockedHttpError(Exception):
        code = 403

        def read(self) -> bytes:
            return BlockedResponse().read()

    import urllib.error

    def blocked_urlopen(*args: object, **kwargs: object) -> object:
        raise urllib.error.HTTPError("https://api-demo.bybit.com", 403, "Forbidden", {}, BlockedResponse())

    monkeypatch.setattr("urllib.request.urlopen", blocked_urlopen)
    transport = BybitDemoTransport(BybitCredentials("key", "secret"))
    with pytest.raises(AdapterError) as error:
        transport.request("GET", "/v5/market/instruments-info?category=linear")
    assert error.value.code == "BYBIT_REGION_BLOCKED"
    assert "secret" not in str(error.value)


def test_private_ws_auth_and_duplicate_event_protection() -> None:
    ws = BybitDemoWebSocket(BybitCredentials("key", "secret"), clock_ms=lambda: 1_700_000_000_000)
    auth = ws.auth_message()
    assert auth["op"] == "auth"
    assert auth["args"][0] == "key"
    message = {"topic": "order", "type": "snapshot", "data": [{"orderId": "1"}]}
    assert ws.accept_message(message)
    assert not ws.accept_message(message)
    assert ws.latest["order"][0]["orderId"] == "1"


def test_adapter_maps_instruments_and_order_lifecycle() -> None:
    transport = FakeTransport({
        ("GET", "/v5/market/instruments-info?category=linear"): {"retCode": 0, "result": {"list": [{"symbol": "BTCUSDT", "baseCoin": "BTC", "quoteCoin": "USDT", "settleCoin": "USDT", "contractValue": "1", "status": "Trading", "lotSizeFilter": {"qtyStep": "0.001", "minOrderQty": "0.001"}, "priceFilter": {"tickSize": "0.1"}}]}},
        ("POST", "/v5/order/create"): {"retCode": 0, "result": {"orderId": "exchange-1"}},
    })
    adapter = BybitAdapter(transport, credentials=BybitCredentials("key", "secret"))
    instrument = adapter.load_instruments()[0]
    assert instrument.instrument_type == InstrumentType.LINEAR_PERPETUAL
    assert instrument.terms_complete
    accepted = adapter.place_order(_order())
    assert accepted.exchange_order_id == "exchange-1"
    assert transport.calls[-1][3]["orderLinkId"] == "client-1"


def test_target_planner_uses_decimal_reduce_only_and_splits_flip() -> None:
    instrument = Instrument("BTCUSDT", InstrumentType.LINEAR_PERPETUAL, "BTC", "USDT", "USDT", Decimal("0.1"), Decimal("0.001"), Decimal("0.001"), Decimal("0"), contract_multiplier=Decimal("1"))
    plan = plan_target_order(instrument, current_contracts=Decimal("1"), target_exposure=Decimal("0.001"), equity=Decimal("1000"), reference_price=Decimal("100"), bid=Decimal("99.9"), ask=Decimal("100.1"), decision_time=datetime.now(timezone.utc), max_target_exposure=Decimal("0.01"))
    assert plan is not None
    assert plan.reduce_only
    assert not plan.post_only
    flip = plan_target_order(instrument, current_contracts=Decimal("1"), target_exposure=Decimal("-0.01"), equity=Decimal("1000"), reference_price=Decimal("100"), bid=Decimal("99.9"), ask=Decimal("100.1"), decision_time=datetime.now(timezone.utc), max_target_exposure=Decimal("0.01"))
    assert flip is not None and flip.reason == "FLIP_REDUCE_FIRST" and flip.quantity == Decimal("1.000")
