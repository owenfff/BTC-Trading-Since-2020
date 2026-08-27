from __future__ import annotations

from datetime import datetime, timezone

from quant_bot.strategy.base import StrategyInput
from quant_bot.strategy.explanations import strategy_reason_zh
from quant_bot.strategy.unified_distillation import UnifiedDistilledStrategy, transition_action
from quant.scripts.build_unified_distillation_model import _aggregate_same_time, _balanced_rows


def _row(index: int, action: str, current: float, target: float) -> dict[str, object]:
    return {
        "decision_time": f"2024-01-{(index % 9) + 1:02d}T00:00:00Z",
        "label_status": "AVAILABLE",
        "label_next_action": action,
        "label_next_target_exposure": str(target),
        "feature_current_normalized_exposure": str(current),
        "feature_symbol": "BTC-PERP",
        "feature_instrument_class": "DERIVATIVE",
        "feature_payout_model": "LINEAR",
        "feature_quote_currency": "USDT",
        "feature_settlement_currency": "USDT",
        "feature_market_bar_interval": "1h",
        "feature_market_regime": "UP" if target >= current else "DOWN",
        "feature_rsi_14": str(35 + index),
        "feature_macd_histogram": str(0.01 if target >= current else -0.01),
        "feature_bollinger_percent_b_20": "0.65",
        "feature_return_24bar": str(0.01 if target >= current else -0.01),
        "source_venue": "BITMEX" if index % 2 else "HYPERLIQUID",
        "canonical_asset": "BTC",
        "model_eligible": "true",
        "_unified_sample_weight": "1",
    }


def test_transition_action_is_target_driven() -> None:
    assert transition_action(0.0, 0.4) == "OPEN_LONG"
    assert transition_action(0.4, 0.7) == "ADD_LONG"
    assert transition_action(0.4, 0.1) == "REDUCE_LONG"
    assert transition_action(0.4, 0.0) == "CLOSE_LONG"
    assert transition_action(0.4, -0.2) == "FLIP_LONG_TO_SHORT"
    assert transition_action(-0.4, -0.4) == "HOLD_SHORT"


def test_unified_model_round_trip_and_idle_target_invariant() -> None:
    actions = [
        ("NO_TRADE", 0.0, 0.0),
        ("OPEN_LONG", 0.0, 0.4),
        ("ADD_LONG", 0.4, 0.7),
        ("REDUCE_LONG", 0.7, 0.3),
        ("CLOSE_LONG", 0.3, 0.0),
        ("OPEN_SHORT", 0.0, -0.4),
        ("ADD_SHORT", -0.4, -0.7),
        ("REDUCE_SHORT", -0.7, -0.3),
        ("CLOSE_SHORT", -0.3, 0.0),
        ("FLIP_LONG_TO_SHORT", 0.3, -0.3),
        ("FLIP_SHORT_TO_LONG", -0.3, 0.3),
        ("HOLD_LONG", 0.3, 0.3),
    ]
    rows = [_row(index, action, current, target) for index, (action, current, target) in enumerate(actions * 3)]
    model = UnifiedDistilledStrategy(epochs=4).fit(rows)
    model.action_threshold = 1.0
    features = dict(rows[0])
    signal = model.predict(StrategyInput(datetime(2024, 2, 1, tzinfo=timezone.utc), features, current_strategy_position=0.0))
    assert signal.strategy_version == "behavioral-distillation-v4.6-unified-distillation"
    assert signal.target_exposure == 0.0
    assert signal.strategy_reason_zh
    restored = UnifiedDistilledStrategy.from_dict(model.to_dict())
    restored_signal = restored.predict(StrategyInput(datetime(2024, 2, 1, tzinfo=timezone.utc), features, current_strategy_position=0.0))
    assert restored_signal.as_dict() == signal.as_dict()


def test_unified_model_does_not_encode_source_symbol_as_predictive_category() -> None:
    rows = [_row(index, "OPEN_LONG" if index % 2 else "OPEN_SHORT", 0.0, 0.4 if index % 2 else -0.4) for index in range(12)]
    model = UnifiedDistilledStrategy(epochs=2).fit(rows)
    assert "feature_symbol" not in (model.encoder.categorical_features or ())
    assert "feature_symbol" not in (model.encoder.categories or {})


def test_strategy_reason_is_chinese_and_marks_model_input_basis() -> None:
    reason = strategy_reason_zh(
        "REDUCE_SHORT",
        -0.8,
        -0.3,
        {"feature_rsi_14": 25, "feature_macd_histogram": 0.01, "feature_bollinger_percent_b_20": 0.12, "feature_return_24bar": -0.02},
    )
    assert "RSI14处于超卖区" in reason
    assert "当前仓位高于模型目标" in reason


def test_training_weights_balance_venue_then_asset() -> None:
    rows = []
    for venue, assets, count in (("BITMEX", ("BTC", "ETH"), 4), ("HYPERLIQUID", ("BTC",), 8)):
        for asset in assets:
            for index in range(count):
                rows.append({"source_venue": venue, "canonical_asset": asset, "symbol": f"{asset}-{index}"})
    prepared, metadata = _balanced_rows(rows)
    sums_by_venue = {}
    sums_by_asset = {}
    for row in prepared:
        weight = float(row["_unified_sample_weight"])
        venue = row["source_venue"]
        key = f"{venue}:{row['canonical_asset']}"
        sums_by_venue[venue] = sums_by_venue.get(venue, 0.0) + weight
        sums_by_asset[key] = sums_by_asset.get(key, 0.0) + weight
    assert metadata["weighting"].startswith("equal total weight per source venue")
    assert max(sums_by_venue.values()) - min(sums_by_venue.values()) < 1e-9
    assert abs(sums_by_asset["BITMEX:BTC"] - sums_by_asset["BITMEX:ETH"]) < 1e-9
    assert sums_by_asset["HYPERLIQUID:BTC"] > sums_by_asset["BITMEX:BTC"]


def test_same_time_conflicting_targets_are_retained_as_ambiguous() -> None:
    base = {"source_venue": "BITMEX", "canonical_asset": "BTC", "decision_time": "2024-01-01T00:00:00Z", "decision_episode_id": "1", "label_next_action": "OPEN_LONG", "label_next_target_exposure": "0.5"}
    other = {**base, "decision_episode_id": "2", "label_next_action": "CLOSE_LONG", "label_next_target_exposure": "0"}
    aggregated, ambiguous = _aggregate_same_time([base, other])
    assert ambiguous == 2
    assert len(aggregated) == 1
    assert aggregated[0]["label_ambiguity"] == "true"
