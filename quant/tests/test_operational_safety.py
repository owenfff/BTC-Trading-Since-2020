from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.market_data import MarketBar, MarketContext, MarketQuote
from quant_bot.domain.order import Order, OrderSide, OrderType
from quant_bot.exchanges.http import AdapterError, FakeTransport
from quant_bot.exchanges.okx import OKXAdapter
from quant_bot.risk.runtime_risk import RuntimeRiskState
from quant_bot.risk.testnet_gate import check_testnet_order
from quant_bot.strategy.deployment import load_deployment_bundle
from quant_bot.strategy.realtime_features import RealtimeFeatureEngine


def _envelope() -> dict[str, object]:
    return {"per_symbol_target_exposure": {"BTCUSDT": {"p99_abs_target_exposure": "1"}}, "historical_simultaneous_total_exposure_cap": "2"}


def test_runtime_risk_blocks_daily_loss_and_preserves_positions() -> None:
    state = RuntimeRiskState()
    state.update(Decimal("1000"), now=datetime(2026, 1, 1, tzinfo=timezone.utc))
    state.update(Decimal("979"), now=datetime(2026, 1, 1, 0, 5, tzinfo=timezone.utc))
    assert state.daily_loss == Decimal("0.021")
    assert not state.safe()
    assert "DAILY_LOSS_LIMIT" in state.block_reasons
    assert state.snapshot()["kill_switch_engaged"] is False


def test_runtime_risk_rechecks_transient_failures_after_restart() -> None:
    state = RuntimeRiskState()
    state.trigger("PRIVATE_WEBSOCKET_ERROR")
    state.trigger("CONSECUTIVE_ORDER_REJECTS")
    state.restore(state.snapshot())
    assert "PRIVATE_WEBSOCKET_ERROR" not in state.block_reasons
    assert "CONSECUTIVE_ORDER_REJECTS" in state.block_reasons


def test_risk_gate_blocks_stale_market_clock_and_kill_switch() -> None:
    decision = check_testnet_order(
        enable_orders=True,
        confirm_testnet=True,
        symbol="BTCUSDT",
        target_exposure=Decimal("0.1"),
        total_target_exposure=Decimal("0.1"),
        envelope=_envelope(),
        reconciliation_ok=True,
        websocket_connected=True,
        market_fresh=False,
        clock_drift_seconds=Decimal("6"),
        kill_switch_engaged=True,
    )
    assert not decision.allowed
    assert {"MARKET_DATA_STALE", "CLOCK_DRIFT", "MANUAL_KILL_SWITCH"}.issubset(decision.reasons)


def test_market_context_tracks_quote_and_bar_age() -> None:
    now = datetime.now(timezone.utc)
    context = MarketContext(
        "BTCUSDT-SWAP",
        MarketQuote("BTCUSDT-SWAP", "99", "100", now - timedelta(seconds=10), "fixture"),
        now - timedelta(minutes=30),
        None,
        None,
        None,
        None,
        now,
        {"quote": "OK", "closed_bar": "OK", "funding": "MISSING", "mark_price": "MISSING", "index_price": "MISSING"},
    )
    assert context.quote_age_seconds(now) == pytest.approx(10)
    assert context.closed_bar_age_seconds(now) == pytest.approx(1800)


def test_realtime_behavior_state_is_not_lost_on_restore() -> None:
    instrument = Instrument("BTCUSDT", InstrumentType.LINEAR_PERPETUAL, "BTC", "USDT", "USDT", "0.1", "1", "1", "0")
    engine = RealtimeFeatureEngine(instrument)
    engine.record_action("OPEN_LONG", fee=0.3, realised_outcome=1.2)
    snapshot = engine.snapshot()
    restored = RealtimeFeatureEngine(instrument)
    restored.restore(snapshot)
    assert restored.latest_action == "OPEN_LONG"
    assert restored.add_count == 1
    assert restored.fees == pytest.approx(0.3)
    assert restored.realised_outcome == pytest.approx(1.2)


def test_realtime_features_reject_future_public_context() -> None:
    now = datetime(2026, 1, 1, 12, tzinfo=timezone.utc)
    instrument = Instrument("BTCUSDT", InstrumentType.LINEAR_PERPETUAL, "BTC", "USDT", "USDT", "0.1", "1", "1", "0")
    engine = RealtimeFeatureEngine(instrument)
    bars = [MarketBar("BTCUSDT", now - timedelta(hours=2 + index), "100", "101", "99", "100", "10") for index in range(40)]
    engine.ingest_closed_bars(bars, now=now)
    engine.attach_market_context(
        funding_rate=0.001,
        funding_source_time=now + timedelta(minutes=1),
        mark_price=101,
        index_price=100,
    )
    engine.attach_market_source_times(mark_source_time=now + timedelta(minutes=1), index_source_time=now + timedelta(minutes=1))
    features = engine.build_input(decision_time=now, current_qty=Decimal("0"), current_equity=Decimal("1000")).features
    assert features["feature_funding_rate"] is None
    assert features["feature_funding_rate_missing"] is True
    assert features["feature_mark_index_basis"] is None
    assert features["feature_mark_index_basis_missing"] is True


