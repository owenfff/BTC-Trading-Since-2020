from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

from cross_asset.market import _audit, _join_funding
from cross_asset.universe import fit_position_scales, split_by_global_time
from features.market_features import build_market_features
from quant_bot.strategy.base import StrategyInput
from quant_bot.strategy.feature_contract import FEATURE_COLUMNS
from quant_bot.strategy.supervised_models import CrossAssetNumpyLogisticStrategy
from quant_bot.paper import PaperTradingEngine


UTC = timezone.utc


def _decision(symbol: str, index: int, action: str, position: str) -> dict[str, object]:
    timestamp = datetime(2020, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    return {
        "symbol": symbol,
        "decision_time": timestamp.isoformat().replace("+00:00", "Z"),
        "_decision_dt": timestamp,
        "decision_episode_id": f"{symbol}-{index}",
        "position_before": position,
        "target_position": str(float(position) + (1 if "LONG" in action else -1)),
        "position_delta": "1",
    }


def test_global_split_and_position_scale_use_train_only() -> None:
    rows = [_decision("A", index, "OPEN_LONG", "0") for index in range(10)]
    rows.extend(_decision("B", index, "OPEN_LONG", "0") for index in range(10))
    ordered = split_by_global_time(rows)
    scales = fit_position_scales(ordered)
    assert set(scales) == {"A", "B"}
    assert all(row["dataset_split"] in {"TRAIN", "VALIDATION", "TEST"} for row in ordered)
    assert scales["A"] == 1.0 and scales["B"] == 1.0


def test_hourly_market_features_use_strictly_prior_bars() -> None:
    rows = []
    start = datetime(2020, 1, 1, tzinfo=UTC)
    for index in range(80):
        timestamp = start + timedelta(hours=index + 1)
        rows.append({
            "timestamp": timestamp,
            "close": 100.0 + index,
            "open": 99.0 + index,
            "high": 101.0 + index,
            "low": 98.0 + index,
            "volume": 10.0,
            "funding_rate": None,
            "funding_source_time": None,
        })
    decision = start + timedelta(hours=80, minutes=30)
    features = build_market_features(rows, decision, timestamps=[row["timestamp"] for row in rows], bar_seconds=3600)
    assert features["feature_latest_bar_time"] == "2020-01-04T08:00:00.000Z"
    assert features["feature_market_data_available"] is True
    assert features["feature_return_1bar"] is not None


def test_funding_join_keeps_latest_asof_event_and_source_time() -> None:
    bars = [{"timestamp": "2020-01-01T01:00:00.000Z", "funding_rate": None, "funding_source_timestamp_utc": ""}]
    _join_funding(bars, [{"timestamp": "2020-01-01T00:30:00.000Z", "fundingRate": 0.001}])
    assert bars[0]["funding_rate"] == 0.001
    assert bars[0]["funding_source_timestamp_utc"] == "2020-01-01T00:30:00.000Z"


def test_cross_asset_logistic_uses_symbol_metadata_and_versioned_signal() -> None:
    rows = []
    for index in range(12):
        row = {key: None for key in FEATURE_COLUMNS}
        row.update({
            "decision_time": f"2020-01-01T{index:02d}:00:00Z",
            "dataset_split": "TRAIN" if index < 10 else "TEST",
            "label_status": "AVAILABLE",
            "label_next_action": "OPEN_LONG" if index % 2 == 0 else "OPEN_SHORT",
            "label_next_target_exposure": "0.5" if index % 2 == 0 else "-0.5",
            "feature_symbol": "A" if index % 2 == 0 else "B",
            "feature_instrument_class": "DERIVATIVE",
            "feature_payout_model": "INVERSE",
            "feature_quote_currency": "USD",
            "feature_settlement_currency": "XBT",
            "feature_market_bar_interval": "1h",
            "feature_market_data_available": True,
            "feature_market_regime": "TREND_UP" if index % 2 == 0 else "TREND_DOWN",
            "feature_current_normalized_exposure": 0.0,
            "feature_return_6bar": 0.01 if index % 2 == 0 else -0.01,
            "feature_return_24bar": 0.02 if index % 2 == 0 else -0.02,
            "feature_trend_slope_24bar": 0.001 if index % 2 == 0 else -0.001,
        })
        rows.append(row)
    model = CrossAssetNumpyLogisticStrategy().fit(rows)
    signal = model.predict(StrategyInput(datetime(2020, 1, 2, tzinfo=UTC), rows[0]))
    assert signal.strategy_version == "behavioral-distillation-v2-cross-asset-logistic"
    assert signal.action in {"OPEN_LONG", "OPEN_SHORT"}


def test_cross_asset_signal_can_be_consumed_by_local_paper_engine() -> None:
    signal = CrossAssetNumpyLogisticStrategy().version
    assert signal == "behavioral-distillation-v2-cross-asset-logistic"
    engine = PaperTradingEngine()
    # The engine contract is exchange-neutral: a StrategySignal is all it
    # needs, and the test never opens a network connection.
    from quant_bot.strategy.base import make_signal as build_signal
    model_signal = build_signal(datetime(2020, 1, 1, tzinfo=UTC), target_exposure=0.25, action="OPEN_LONG", confidence=0.8, strategy_version=signal)
    engine.apply_signal(model_signal, reference_price=Decimal("100"))
    assert engine.state.partial_orders == 1
    assert engine.state.position > 0


def test_stable_target_regression_uses_ridge_without_changing_legacy_default() -> None:
    rows = []
    for index in range(24):
        row = {key: None for key in FEATURE_COLUMNS}
        row.update({
            "decision_time": f"2020-01-{index + 1:02d}T00:00:00Z",
            "dataset_split": "TRAIN",
            "label_status": "AVAILABLE",
            "label_next_action": "OPEN_LONG" if index % 2 == 0 else "OPEN_SHORT",
            "label_next_target_exposure": "0.25" if index % 2 == 0 else "-0.25",
            "feature_symbol": "A",
            "feature_instrument_class": "DERIVATIVE",
            "feature_payout_model": "LINEAR",
            "feature_quote_currency": "USD",
            "feature_settlement_currency": "USD",
            "feature_market_bar_interval": "1h",
            "feature_market_data_available": True,
            "feature_mark_index_missing": False,
            "feature_market_regime": "RANGE_OR_MIXED",
            "feature_contract_lot_size": 1.0,
            "feature_multiplier_major": 1.0,
            "feature_current_normalized_exposure": 0.0,
            # Deliberately collinear with the next field, as in instrument
            # metadata plus indicator columns in the historical dataset.
            "feature_rsi_14": 50.0,
            "feature_macd_line_12_26": 0.0,
            "feature_macd_signal_9": 0.0,
            "feature_macd_histogram": 0.0,
            "feature_bollinger_zscore_20": 0.0,
            "feature_bollinger_percent_b_20": 0.5,
        })
        rows.append(row)
    legacy = CrossAssetNumpyLogisticStrategy().fit(rows)
    stable = CrossAssetNumpyLogisticStrategy(target_l2=1.0).fit(rows)
    assert stable.target_l2 == 1.0
    assert stable.target_coef is not None
    assert all(float(value) == float(value) for value in stable.target_coef)
    assert max(abs(float(value)) for value in stable.target_coef) < 100.0
    assert legacy.target_l2 == 0.0


def test_balanced_class_weighting_is_explicit_and_round_trips() -> None:
    rows = []
    for index in range(12):
        row = {key: None for key in FEATURE_COLUMNS}
        row.update({
            "decision_time": f"2020-01-01T{index:02d}:00:00Z",
            "dataset_split": "TRAIN",
            "label_status": "AVAILABLE",
            "label_next_action": "NO_TRADE" if index < 10 else "OPEN_LONG",
            "label_next_target_exposure": "0.0" if index < 10 else "0.25",
            "feature_symbol": "A",
            "feature_instrument_class": "DERIVATIVE",
            "feature_payout_model": "LINEAR",
            "feature_quote_currency": "USD",
            "feature_settlement_currency": "USD",
            "feature_market_bar_interval": "1h",
            "feature_market_data_available": True,
            "feature_mark_index_missing": False,
            "feature_market_regime": "RANGE_OR_MIXED",
            "feature_contract_lot_size": 1.0,
            "feature_multiplier_major": 1.0,
            "feature_current_normalized_exposure": 0.0,
        })
        rows.append(row)
    model = CrossAssetNumpyLogisticStrategy(target_l2=1.0, class_weighting="balanced", min_action_confidence=0.73).fit(rows)
    restored = CrossAssetNumpyLogisticStrategy.from_dict(model.to_dict())
    assert model.class_weighting == "balanced"
    assert restored.class_weighting == "balanced"
    assert restored.min_action_confidence == 0.73


def test_probability_calibration_is_train_only_serializable_and_bounded() -> None:
    rows = []
    actions = ("NO_TRADE", "OPEN_LONG", "OPEN_SHORT")
    targets = ("0.0", "0.25", "-0.25")
    for index in range(36):
        action_index = index % len(actions)
        day = index + 1 if index < 24 else index - 23
        month = "01" if index < 24 else "02"
        row = {key: None for key in FEATURE_COLUMNS}
        row.update({
            "decision_time": f"2020-{month}-{day:02d}T00:00:00Z",
            "dataset_split": "TRAIN",
            "label_status": "AVAILABLE",
            "label_next_action": actions[action_index],
            "label_next_target_exposure": targets[action_index],
            "feature_symbol": "A",
            "feature_instrument_class": "DERIVATIVE",
            "feature_payout_model": "LINEAR",
            "feature_quote_currency": "USD",
            "feature_settlement_currency": "USD",
            "feature_market_bar_interval": "1h",
            "feature_market_data_available": True,
            "feature_mark_index_missing": False,
            "feature_market_regime": "RANGE_OR_MIXED",
            "feature_contract_lot_size": 1.0,
            "feature_multiplier_major": 1.0,
            "feature_current_normalized_exposure": 0.0,
            "feature_return_1bar": (index % 5 - 2) / 100.0,
        })
        rows.append(row)
    model = CrossAssetNumpyLogisticStrategy(target_l2=1.0, class_weighting="sqrt_balanced").fit(rows[:24])
    stats = model.calibrate_probabilities(rows[24:])
    assert stats["calibration_rows"] == 12
    assert stats["nll_after"] <= stats["nll_before"] + 1e-9
    assert 0.25 <= model.probability_temperature <= 10.0
    restored = CrossAssetNumpyLogisticStrategy.from_dict(model.to_dict())
    assert restored.calibration_row_count == 12
    assert restored.probability_temperature == model.probability_temperature
    assert restored.probability_bias is not None


def test_nested_probability_split_is_chronological_and_non_overlapping() -> None:
    from audit_cross_venue_probability_calibrated_stability import _split_training_rows

    rows = [{"decision_time": f"2020-01-01T{index:02d}:00:00Z"} for index in range(10)]
    fit, calibration, threshold = _split_training_rows(rows)
    assert len(fit) == 6
    assert len(calibration) == 2
    assert len(threshold) == 2
    assert fit[-1]["decision_time"] < calibration[0]["decision_time"]
    assert calibration[-1]["decision_time"] < threshold[0]["decision_time"]


def test_action_target_consistency_prevents_no_trade_from_repositioning() -> None:
    rows = []
    for index in range(12):
        row = {key: None for key in FEATURE_COLUMNS}
        row.update({
            "decision_time": f"2020-01-01T{index:02d}:00:00Z",
            "dataset_split": "TRAIN",
            "label_status": "AVAILABLE",
            "label_next_action": "NO_TRADE",
            "label_next_target_exposure": "0.0",
            "feature_symbol": "A",
            "feature_instrument_class": "DERIVATIVE",
            "feature_payout_model": "LINEAR",
            "feature_quote_currency": "USD",
            "feature_settlement_currency": "USD",
            "feature_market_bar_interval": "1h",
            "feature_market_data_available": True,
            "feature_mark_index_missing": False,
            "feature_market_regime": "RANGE_OR_MIXED",
            "feature_contract_lot_size": 1.0,
            "feature_multiplier_major": 1.0,
            "feature_current_normalized_exposure": 0.0,
        })
        rows.append(row)
    model = CrossAssetNumpyLogisticStrategy(target_l2=1.0, enforce_action_target_consistency=True).fit(rows)
    signal = model.predict(StrategyInput(datetime(2020, 1, 2, tzinfo=UTC), rows[0], current_strategy_position=0.37))
    assert signal.action == "NO_TRADE"
    assert signal.target_exposure == 0.37


def test_market_coverage_audit_marks_out_of_range_series_insufficient() -> None:
    first = datetime(2020, 1, 1, tzinfo=UTC)
    last = datetime(2020, 1, 2, tzinfo=UTC)
    audit = _audit("A", [{"timestamp": "2020-01-01T12:00:00.000Z", "mark_price": None, "index_price": None, "funding_rate": None}], first, last, "PASS")
    assert audit["coverage_status"] == "INSUFFICIENT"
