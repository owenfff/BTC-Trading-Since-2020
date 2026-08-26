from __future__ import annotations

from datetime import datetime, timezone

from audit_shared_intent_timing import timing_metrics
from quant_bot.strategy.base import make_signal


DECISION_TIME = datetime(2026, 1, 1, tzinfo=timezone.utc)


def test_timing_metrics_isolates_action_from_action_family() -> None:
    rows = [
        {"decision_episode_id": "1", "label_next_action": "OPEN"},
        {"decision_episode_id": "2", "label_next_action": "NO_TRADE"},
        {"decision_episode_id": "3", "label_next_action": "REDUCE"},
    ]
    predictions = [
        (rows[0], make_signal(DECISION_TIME, target_exposure=0.1, action="ADD", confidence=0.8)),
        (rows[1], make_signal(DECISION_TIME, target_exposure=0.0, action="NO_TRADE", confidence=0.8)),
        (rows[2], make_signal(DECISION_TIME, target_exposure=0.0, action="FLIP", confidence=0.8)),
    ]
    metrics = timing_metrics(rows, predictions)
    assert metrics["rows"] == 3
    assert metrics["true_action_rows"] == 2
    assert metrics["predicted_action_rows"] == 2
    assert metrics["f1"] == 1.0


def test_timing_metrics_counts_all_no_trade_baseline() -> None:
    rows = [{"decision_episode_id": "1", "label_next_action": "OPEN"}]
    predictions = [(rows[0], make_signal(DECISION_TIME, target_exposure=0.0, action="NO_TRADE", confidence=0.8))]
    metrics = timing_metrics(rows, predictions)
    assert metrics["predicted_action_rate"] == 0.0
    assert metrics["all_no_trade_baseline_f1"] == 0.0