def test_realtime_features_keep_action_history_and_position_cycle() -> None:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    instrument = Instrument("BTCUSDT", InstrumentType.LINEAR_PERPETUAL, "BTC", "USDT", "USDT", "0.1", "1", "1", "0")
    engine = RealtimeFeatureEngine(instrument)
    engine.record_action("OPEN_LONG", timestamp=start, current_position=Decimal("1"))
    engine.record_action("ADD_LONG", timestamp=start + timedelta(hours=1), current_position=Decimal("2"))
    engine.ingest_closed_bars([MarketBar("BTCUSDT", start + timedelta(hours=index), "100", "101", "99", "100", "10") for index in range(1, 40)], now=start + timedelta(hours=41))
    features = engine.build_input(decision_time=start + timedelta(hours=2), current_qty=Decimal("2"), current_equity=Decimal("1000")).features
    assert features["feature_latest_action"] == "ADD_LONG"
    assert features["feature_action_lag_1"] == "OPEN_LONG"
    assert features["feature_cycle_duration_seconds"] == pytest.approx(7200)


def test_okx_context_preserves_missing_public_fields() -> None:
    timestamp = str(int(datetime.now(timezone.utc).timestamp() * 1000))
    transport = FakeTransport({
        ("GET", "/api/v5/market/ticker?instId=BTC-USDT-SWAP"): {"code": "0", "data": [{"bidPx": "99", "askPx": "100", "ts": timestamp}]},
        ("GET", "/api/v5/public/funding-rate?instId=BTC-USDT-SWAP"): {"code": "0", "data": []},
        ("GET", "/api/v5/public/mark-price?instType=SWAP&instId=BTC-USDT-SWAP"): {"code": "0", "data": []},
        ("GET", "/api/v5/market/index-tickers?instId=BTC-USDT-SWAP"): {"code": "0", "data": []},
    })
    adapter = OKXAdapter(transport)
    adapter._instrument_types["BTC-USDT-SWAP"] = "SWAP"
    bar = MarketBar("BTC-USDT-SWAP", datetime.now(timezone.utc) - timedelta(hours=2), "99", "101", "98", "100", "1")
    context = adapter.fetch_market_context("BTC-USDT-SWAP", bars=[bar])
    assert context.funding_rate is None
    assert context.mark_price is None
    assert context.index_price is None
    assert context.coverage["funding"] == "MISSING"
    assert context.coverage["mark_price"] == "MISSING"
    assert context.coverage["index_price"] == "MISSING"


def test_okx_context_rejects_future_mark_and_index_snapshots() -> None:
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    future_ms = now_ms + 60_000
    transport = FakeTransport({
        ("GET", "/api/v5/market/ticker?instId=BTC-USDT-SWAP"): {"code": "0", "data": [{"bidPx": "99", "askPx": "100", "ts": str(now_ms)}]},
        ("GET", "/api/v5/public/funding-rate?instId=BTC-USDT-SWAP"): {"code": "0", "data": []},
        ("GET", "/api/v5/public/mark-price?instType=SWAP&instId=BTC-USDT-SWAP"): {"code": "0", "data": [{"markPx": "101", "ts": str(future_ms)}]},
        ("GET", "/api/v5/market/index-tickers?instId=BTC-USDT-SWAP"): {"code": "0", "data": [{"idxPx": "100", "ts": str(future_ms)}]},
    })
    adapter = OKXAdapter(transport)
    adapter._instrument_types["BTC-USDT-SWAP"] = "SWAP"
    context = adapter.fetch_market_context("BTC-USDT-SWAP", bars=[])
    assert context.mark_price is None
    assert context.index_price is None
    assert context.coverage["mark_price"] == "FUTURE_REJECTED"
    assert context.coverage["index_price"] == "FUTURE_REJECTED"


