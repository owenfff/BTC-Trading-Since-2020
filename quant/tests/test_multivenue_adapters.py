from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest

from quant_bot.domain.order import Order, OrderSide, OrderType
from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.exchanges.binance import BinanceSpotAdapter
from quant_bot.exchanges.binance_http import BinanceSpotTestnetTransport, BinanceTestnetCredentials, assert_binance_spot_testnet_url, assert_binance_spot_testnet_ws_url, binance_signature
from quant_bot.exchanges.binance_ws import BinanceSpotTestnetWebSocket
from quant_bot.exchanges.http import AdapterError, FakeTransport
from quant_bot.exchanges.okx import OKXAdapter
from quant_bot.exchanges.okx_http import OKXDemoCredentials, assert_okx_demo_url, okx_signature
from quant_bot.exchanges.okx_ws import OKXDemoWebSocket
from quant_bot.execution.target_planner import plan_spot_order
from quant_bot.venue_runtime import build_venue_symbol_mapping


def _order(symbol: str) -> Order:
    return Order("client-venue-1", symbol, OrderSide.BUY, OrderType.LIMIT, Decimal("0.01"), datetime(2024, 1, 1, tzinfo=timezone.utc), price=Decimal("100"))


def test_okx_signature_and_demo_endpoint_guard() -> None:
    assert okx_signature("secret", "2020-12-08T09:08:57.715Z", "GET", "/api/v5/account/balance") == "5ktoTKif8DCJlIPb/3Kfd1A17bIRye6jpS9QBWj+9AU="
    assert_okx_demo_url()
    with pytest.raises(AdapterError) as error:
        assert_okx_demo_url("https://www.okx.com")
    assert error.value.code == "MAINNET_OR_UNTRUSTED_ENDPOINT"


def test_okx_demo_uses_global_demo_rest_and_websocket_hosts() -> None:
    from quant_bot.exchanges.okx_http import OKX_DEMO_PRIVATE_WS_URL, OKX_DEMO_REST_BASE_URL

    assert OKX_DEMO_REST_BASE_URL == "https://openapi.okx.com"
    assert OKX_DEMO_PRIVATE_WS_URL == "wss://wspap.okx.com:8443/ws/v5/private"


def test_binance_hmac_and_testnet_endpoint_guard() -> None:
    assert binance_signature("secret", "symbol=BTCUSDT&timestamp=1700000000000") == "6244d11c958f45ac56733152cb3cb1831d23a2b3709b3a88b8b42a072aceb410"
    assert_binance_spot_testnet_url()
    with pytest.raises(AdapterError) as error:
        assert_binance_spot_testnet_url("https://api.binance.com")
    assert error.value.code == "MAINNET_OR_UNTRUSTED_ENDPOINT"


