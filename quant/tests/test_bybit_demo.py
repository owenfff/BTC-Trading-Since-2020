from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.balance import Balance
from quant_bot.domain.fill import Fill
from quant_bot.domain.order import Order, OrderSide, OrderType
from quant_bot.domain.position import Position
from quant_bot.execution.target_planner import plan_target_order
from quant_bot.exchanges.bybit import BybitAdapter
from quant_bot.exchanges.bybit_http import BybitCredentials, BybitDemoTransport, assert_demo_url, bybit_signature, bybit_websocket_signature
from quant_bot.exchanges.bybit_ws import BybitDemoWebSocket
from quant_bot.exchanges.http import AdapterError, FakeTransport
from quant_bot.testnet_runtime import _public_account_snapshot
from frontend.server import status_payload


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


def test_bybit_get_retries_transient_network_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        headers: dict[str, str] = {}

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"retCode":0,"result":{"timeNano":"1700000000000000000"}}'

    attempts = 0

    def flaky_urlopen(*args: object, **kwargs: object) -> Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            import urllib.error

            raise urllib.error.URLError(TimeoutError("timed out"))
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", flaky_urlopen)
    monkeypatch.setattr("quant_bot.exchanges.bybit_http.time.sleep", lambda seconds: None)
    transport = BybitDemoTransport(BybitCredentials("key", "secret"))
    result = transport.request("GET", "/v5/market/time")
    assert result["retCode"] == 0
    assert attempts == 2


def test_private_requests_apply_server_clock_offset(monkeypatch: pytest.MonkeyPatch) -> None:
    class Response:
        headers: dict[str, str] = {}

        def __enter__(self) -> "Response":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"retCode":0,"result":{"list":[]}}'

    captured: dict[str, str] = {}

    def fake_urlopen(request: object, **kwargs: object) -> Response:
        captured.update({key.lower(): value for key, value in request.header_items()})
        return Response()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    transport = BybitDemoTransport(BybitCredentials("key", "secret"), clock_ms=lambda: 1_700_000_000_000)
    transport.set_clock_offset_ms(2_500)
    transport.request("GET", "/v5/account/wallet-balance?accountType=UNIFIED", private=True)
    assert captured["x-bapi-timestamp"] == "1700000002500"


def test_frontend_dashboard_is_read_only_and_never_exposes_credentials() -> None:
    payload = status_payload()
    serialized = json.dumps(payload, ensure_ascii=False)
    assert payload["dashboard_role"] == "FRONTEND_ONLY"
    assert payload["exchange_connection"] == "NONE_FROM_THIS_SERVER"
    assert payload["trading_enabled_here"] is False
    assert "BYBIT_DEMO_API_KEY" not in serialized
    assert "BYBIT_DEMO_API_SECRET" not in serialized


def test_account_snapshot_is_sanitized_for_dashboard() -> None:
    order = _order()
    fill = Fill("fill-1", "client-1", "BTCUSDT", OrderSide.BUY, Decimal("1"), Decimal("100"), Decimal("0.1"), "USDT", datetime(2024, 1, 1, tzinfo=timezone.utc))
    snapshot = _public_account_snapshot({"ok": True, "balances": [Balance("USDT", "10", "9")], "positions": [Position("BTCUSDT", "USDT", "1", "100", "0")], "open_orders": [order], "recent_fills": [fill]}, Decimal("10"))
    assert snapshot["equity"] == "10"
    assert snapshot["balances"][0]["available"] == "9"
    assert snapshot["positions"][0]["quantity"] == "1"
    assert snapshot["open_orders"][0]["client_order_id"] == "client-1"
    assert snapshot["recent_fills"][0]["event_id"] == "fill-1"
    assert "raw" not in json.dumps(snapshot)


def test_private_ws_auth_and_duplicate_event_protection() -> None:
    ws = BybitDemoWebSocket(BybitCredentials("key", "secret"), clock_ms=lambda: 1_700_000_000_000)
    auth = ws.auth_message()
    assert auth["op"] == "auth"
    assert auth["args"][0] == "key"
    message = {"topic": "order", "type": "snapshot", "data": [{"orderId": "1"}]}
    assert ws.accept_message(message)
    assert not ws.accept_message(message)
    assert ws.latest["order"][0]["orderId"] == "1"


def test_private_ws_accepts_sync_runtime_callback() -> None:
    class Socket:
        async def send(self, value: str) -> None:
            return None

        async def recv(self) -> str:
            return json.dumps({"success": True, "topic": "wallet", "data": [{"coin": "USDT"}]})

        async def close(self) -> None:
            return None

    async def fake_connect(*args: object, **kwargs: object) -> Socket:
        return Socket()

    ws = BybitDemoWebSocket(BybitCredentials("key", "secret"), connect_factory=fake_connect)
    stop = asyncio.Event()
    received: list[dict[str, object]] = []

    def on_message(message: dict[str, object]) -> None:
        received.append(message)
        stop.set()

    asyncio.run(ws.run(on_message, stop, []))
    assert received[0]["success"] is True


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


def test_adapter_enables_inverse_settlement_collateral() -> None:
    transport = FakeTransport({
        ("GET", "/v5/account/collateral-info?currency=ADA"): {"retCode": 0, "result": {"list": [{"currency": "ADA", "marginCollateral": True, "collateralSwitch": False}]}},
        ("POST", "/v5/account/set-collateral-switch"): {"retCode": 0, "result": {}},
    })
    adapter = BybitAdapter(transport, credentials=BybitCredentials("key", "secret"))
    assert adapter.ensure_collateral_coins({"ADA", "USDT"}) == {"ADA": "ENABLED", "USDT": "INHERENT_COLLATERAL"}


def test_target_planner_uses_decimal_reduce_only_and_splits_flip() -> None:
    instrument = Instrument("BTCUSDT", InstrumentType.LINEAR_PERPETUAL, "BTC", "USDT", "USDT", Decimal("0.1"), Decimal("0.001"), Decimal("0.001"), Decimal("0"), contract_multiplier=Decimal("1"))
    plan = plan_target_order(instrument, current_contracts=Decimal("1"), target_exposure=Decimal("0.001"), equity=Decimal("1000"), reference_price=Decimal("100"), bid=Decimal("99.9"), ask=Decimal("100.1"), decision_time=datetime.now(timezone.utc), max_target_exposure=Decimal("0.01"))
    assert plan is not None
    assert plan.reduce_only
    assert not plan.post_only
    flip = plan_target_order(instrument, current_contracts=Decimal("1"), target_exposure=Decimal("-0.01"), equity=Decimal("1000"), reference_price=Decimal("100"), bid=Decimal("99.9"), ask=Decimal("100.1"), decision_time=datetime.now(timezone.utc), max_target_exposure=Decimal("0.01"))
    assert flip is not None and flip.reason == "FLIP_REDUCE_FIRST" and flip.quantity == Decimal("1.000")
