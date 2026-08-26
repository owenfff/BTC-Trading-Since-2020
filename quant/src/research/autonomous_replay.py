"""Strict autonomous state handling for causal model evaluation.

Historical account/position columns are useful for conditional behavior
fidelity, but they are not valid inputs for a counterfactual robot replay.
This module replaces those dynamic fields with a deterministic simulated state
and merges same-time aliases before updating that state.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Mapping

from quant_bot.strategy.base import StrategySignal
from quant_bot.strategy.feature_contract import strategy_input_from_row


UTC = timezone.utc
STATE_FIELDS = (
    "feature_current_net_position_contracts",
    "feature_current_normalized_exposure",
    "feature_position_scale_contracts",
    "feature_cycle_duration_seconds",
    "feature_latest_action",
    "feature_recent_add_count_24h",
    "feature_recent_reduce_count_24h",
    "feature_recent_flip_count_24h",
    "feature_recent_realised_outcome",
    "feature_realised_drawdown",
    "feature_fee_accumulation_raw",
    "feature_funding_accumulation_raw",
    "feature_order_execution_style",
    "feature_ordering_confidence",
    "feature_accounting_confidence",
    "feature_history_last_decision_time",
)


def parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    return (result if result.tzinfo else result.replace(tzinfo=UTC)).astimezone(UTC)


def number(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def state_key(row: Mapping[str, Any]) -> str:
    venue = str(row.get("source_venue") or "BITMEX")
    canonical = str(row.get("canonical_asset") or row.get("feature_symbol") or row.get("symbol") or "UNKNOWN")
    return f"{venue}:{canonical}"


@dataclass
class AutonomousState:
    current_position_contracts: float = 0.0
    current_normalized_exposure: float = 0.0
    cycle_start: datetime | None = None
    latest_action: str = ""
    recent_add_count: int = 0
    recent_reduce_count: int = 0
    recent_flip_count: int = 0
    recent_realised_outcome: float = 0.0
    realised_drawdown: float = 0.0
    fee_accumulation_raw: float = 0.0
    funding_accumulation_raw: float = 0.0
    last_execution_time: datetime | None = None

    def apply_execution(self, target: float, action: str, execution_time: datetime, fee_rate: float = 0.0005) -> None:
        before = self.current_normalized_exposure
        delta = target - before
        if abs(delta) <= 1e-12:
            return
        self.current_normalized_exposure = target
        self.fee_accumulation_raw += abs(delta) * fee_rate
        self.latest_action = action
        if "ADD" in action:
            self.recent_add_count += 1
        elif "REDUCE" in action or "CLOSE" in action:
            self.recent_reduce_count += 1
        elif "FLIP" in action:
            self.recent_flip_count += 1
        if target == 0:
            self.cycle_start = None
        elif before == 0 or (before > 0) != (target > 0):
            self.cycle_start = execution_time
        self.last_execution_time = execution_time


def _action_kind(action: str) -> str:
    if "FLIP" in action:
        return "FLIP"
    if "ADD" in action:
        return "ADD"
    if "REDUCE" in action or "CLOSE" in action:
        return "REDUCE"
    return "OTHER"


def override_dynamic_state(row: Mapping[str, Any], state: AutonomousState, scale: float, decision_time: datetime) -> dict[str, Any]:
    """Return a row with every teacher-dynamic field replaced by bot state."""

    output = dict(row)
    current_contracts = state.current_normalized_exposure * scale
    output.update({
        "feature_current_net_position_contracts": current_contracts,
        "feature_current_normalized_exposure": state.current_normalized_exposure,
        "feature_position_scale_contracts": scale,
        "feature_cycle_duration_seconds": (decision_time - state.cycle_start).total_seconds() if state.cycle_start and state.current_normalized_exposure else None,
        "feature_latest_action": state.latest_action,
        "feature_recent_add_count_24h": state.recent_add_count,
        "feature_recent_reduce_count_24h": state.recent_reduce_count,
        "feature_recent_flip_count_24h": state.recent_flip_count,
        "feature_recent_realised_outcome": state.recent_realised_outcome,
        "feature_realised_drawdown": state.realised_drawdown,
        "feature_fee_accumulation_raw": state.fee_accumulation_raw,
        "feature_funding_accumulation_raw": state.funding_accumulation_raw,
        "feature_order_execution_style": "AUTONOMOUS_LIMIT_POST_ONLY",
        "feature_ordering_confidence": "HIGH",
        "feature_accounting_confidence": "HIGH",
        "feature_history_last_decision_time": state.last_execution_time.isoformat().replace("+00:00", "Z") if state.last_execution_time else "",
        "autonomous_state_source": "SIMULATED_ZERO_START",
        "teacher_state_fields_overridden": ",".join(STATE_FIELDS),
    })
    return output


def merge_same_time_signals(signals: Iterable[tuple[Mapping[str, Any], StrategySignal]], *, key: str, decision_time: datetime) -> dict[str, Any] | None:
    items = list(signals)
    if not items:
        return None
    total_weight = sum(max(1e-6, min(1.0, float(signal.confidence))) for _, signal in items)
    target = sum(float(signal.target_exposure) * max(1e-6, min(1.0, float(signal.confidence))) for _, signal in items) / total_weight
    strongest_row, strongest = max(items, key=lambda pair: float(pair[1].confidence))
    return {
        "venue_symbol": key,
        "decision_time": decision_time,
        "target_exposure": max(-1.0, min(1.0, target)),
        "action": str(strongest.action),
        "confidence": float(strongest.confidence),
        "historical_symbols": tuple(sorted(str(row.get("symbol") or row.get("source_symbol") or "") for row, _ in items)),
        "source_signals": tuple({
            "symbol": str(row.get("symbol") or row.get("source_symbol") or ""),
            "action": str(signal.action),
            "target_exposure": float(signal.target_exposure),
            "confidence": float(signal.confidence),
        } for row, signal in items),
        "autonomous_state_source": "SIMULATED_ZERO_START",
    }


def roll_forward_predictions(
    model: Any,
    rows: Iterable[Mapping[str, Any]],
    scales: Mapping[str, float],
    *,
    market_bar_opens: Mapping[str, list[datetime]] | None = None,
    fee_rate: float = 0.0005,
    include_state_overrides: bool = True,
) -> dict[str, Any]:
    """Predict chronologically with zero-start simulated state.

    Same-time rows for the same venue/canonical instrument are predicted from
    one pre-decision state, merged by confidence, and then scheduled for the
    next available bar open.  No teacher dynamic field is read for the model
    call; raw market/instrument fields remain from the dataset.
    """

    # Rows are never mutated by the replay path; sorting references avoids a
    # second full copy of large temporal datasets before grouping them.
    ordered = sorted(rows, key=lambda row: (parse_time(row.get("decision_time")) or datetime.max.replace(tzinfo=UTC), state_key(row), str(row.get("decision_episode_id"))))
    states: dict[str, AutonomousState] = defaultdict(AutonomousState)
    pending: dict[str, list[tuple[datetime, float, str]]] = defaultdict(list)
    row_predictions: list[tuple[dict[str, Any], StrategySignal]] = []
    merged_events: list[dict[str, Any]] = []
    overrides: list[dict[str, Any]] = []
    grouped: defaultdict[tuple[str, datetime], list[dict[str, Any]]] = defaultdict(list)
    for row in ordered:
        when = parse_time(row.get("decision_time"))
        if when is not None:
            grouped[(state_key(row), when)].append(row)
    for (key, when), group in grouped.items():
        state = states[key]
        while pending[key] and pending[key][0][0] <= when:
            execution_time, target, action = pending[key].pop(0)
            state.apply_execution(target, action, execution_time, fee_rate)
        scale = max(1.0, number(scales.get(key), number(group[0].get("feature_position_scale_contracts"), 1.0)))
        local: list[tuple[dict[str, Any], StrategySignal]] = []
        for row in group:
            overridden = override_dynamic_state(row, state, scale, when)
            signal = model.predict(strategy_input_from_row(overridden))
            local.append((row, signal))
            if include_state_overrides:
                overrides.append({"decision_episode_id": row.get("decision_episode_id"), "state_key": key, "teacher_state_fields_overridden": list(STATE_FIELDS)})
            row_predictions.append((row, signal))
        merged = merge_same_time_signals(local, key=key, decision_time=when)
        if merged is None:
            continue
        merged_events.append(merged)
        bar_opens = (market_bar_opens or {}).get(key, [])
        index = bisect_right(bar_opens, when)
        execution_time = bar_opens[index] if index < len(bar_opens) else when + timedelta(hours=1)
        pending[key].append((execution_time, float(merged["target_exposure"]), str(merged["action"])))
    return {
        "row_predictions": row_predictions,
        "merged_events": merged_events,
        "state_source": "SIMULATED_ZERO_START",
        "teacher_state_fields_consumed": 0,
        "teacher_state_fields_overridden": list(STATE_FIELDS),
        "state_overrides": overrides,
    }


def fit_window_scales(train_rows: Iterable[Mapping[str, Any]]) -> dict[str, float]:
    maxima: defaultdict[str, float] = defaultdict(float)
    for row in train_rows:
        key = state_key(row)
        for field in ("raw_current_position_contracts", "raw_target_position_contracts", "raw_next_target_position_contracts", "observed_position_delta_contracts", "label_next_target_position_contracts"):
            value = number(row.get(field), 0.0)
            maxima[key] = max(maxima[key], abs(value))
    return {key: max(1.0, value) for key, value in maxima.items()}


def normalize_window_rows(rows: Iterable[Mapping[str, Any]], train_rows: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, float]]:
    """Normalize contract positions using only the current window's train rows."""

    scales = fit_window_scales(train_rows)
    output: list[dict[str, Any]] = []
    for original in rows:
        row = dict(original)
        key = state_key(row)
        scale = scales.get(key)
        if scale is None:
            row["position_scale_fit_available"] = False
            row["model_eligible"] = False
            output.append(row)
            continue
        current = number(row.get("raw_current_position_contracts"), number(row.get("observed_position_before_contracts"), 0.0))
        next_target = row.get("raw_next_target_position_contracts", row.get("label_next_target_position_contracts", ""))
        row["feature_position_scale_contracts"] = scale
        row["feature_current_net_position_contracts"] = current
        row["feature_current_normalized_exposure"] = current / scale
        if next_target not in (None, ""):
            row["label_next_target_exposure"] = number(next_target) / scale
        row["position_scale_fit_available"] = True
        row["model_eligible"] = str(row.get("row_market_coverage_status", row.get("market_coverage_status", "PASS"))) == "PASS" and str(row.get("label_status")) == "AVAILABLE"
        output.append(row)
    return output, scales


__all__ = [
    "AutonomousState",
    "STATE_FIELDS",
    "fit_window_scales",
    "merge_same_time_signals",
    "normalize_window_rows",
    "override_dynamic_state",
    "roll_forward_predictions",
    "state_key",
]
