from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_bot.strategy.base import StrategyInput  # noqa: E402
from quant_bot.strategy.distilled_rules import DistilledRuleStrategy  # noqa: E402
from quant_bot.strategy.feature_contract import FEATURE_COLUMNS, strategy_input_from_row  # noqa: E402
from quant_bot.strategy.imitation_model import HistoricalBehaviorBaseline  # noqa: E402
from quant_bot.strategy.strategy_state import StrategyState  # noqa: E402


def features(**overrides: object) -> dict[str, object]:
    result = {key: None for key in FEATURE_COLUMNS}
    result.update(
        {
            "feature_market_data_available": True,
            "feature_mark_index_missing": True,
            "feature_current_normalized_exposure": 0.0,
            "feature_market_regime": "UPTREND",
            "feature_return_6bar": 0.01,
            "feature_return_24bar": 0.02,
            "feature_trend_slope_24bar": 0.001,
            "feature_accounting_confidence": "HIGH",
        }
    )
    result.update(overrides)
    return result


def test_rule_strategy_emits_complete_shared_signal_contract() -> None:
    signal = DistilledRuleStrategy().predict(StrategyInput(datetime(2020, 1, 1, tzinfo=timezone.utc), features()))
    signal.validate()
    assert signal.action == "OPEN_LONG"
    assert signal.signal_timestamp.endswith("Z")
    assert "MARK_INDEX_MISSING" in signal.risk_tags


def test_rule_strategy_holds_when_required_history_is_missing() -> None:
    signal = DistilledRuleStrategy().predict(StrategyInput(datetime(2020, 1, 1, tzinfo=timezone.utc), features(feature_market_regime="UNKNOWN")))
    assert signal.action == "NO_TRADE"
    assert "UNKNOWN_MARKET_REGIME" in signal.risk_tags


def test_baseline_fits_train_only_and_predicts() -> None:
    rows = [
        {"dataset_split": "TRAIN", "feature_market_regime": "UPTREND", "feature_current_normalized_exposure": "0", "label_next_action": "OPEN_LONG", "label_next_target_exposure": "0.2"},
        {"dataset_split": "TEST", "feature_market_regime": "UPTREND", "feature_current_normalized_exposure": "0", "label_next_action": "OPEN_SHORT", "label_next_target_exposure": "-0.2"},
    ]
    model = HistoricalBehaviorBaseline().fit(rows)
    assert model.fit_row_count == 1
    signal = model.predict(StrategyInput(datetime(2020, 1, 1, tzinfo=timezone.utc), features(feature_market_regime="UPTREND")))
    assert signal.action == "OPEN_LONG"


def test_strategy_input_rejects_observed_or_label_columns() -> None:
    row = {"decision_time": "2020-01-01T00:00:00Z", "observed_action": "OPEN_LONG", **features()}
    converted = strategy_input_from_row(row)
    assert "observed_action" not in converted.features
    assert all(not key.startswith("label_") for key in converted.features)


def test_strategy_state_tracks_only_signal_contract() -> None:
    signal = DistilledRuleStrategy().predict(StrategyInput(datetime(2020, 1, 1, tzinfo=timezone.utc), features()))
    state = StrategyState()
    state.apply_signal(signal)
    assert state.current_exposure == signal.target_exposure
    assert state.last_action == signal.action
