from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "quant" / "scripts"
SRC = ROOT / "quant" / "src"
for path in (SCRIPTS, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from audit_cross_venue_temporal_labels import (  # noqa: E402
    action_from_transition,
    audit_event_rows,
    audit_temporal_rows,
)


def test_action_transition_covers_flip_and_no_trade() -> None:
    assert action_from_transition(10, -5) == "FLIP_SHORT"
    assert action_from_transition(-5, 0) == "CLOSE_SHORT"
    assert action_from_transition(4, 4) == "NO_TRADE"


def test_event_audit_accepts_isolated_target_and_legacy_flip_name() -> None:
    grouped = {
        ("BITMEX", "BTC-PERP"): [
            {
                "decision_time": "2021-01-01T00:00:00Z",
                "decision_episode_id": "a",
                "raw_current_position_contracts": "10",
                "raw_target_position_contracts": "20",
                "observed_action": "ADD_LONG",
                "label_status": "AVAILABLE",
                "label_next_decision_time": "2021-01-01T01:00:00Z",
                "label_next_action": "FLIP_LONG_TO_SHORT",
            },
            {
                "decision_time": "2021-01-01T01:00:00Z",
                "decision_episode_id": "b",
                "raw_current_position_contracts": "20",
                "raw_target_position_contracts": "-5",
                "observed_action": "FLIP_LONG_TO_SHORT",
                "label_status": "UNAVAILABLE",
            },
        ]
    }
    result = audit_event_rows(grouped)
    assert result["checks"].get("event_action_target_mismatch", 0) == 0
    assert result["checks"].get("event_next_action_label_mismatch", 0) == 0


def test_temporal_audit_flags_net_zero_hour_hiding_source_actions() -> None:
    key = ("BITMEX", "BTC-PERP")
    events = {
        key: [
            {"decision_time": "2021-01-01T00:10:00Z", "observed_action": "ADD_LONG"},
            {"decision_time": "2021-01-01T00:40:00Z", "observed_action": "REDUCE_LONG"},
        ]
    }
    temporal = {
        key: [
            {
                "decision_time": "2021-01-01T00:00:00Z",
                "label_next_decision_time": "2021-01-01T01:00:00Z",
                "raw_current_position_contracts": "10",
                "raw_next_target_position_contracts": "10",
                "label_next_action": "NO_TRADE",
                "temporal_row_type": "NO_TRADE",
                "model_eligible": "true",
            }
        ]
    }
    result = audit_temporal_rows(temporal, events)
    assert result["checks"]["net_zero_label_hides_source_action"] == 1
