"""UTC grid and gap auditing for public market series."""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta
from typing import Any, Iterable

from .download import parse_utc


def _iso(value: datetime | None) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z") if value else ""


def audit_time_grid(rows: Iterable[dict[str, Any]], *, time_field: str = "timestamp", interval_seconds: int = 300) -> dict[str, Any]:
    original = [parse_utc(row.get(time_field)) for row in rows]
    valid = [value for value in original if value is not None]
    counts = Counter(value for value in valid)
    unique = sorted(counts)
    out_of_order = sum(1 for left, right in zip(valid, valid[1:]) if right < left)
    gaps: list[dict[str, Any]] = []
    for left, right in zip(unique, unique[1:]):
        delta = int((right - left).total_seconds())
        if delta > interval_seconds and delta % interval_seconds == 0:
            missing_count = delta // interval_seconds - 1
            gaps.append({
                "gap_start_utc": _iso(left + timedelta(seconds=interval_seconds)),
                "gap_end_utc": _iso(right - timedelta(seconds=interval_seconds)),
                "missing_bar_count": missing_count,
                "gap_seconds": delta - interval_seconds,
            })
        elif delta > interval_seconds:
            gaps.append({
                "gap_start_utc": _iso(left + timedelta(seconds=interval_seconds)),
                "gap_end_utc": _iso(right),
                "missing_bar_count": None,
                "gap_seconds": delta - interval_seconds,
                "non_grid_gap": True,
            })
    expected_count = 0
    if unique:
        expected_count = int((unique[-1] - unique[0]).total_seconds() // interval_seconds) + 1
    missing_count = sum(int(gap.get("missing_bar_count") or 0) for gap in gaps)
    return {
        "status": "PASS" if valid and not gaps and not out_of_order and not any(count > 1 for count in counts.values()) else ("WARNING" if valid else "BLOCKED"),
        "row_count": len(original),
        "valid_timestamp_count": len(valid),
        "unique_timestamp_count": len(unique),
        "duplicate_timestamp_count": sum(count - 1 for count in counts.values() if count > 1),
        "timestamp_parse_failure_count": len(original) - len(valid),
        "out_of_order_transition_count": out_of_order,
        "first_timestamp_utc": _iso(unique[0]) if unique else "",
        "last_timestamp_utc": _iso(unique[-1]) if unique else "",
        "expected_grid_count": expected_count,
        "missing_grid_count": missing_count,
        "coverage_ratio": (len(unique) / expected_count) if expected_count else 0.0,
        "gap_count": len(gaps),
    }


def build_gap_rows(rows: Iterable[dict[str, Any]], *, time_field: str = "timestamp", interval_seconds: int = 300, series: str = "") -> list[dict[str, Any]]:
    audit = audit_time_grid(rows, time_field=time_field, interval_seconds=interval_seconds)
    valid = sorted({parse_utc(row.get(time_field)) for row in rows if parse_utc(row.get(time_field)) is not None})
    output: list[dict[str, Any]] = []
    for left, right in zip(valid, valid[1:]):
        delta = int((right - left).total_seconds())
        if delta > interval_seconds:
            missing_count = delta // interval_seconds - 1 if delta % interval_seconds == 0 else None
            output.append({
                "series": series,
                "gap_start_utc": _iso(left + timedelta(seconds=interval_seconds)),
                "gap_end_utc": _iso(right - timedelta(seconds=interval_seconds)) if missing_count is not None else _iso(right),
                "missing_bar_count": missing_count,
                "gap_seconds": delta - interval_seconds,
                "grid_status": "ALIGNED" if missing_count is not None else "NON_GRID_GAP",
            })
    if not output and audit["status"] == "BLOCKED":
        output.append({"series": series, "gap_start_utc": "", "gap_end_utc": "", "missing_bar_count": None, "gap_seconds": None, "grid_status": "NO_VALID_DATA"})
    return output


__all__ = ["audit_time_grid", "build_gap_rows"]
