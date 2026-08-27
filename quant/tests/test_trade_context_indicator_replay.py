from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys
from pytest import approx

ROOT = Path(__file__).resolve().parents[2]
SCRIPT_DIR = ROOT / "quant" / "scripts"
SRC = ROOT / "quant" / "src"
for path in (ROOT, SRC, SCRIPT_DIR):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from build_trade_context_indicator_replay import GroupStats, action_family, causal_row_audit, strategy_reason_zh  # noqa: E402
from quant_bot.strategy.feature_contract import strategy_input_from_row  # noqa: E402


UTC = timezone.utc


def test_causal_audit_rejects_equal_or_future_bar_and_funding() -> None:
    row = {
        "decision_time": "2025-01-01T01:00:00Z",
        "feature_latest_bar_time": "2025-01-01T01:00:00Z",
        "feature_funding_source_time": "2025-01-01T02:00:00Z",
        "label_status": "AVAILABLE",
        "label_next_decision_time": "2025-01-01T00:59:00Z",
    }
    audit = causal_row_audit(row)
    assert audit["closed_bar"] == "FUTURE_OR_EQUAL"
    assert audit["funding"] == "FUTURE_OR_EQUAL"
    assert audit["next_label"] == "FUTURE_OR_EQUAL"


def test_causal_audit_accepts_strictly_prior_closed_bar() -> None:
    row = {
        "decision_time": "2025-01-01T01:00:00Z",
        "feature_latest_bar_time": "2025-01-01T00:00:00Z",
        "feature_funding_source_time": "2025-01-01T00:30:00Z",
        "label_status": "AVAILABLE",
        "label_next_decision_time": "2025-01-01T02:00:00Z",
    }
    assert all(value in {"PASS", "NOT_APPLICABLE"} for value in causal_row_audit(row).values())


def test_labels_and_observed_fields_are_not_strategy_input() -> None:
    row = {
        "decision_time": datetime(2025, 1, 1, tzinfo=UTC).isoformat(),
        "feature_symbol": "BTC-PERP",
        "feature_current_normalized_exposure": "0.1",
        "label_next_action": "OPEN_LONG",
        "label_next_target_exposure": "0.8",
        "observed_action": "OPEN_SHORT",
        "observed_target_position_contracts": "123",
    }
    strategy_input = strategy_input_from_row(row)
    assert strategy_input.features
    assert not any(key.startswith("label_") or key.startswith("observed_") for key in strategy_input.features)


def test_group_stats_tracks_indicator_missing_values_and_action_metrics() -> None:
    stats = GroupStats()
    row = {
        "label_status": "AVAILABLE",
        "label_next_action": "OPEN_LONG",
        "label_next_target_exposure": "0.25",
        "feature_rsi_14": "25",
        "feature_macd_histogram": "-0.1",
        "feature_bollinger_percent_b_20": "0.05",
        "feature_volume_percentile_72bar": "0.8",
        "feature_return_24bar": "-0.02",
        "feature_atr_14bar": "0.03",
    }
    stats.add(row, "OPEN_LONG", 0.2)
    result = stats.as_dict()
    assert result["labeled_rows"] == 1
    assert result["action_accuracy"] == 1.0
    assert result["indicator_summary"]["feature_rsi_14"]["mean"] == 25.0
    assert result["target_exposure_mae"] == approx(0.05)


def test_action_family_and_chinese_reason_are_explicit() -> None:
    assert action_family("FLIP_SHORT_TO_LONG") == "FLIP"
    assert action_family("NO_TRADE") == "HOLD"
    reason = strategy_reason_zh({"feature_rsi_14": "28", "feature_macd_histogram": "-0.1", "feature_bollinger_percent_b_20": "0.05", "feature_return_24bar": "-0.02"}, "OPEN_LONG")
    assert "模型输入依据" in reason
    assert "真实规则" in reason
