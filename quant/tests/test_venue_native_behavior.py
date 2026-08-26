from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "quant" / "scripts", ROOT / "quant" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from audit_venue_native_behavior import chronological_split  # noqa: E402


def test_native_split_is_chronological_and_non_overlapping() -> None:
    rows = [{"decision_time": f"2021-01-01T{index:02d}:00:00Z"} for index in range(10)]
    train, test = chronological_split(rows)
    assert len(train) == 8
    assert len(test) == 2
    assert train[-1]["decision_time"] < test[0]["decision_time"]


def test_native_split_handles_tiny_series_without_leaking() -> None:
    train, test = chronological_split([{"decision_time": "2021-01-01T00:00:00Z"}])
    assert len(train) == 1
    assert test == []
