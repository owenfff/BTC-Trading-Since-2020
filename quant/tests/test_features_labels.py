from __future__ import annotations

from datetime import datetime, timezone

from features.market_features import build_market_features
from labels.next_decision import build_next_decision_labels, position_delta_bucket


def _bar(minute: int, close: float) -> dict[str, object]:
    timestamp = datetime(2020, 1, 1, 0, minute, tzinfo=timezone.utc)
    return {
        "timestamp": timestamp,
        "timestamp_utc": timestamp.isoformat().replace("+00:00", "Z"),
        "open": close,
        "high": close + 1,
        "low": close - 1,
        "close": close,
        "volume": 10,
        "turnover": 100,
        "mark_price": None,
        "index_price": None,
        "funding_rate": 0.001,
        "funding_source_time": timestamp,
    }


def test_market_features_use_only_closed_bars_before_decision() -> None:
    bars = [_bar(5, 100), _bar(10, 101), _bar(15, 102)]
    decision = datetime(2020, 1, 1, 0, 12, tzinfo=timezone.utc)
    features = build_market_features(bars, decision, timestamps=[row["timestamp"] for row in bars])
    assert features["feature_latest_bar_time"] == "2020-01-01T00:10:00.000Z"
    assert features["feature_latest_bar_time"] < "2020-01-01T00:12:00.000Z"


def test_market_features_do_not_use_future_funding() -> None:
    bars = [_bar(5, 100)]
    bars[0]["funding_source_time"] = datetime(2020, 1, 1, 0, 20, tzinfo=timezone.utc)
    features = build_market_features(bars, datetime(2020, 1, 1, 0, 10, tzinfo=timezone.utc), timestamps=[bars[0]["timestamp"]])
    assert features["feature_funding_rate"] is None


def test_labels_skip_same_timestamp_ties_and_use_next_later_decision() -> None:
    decisions = [
        {"decision_episode_id": "a", "decision_time": "2020-01-01T00:00:00Z", "target_position": "1", "position_delta": "1", "action": "OPEN_LONG"},
        {"decision_episode_id": "b", "decision_time": "2020-01-01T00:00:00Z", "target_position": "2", "position_delta": "1", "action": "ADD_LONG"},
        {"decision_episode_id": "c", "decision_time": "2020-01-01T01:00:00Z", "target_position": "0", "position_delta": "-2", "action": "CLOSE_LONG"},
    ]
    labels = build_next_decision_labels(decisions)
    assert labels[0]["label_status"] == "AVAILABLE"
    assert labels[0]["label_next_action"] == "CLOSE_LONG"
    assert labels[1]["label_next_action"] == "CLOSE_LONG"
    assert position_delta_bucket(0) == "ZERO"
