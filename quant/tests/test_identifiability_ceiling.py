from __future__ import annotations

from audit_identifiability_ceiling import event_rows


def test_event_rows_removes_idle_rows_but_keeps_directional_actions() -> None:
    rows = [
        {"model_eligible": "True", "label_status": "AVAILABLE", "label_next_action": "NO_TRADE"},
        {"model_eligible": "True", "label_status": "AVAILABLE", "label_next_action": "OPEN_LONG"},
        {"model_eligible": "False", "label_status": "AVAILABLE", "label_next_action": "CLOSE_LONG"},
    ]
    selected = event_rows(rows)
    assert len(selected) == 1
    assert selected[0]["label_next_action"] == "OPEN_LONG"


def test_event_rows_requires_available_label() -> None:
    rows = [{"model_eligible": "True", "label_status": "MISSING", "label_next_action": "OPEN_LONG"}]
    assert event_rows(rows) == []
