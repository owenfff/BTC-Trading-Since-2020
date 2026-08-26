from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "quant" / "scripts", ROOT / "quant" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from audit_cross_venue_state_robust_model import (  # noqa: E402
    _augment_training_rows,
    _transition_action,
)


def _row(action: str, current: float, target: float) -> dict[str, object]:
    return {
        "label_next_action": action,
        "label_next_target_exposure": str(target),
        "feature_current_normalized_exposure": str(current),
        "feature_position_scale_contracts": "100",
        "feature_latest_action": "ADD_LONG",
        "feature_recent_add_count_24h": "3",
        "feature_cycle_duration_seconds": "3600",
        "feature_history_last_decision_time": "2021-01-01T00:00:00Z",
    }


def test_transition_action_recomputes_open_flip_and_close() -> None:
    assert _transition_action(0.0, 0.4) == "OPEN_LONG"
    assert _transition_action(0.4, -0.2) == "FLIP_SHORT"
    assert _transition_action(0.4, 0.0) == "CLOSE_LONG"


def test_state_augmentation_only_adds_non_idle_variants_and_resets_dynamic_state() -> None:
    rows = [_row("ADD_LONG", 0.2, 0.4), _row("NO_TRADE", 0.4, 0.4)]
    augmented = _augment_training_rows(rows)
    assert len(augmented) > len(rows)
    synthetic = [row for row in augmented if row.get("state_augmentation") != "ORIGINAL"]
    assert synthetic
    assert all(row["label_next_action"] != "NO_TRADE" for row in synthetic)
    assert all(row["feature_latest_action"] == "" for row in synthetic)
    assert all(float(row["feature_recent_add_count_24h"]) == 0.0 for row in synthetic)
    assert sum(row.get("state_augmentation") == "ORIGINAL" for row in augmented) == 2