def test_venue_credentials_are_redacted(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OKX_DEMO_API_KEY", raising=False)
    monkeypatch.delenv("OKX_DEMO_API_SECRET", raising=False)
    monkeypatch.delenv("OKX_DEMO_API_PASSPHRASE", raising=False)
    with pytest.raises(AdapterError) as error:
        OKXDemoCredentials.from_environment()
    assert error.value.code == "DEMO_CREDENTIALS_REQUIRED"
    assert "secret-value" not in repr(OKXDemoCredentials("key", "secret-value", "pass-value"))
    assert "secret-value" not in repr(BinanceTestnetCredentials("key", "secret-value"))


def test_okx_adapter_maps_instruments_and_places_demo_order() -> None:
    transport = FakeTransport({
        ("GET", "/api/v5/public/instruments?instType=SPOT"): {"code": "0", "data": [{"instType": "SPOT", "instId": "BTC-USDT", "baseCcy": "BTC", "quoteCcy": "USDT", "tickSz": "0.1", "lotSz": "0.001", "minSz": "0.001", "state": "live"}]},
        ("GET", "/api/v5/public/instruments?instType=SWAP"): {"code": "0", "data": []},
        ("POST", "/api/v5/trade/order"): {"code": "0", "data": [{"ordId": "okx-order-1", "sCode": "0"}]},
    })
    adapter = OKXAdapter(transport, credentials=OKXDemoCredentials("key", "secret", "pass"))
    instrument = adapter.load_all_instruments()[0]
    assert instrument.canonical_symbol == "BTC-USDT"
    assert instrument.instrument_type.value == "SPOT"
    accepted = adapter.place_order(_order("BTC-USDT"))
    assert accepted.exchange_order_id == "okx-order-1"
    assert transport.calls[-1][3]["tdMode"] == "cash"


def test_binance_adapter_maps_instruments_and_places_testnet_order() -> None:
    transport = FakeTransport({
        ("GET", "/api/v3/exchangeInfo"): {"symbols": [{"symbol": "BTCUSDT", "status": "TRADING", "baseAsset": "BTC", "quoteAsset": "USDT", "isSpotTradingAllowed": True, "filters": [{"filterType": "PRICE_FILTER", "tickSize": "0.1"}, {"filterType": "LOT_SIZE", "minQty": "0.001", "stepSize": "0.001"}, {"filterType": "MIN_NOTIONAL", "minNotional": "5"}]}]},
        ("POST", "/api/v3/order"): {"symbol": "BTCUSDT", "orderId": 123, "clientOrderId": "client-venue-1", "status": "NEW"},
    })
    adapter = BinanceSpotAdapter(transport, credentials=BinanceTestnetCredentials("key", "secret"))
    instrument = adapter.load_instruments()[0]
    assert instrument.canonical_symbol == "BTCUSDT"
    assert instrument.minimum_notional == Decimal("5")
    accepted = adapter.place_order(_order("BTCUSDT"))
    assert accepted.exchange_order_id == "123"
    assert transport.calls[-1][3]["type"] == "LIMIT"


def test_binance_transport_never_accepts_mainnet_base_url() -> None:
    with pytest.raises(AdapterError) as error:
        BinanceSpotTestnetTransport(BinanceTestnetCredentials("key", "secret"), base_url="https://api.binance.com")
    assert error.value.code == "MAINNET_OR_UNTRUSTED_ENDPOINT"


def test_private_websocket_guards_auth_and_deduplication() -> None:
    okx = OKXDemoWebSocket(OKXDemoCredentials("key", "secret", "pass"), clock_seconds=lambda: 1700000000)
    assert okx.login_message()["op"] == "login"
    message = {"event": "login", "code": "0"}
    assert okx.accept_message(message) is True
    assert okx.accept_message(message) is False

    assert_binance_spot_testnet_ws_url()
    with pytest.raises(AdapterError) as error:
        assert_binance_spot_testnet_ws_url("wss://stream.binance.com/ws")
    assert error.value.code == "MAINNET_OR_UNTRUSTED_ENDPOINT"
    binance = BinanceSpotTestnetWebSocket(BinanceSpotTestnetTransport(BinanceTestnetCredentials("key", "secret")))
    assert binance.accept_message({"e": "executionReport", "i": 1}) is True
    assert binance.accept_message({"e": "executionReport", "i": 1}) is False


def test_binance_region_block_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    import urllib.error

    class BlockedResponse:
        def read(self) -> bytes:
            return b"region blocked"

        def close(self) -> None:
            return None

    def blocked_urlopen(*args: object, **kwargs: object) -> object:
        raise urllib.error.HTTPError("https://testnet.binance.vision", 451, "Unavailable For Legal Reasons", {}, BlockedResponse())

    monkeypatch.setattr("urllib.request.urlopen", blocked_urlopen)
    transport = BinanceSpotTestnetTransport(BinanceTestnetCredentials("key", "secret"))
    with pytest.raises(AdapterError) as error:
        transport.request("GET", "/api/v3/exchangeInfo")
    assert error.value.code == "BINANCE_REGION_BLOCKED"


def test_spot_planner_uses_wallet_quantity_and_never_creates_reduce_only() -> None:
    instrument = Instrument("BTCUSDT", InstrumentType.SPOT, "BTC", "USDT", "USDT", "0.1", "0.001", "0.001", "5")
    plan = plan_spot_order(
        instrument,
        current_base_quantity=Decimal("0.01"),
        target_exposure=Decimal("0.10"),
        equity=Decimal("1000"),
        reference_price=Decimal("100"),
        bid=Decimal("99.9"),
        ask=Decimal("100.1"),
        decision_time=datetime(2024, 1, 1, tzinfo=timezone.utc),
    )
    assert plan is not None
    assert plan.side == OrderSide.BUY
    assert plan.reduce_only is False
    assert plan.post_only is True


def test_cross_venue_mapping_marks_spot_substitution_explicitly() -> None:
    class Bundle:
        symbols = ("XBTUSD", "ETHUSD")
        symbol_policy = {"XBTUSD": {"instrument_class": "DERIVATIVE"}, "ETHUSD": {"instrument_class": "DERIVATIVE"}}

    instruments = [
        Instrument("BTCUSDT", InstrumentType.SPOT, "BTC", "USDT", "USDT", "0.1", "0.001", "0.001", "5", metadata={"status": "TRADING"}),
        Instrument("ETHUSDT", InstrumentType.SPOT, "ETH", "USDT", "USDT", "0.1", "0.001", "0.001", "5", metadata={"status": "TRADING"}),
    ]
    mapping = build_venue_symbol_mapping(Bundle(), "binance-spot-testnet", instruments)
    assert mapping["spot_approximation_count"] == 2
    assert {row["status"] for row in mapping["symbols"]} == {"ALLOW_SPOT_BEHAVIOR_APPROXIMATION"}
