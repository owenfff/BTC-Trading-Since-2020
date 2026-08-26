from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from quant_bot.domain.instrument import Instrument, InstrumentType
from quant_bot.domain.market_data import MarketBar
from quant_bot.domain.order import OrderSide, OrderType
from quant_bot.execution.aggregation import merge_duplicate_target_plans
from quant_bot.execution.target_planner import TargetOrderPlan
from quant_bot.strategy.explanations import strategy_basis_from_features
from quant_bot.strategy.realtime_features import RealtimeFeatureEngine
from features.technical_indicators import calculate_technical_indicators


UTC = timezone.utc


def _plan(source: str, target: str, confidence: str) -> TargetOrderPlan:
    return TargetOrderPlan(
        client_order_id=f"client-{source}",
        symbol="ADA-USDT-SWAP",
        side=OrderSide.BUY,
        order_type=OrderType.LIMIT,
        quantity=Decimal("1"),
        price=Decimal("1"),
        reduce_only=False,
        post_only=True,
        target_exposure=Decimal(target),
        target_contracts=Decimal("1"),
        current_contracts=Decimal("0"),
        reason="TARGET_DELTA",
        reference_price=Decimal("1"),
        bid=Decimal("1"),
        ask=Decimal("1"),
        strategy_action="OPEN_LONG",
        strategy_confidence=Decimal(confidence),
        strategy_basis=("RSI14=60.00",),
        strategy_source_symbols=(source,),
        strategy_source_signals=({"historical_symbol": source, "target_exposure": target},),
    )


def test_indicator_boundaries_and_missing_windows() -> None:
    closes = [100 + index for index in range(100)]
    indicators = calculate_technical_indicators(closes, closes, [value - 1 for value in closes], [100 + index for index in range(100)])
    assert indicators["feature_rsi_14"] == 100.0
    assert indicators["feature_macd_histogram"] is not None
    assert indicators["feature_bollinger_percent_b_20"] is not None
    assert indicators["feature_volume_percentile_72bar"] == 1.0

    incomplete = calculate_technical_indicators([100, 101], [101, 102], [99, 100], [10, 11])
    assert incomplete["feature_rsi_14"] is None
    assert incomplete["feature_macd_histogram"] is None
    assert incomplete["feature_bollinger_percent_b_20"] is None
    assert incomplete["feature_volume_percentile_72bar"] is None


def test_realtime_indicator_calculation_uses_same_causal_helper() -> None:
    instrument = Instrument("ADA-USDT-SWAP", InstrumentType.LINEAR_PERPETUAL, "ADA", "USDT", "USDT", "0.1", "1", "1", "0")
    start = datetime(2020, 1, 1, tzinfo=UTC)
    bars = [
        MarketBar("ADA-USDT-SWAP", start + timedelta(hours=index), 100 + index, 101 + index, 99 + index, 100 + index, 100 + index)
        for index in range(100)
    ]
    engine = RealtimeFeatureEngine(instrument, feature_contract_version="m13-v3-cross-asset-indicators")
    engine.ingest_closed_bars(bars, now=start + timedelta(hours=200))
    features = engine.build_input(decision_time=start + timedelta(hours=100), current_qty=Decimal("0"), current_equity=Decimal("1000")).features
    expected = calculate_technical_indicators([bar.close for bar in bars], [bar.high for bar in bars], [bar.low for bar in bars], [bar.volume for bar in bars])
    for key, value in expected.items():
        assert features[key] == value


def test_indicator_basis_is_explicit_and_missing_values_are_not_zero() -> None:
    basis = strategy_basis_from_features({
        "feature_rsi_14": 61.234,
        "feature_macd_histogram": 0.0123,
        "feature_bollinger_percent_b_20": 0.73,
        "feature_return_24bar": 0.04,
    })
    assert "RSI14=61.23" in basis
    assert "MACD_HIST=0.01230000" in basis
    assert "INDICATORS_INCOMPLETE" not in basis
    missing = strategy_basis_from_features({"feature_return_24bar": 0.01})
    assert "INDICATORS_INCOMPLETE" in missing


def test_duplicate_historical_symbols_merge_to_one_net_target() -> None:
    merged = merge_duplicate_target_plans([_plan("ADAUSD", "0.4", "0.8"), _plan("ADAUSDT", "0.2", "0.2")])
    assert len(merged) == 1
    assert merged[0].symbol == "ADA-USDT-SWAP"
    assert merged[0].target_exposure == Decimal("0.36")
    assert merged[0].strategy_source_symbols == ("ADAUSD", "ADAUSDT")
    assert len(merged[0].strategy_source_signals) == 2
    assert "MERGED_DUPLICATE_SYMBOLS" in merged[0].strategy_basis

