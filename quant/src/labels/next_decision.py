"""Chronological next-decision labels with same-timestamp tie protection."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


UTC = timezone.utc
POSITION_SCALE_CONTRACTS = 10_000_000


def parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso_utc(value: datetime | None) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z") if value else ""


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def position_delta_bucket(delta: float, scale: float = POSITION_SCALE_CONTRACTS) -> str:
    magnitude = abs(delta)
    if magnitude == 0:
        return "ZERO"
    if magnitude <= scale * 0.01:
        return "SMALL"
    if magnitude <= scale * 0.10:
        return "MEDIUM"
    return "LARGE"


def build_next_decision_labels(
    decisions: list[dict[str, Any]],
    *,
    position_scale_contracts: float = POSITION_SCALE_CONTRACTS,
) -> list[dict[str, Any]]:
    if position_scale_contracts <= 0:
        raise ValueError("position_scale_contracts must be positive")
    ordered = sorted(decisions, key=lambda row: (parse_utc(row.get("decision_time")) or datetime.max.replace(tzinfo=UTC), str(row.get("decision_episode_id", ""))))
    output: list[dict[str, Any]] = []
    for index, current in enumerate(ordered):
        current_time = parse_utc(current.get("decision_time"))
        row: dict[str, Any] = {
            "decision_episode_id": str(current.get("decision_episode_id", "")),
            "label_next_decision_time": "",
            "label_next_target_position_contracts": None,
            "label_next_target_exposure": None,
            "label_next_action": "",
            "label_next_position_delta_bucket": "",
            "label_time_to_next_action_seconds": None,
            "label_status": "NO_LATER_DECISION",
        }
        if current_time is None:
            row["label_status"] = "INVALID_CURRENT_TIME"
            output.append(row)
            continue
        next_index = index + 1
        while next_index < len(ordered) and parse_utc(ordered[next_index].get("decision_time")) == current_time:
            next_index += 1
        if next_index < len(ordered):
            next_row = ordered[next_index]
            next_time = parse_utc(next_row.get("decision_time"))
            if next_time and next_time > current_time:
                next_target = _number(next_row.get("target_position"))
                next_delta = _number(next_row.get("position_delta"))
                row.update({
                    "label_next_decision_time": iso_utc(next_time),
                    "label_next_target_position_contracts": next_target,
                    "label_next_target_exposure": next_target / position_scale_contracts,
                    "label_next_action": str(next_row.get("action", "")),
                    "label_next_position_delta_bucket": position_delta_bucket(next_delta, position_scale_contracts),
                    "label_time_to_next_action_seconds": (next_time - current_time).total_seconds(),
                    "label_status": "AVAILABLE",
                })
            else:
                row["label_status"] = "SAME_TIMESTAMP_TIE_ONLY"
        output.append(row)
    return output


__all__ = ["build_next_decision_labels", "position_delta_bucket"]