def test_deployment_model_hash_mismatch_blocks_startup(tmp_path: Path) -> None:
    source = Path("quant/outputs/cross_asset_deployment_model_v3.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["model_sha256"] = "0" * 64
    target = tmp_path / "tampered.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_deployment_bundle(target, require_model_sha256=True)


def test_okx_flat_account_can_verify_isolated_leverage_before_first_order() -> None:
    transport = FakeTransport({
        ("GET", "/api/v5/account/config"): {"code": "0", "data": [{"acctLv": "2", "posMode": "net_mode"}]},
        ("GET", "/api/v5/account/leverage-info?instId=BTC-USDT-SWAP,ETH-USDT-SWAP&mgnMode=isolated"): {
            "code": "0",
            "data": [
                {"instId": "BTC-USDT-SWAP", "mgnMode": "isolated", "posSide": "net", "lever": "2"},
                {"instId": "ETH-USDT-SWAP", "mgnMode": "isolated", "posSide": "net", "lever": "2"},
            ],
        },
    })
    adapter = OKXAdapter(transport, credentials=object())
    result = adapter.verify_risk_configuration(("BTC-USDT-SWAP", "ETH-USDT-SWAP"))
    assert result["verified"] is True
    assert adapter.risk_configuration_verified is True
    assert adapter.margin_mode == "isolated"
    assert adapter.max_position_leverage == Decimal("2")


def test_okx_risk_verification_is_scoped_per_symbol() -> None:
    transport = FakeTransport({
        ("GET", "/api/v5/account/config"): {"code": "0", "data": [{"acctLv": "2", "posMode": "net_mode"}]},
        ("GET", "/api/v5/account/leverage-info?instId=BTC-USDT-SWAP,ETH-USDT-SWAP&mgnMode=isolated"): {
            "code": "0",
            "data": [
                {"instId": "BTC-USDT-SWAP", "mgnMode": "isolated", "posSide": "net", "lever": "2"},
                {"instId": "ETH-USDT-SWAP", "mgnMode": "isolated", "posSide": "net", "lever": "3"},
            ],
        },
    })
    adapter = OKXAdapter(transport, credentials=object())
    result = adapter.verify_risk_configuration(("BTC-USDT-SWAP", "ETH-USDT-SWAP"))
    assert result["verified"] is False
    assert adapter.risk_configuration_verified is False
    assert adapter.risk_configuration_by_symbol["BTC-USDT-SWAP"] is True
    assert adapter.risk_configuration_by_symbol["ETH-USDT-SWAP"] is False
    assert "LEVERAGE_LIMIT_OR_UNVERIFIED" in adapter.risk_configuration_reason_by_symbol["ETH-USDT-SWAP"]


def test_risk_gate_uses_symbol_verdict_over_global_verdict() -> None:
    kwargs = dict(
        enable_orders=True,
        confirm_testnet=True,
        symbol="BTCUSDT",
        target_exposure=Decimal("0.1"),
        total_target_exposure=Decimal("0.1"),
        envelope=_envelope(),
        reconciliation_ok=True,
        websocket_connected=True,
        market_fresh=True,
        clock_drift_seconds=Decimal("0"),
        risk_configuration_verified=False,
    )
    assert check_testnet_order(**kwargs, symbol_risk_configuration_verified=True).allowed
    blocked = check_testnet_order(**kwargs, symbol_risk_configuration_verified=False)
    assert not blocked.allowed
    assert "RISK_CONFIGURATION_UNVERIFIED" in blocked.reasons


def test_okx_derivative_order_is_blocked_until_risk_configuration_is_verified() -> None:
    transport = FakeTransport({
        ("GET", "/api/v5/public/instruments?instType=SWAP"): {
            "code": "0",
            "data": [{"instType": "SWAP", "instId": "BTC-USDT-SWAP", "baseCcy": "BTC", "quoteCcy": "USDT", "settleCcy": "USDT", "ctVal": "1", "tickSz": "0.1", "lotSz": "1", "minSz": "1", "state": "live"}],
        },
    })
    adapter = OKXAdapter(transport, credentials=object())
    adapter.load_instruments(inst_type="SWAP")
    with pytest.raises(AdapterError, match="verify isolated margin") as error:
        adapter.place_order(Order("client-1", "BTC-USDT-SWAP", OrderSide.BUY, OrderType.LIMIT, Decimal("1"), datetime.now(timezone.utc), price=Decimal("100")))
    assert error.value.code == "RISK_CONFIGURATION_UNVERIFIED"


def test_cli_does_not_route_bybit_to_the_legacy_order_runtime(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    from quant_bot.__main__ import main

    monkeypatch.setattr(sys, "argv", ["quant_bot", "run", "--mode", "testnet", "--venue", "bybit-demo"])
    with pytest.raises(SystemExit) as raised:
        main()
    assert raised.value.code == 2
    assert "LEGACY_RUNTIME_DISABLED" in capsys.readouterr().out
