from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.market_data import MarketBar, MarketContext, MarketQuote
from quant_bot.exchanges.http import FakeTransport
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


def test_deployment_model_hash_mismatch_blocks_startup(tmp_path: Path) -> None:
    source = Path("quant/outputs/cross_asset_deployment_model_v3.json")
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["model_sha256"] = "0" * 64
    target = tmp_path / "tampered.json"
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="hash mismatch"):
        load_deployment_bundle(target, require_model_sha256=True)
