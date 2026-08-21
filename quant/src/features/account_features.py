"""Past-only account and behavior features for decision timestamps."""

from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from typing import Any


UTC = timezone.utc
POSITION_SCALE_CONTRACTS = 10_000_000
RECENT_WINDOW = timedelta(hours=24)


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


def _action_kind(action: str) -> str:
    if "FLIP" in action:
        return "FLIP"
    if "ADD" in action:
        return "ADD"
    if "REDUCE" in action or "CLOSE" in action:
        return "REDUCE"
    return "OTHER"


def build_account_features(
    decisions: list[dict[str, Any]],
    *,
    cycles: list[dict[str, Any]] | None = None,
    trade_actions: list[dict[str, Any]] | None = None,
    order_episodes: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Return one row per decision, with all state sourced from prior rows."""
    decisions = sorted(decisions, key=lambda row: (parse_utc(row.get("decision_time")) or datetime.max.replace(tzinfo=UTC), str(row.get("decision_episode_id", ""))))
    cycles = sorted(cycles or [], key=lambda row: parse_utc(row.get("close_time")) or datetime.max.replace(tzinfo=UTC))
    actions = sorted(trade_actions or [], key=lambda row: parse_utc(row.get("event_time")) or datetime.max.replace(tzinfo=UTC))
    orders_by_id = {str(row.get("order_episode_id", "")): row for row in (order_episodes or [])}
    cycle_index = 0
    action_index = 0
    prior_decisions: deque[tuple[datetime, str]] = deque()
    prior_action_kinds: deque[tuple[datetime, str]] = deque()
    cumulative_realised = 0.0
    cumulative_fee = 0.0
    cumulative_funding = 0.0
    peak_realised = 0.0
    last_closed_pnl: float | None = None
    active_cycle_start: datetime | None = None
    previous_action = ""
    previous_order_style = ""
    previous_ordering_confidence = ""
    previous_accounting_confidence = ""
    maximum_abs_position_seen = 0.0
    output: list[dict[str, Any]] = []

    for decision in decisions:
        decision_time = parse_utc(decision.get("decision_time"))
        if decision_time is None:
            continue
        while prior_decisions and prior_decisions[0][0] >= decision_time - RECENT_WINDOW:
            break
        while prior_decisions and prior_decisions[0][0] < decision_time - RECENT_WINDOW:
            prior_decisions.popleft()
        while prior_action_kinds and prior_action_kinds[0][0] < decision_time - RECENT_WINDOW:
            prior_action_kinds.popleft()
        while cycle_index < len(cycles):
            close_time = parse_utc(cycles[cycle_index].get("close_time"))
            if close_time is None or close_time >= decision_time:
                break
            cycle = cycles[cycle_index]
            pnl = _number(cycle.get("gross_pnl_analytical"))
            funding = _number(cycle.get("funding"))
            cumulative_realised += pnl
            cumulative_funding += funding
            peak_realised = max(peak_realised, cumulative_realised)
            last_closed_pnl = pnl
            cycle_index += 1
        while action_index < len(actions):
            event_time = parse_utc(actions[action_index].get("event_time"))
            if event_time is None or event_time >= decision_time:
                break
            cumulative_fee += _number(actions[action_index].get("execComm_raw"))
            action_index += 1

        position_before = _number(decision.get("position_before"))
        maximum_abs_position_seen = max(maximum_abs_position_seen, abs(position_before))
        current_cycle_duration = (decision_time - active_cycle_start).total_seconds() if active_cycle_start and active_cycle_start < decision_time and position_before else None
        recent_counts = {"ADD": 0, "REDUCE": 0, "FLIP": 0}
        for prior_time, kind in prior_action_kinds:
            if not (decision_time - RECENT_WINDOW <= prior_time < decision_time):
                continue
            if kind in recent_counts:
                recent_counts[kind] += 1
        strict_prior_times = [prior_time for prior_time, _ in prior_decisions if prior_time < decision_time]
        strict_previous = previous_action if strict_prior_times and max(strict_prior_times) < decision_time else ""
        strict_previous_style = previous_order_style if strict_prior_times and max(strict_prior_times) < decision_time else ""
        strict_previous_ordering = previous_ordering_confidence if strict_prior_times and max(strict_prior_times) < decision_time else ""
        strict_previous_accounting = previous_accounting_confidence if strict_prior_times and max(strict_prior_times) < decision_time else ""
        row = {
            "feature_current_net_position_contracts": position_before,
            "feature_current_normalized_exposure": position_before / POSITION_SCALE_CONTRACTS,
            "feature_position_scale_contracts": POSITION_SCALE_CONTRACTS,
            "feature_cycle_duration_seconds": current_cycle_duration,
            "feature_latest_action": strict_previous,
            "feature_recent_add_count_24h": recent_counts["ADD"],
            "feature_recent_reduce_count_24h": recent_counts["REDUCE"],
            "feature_recent_flip_count_24h": recent_counts["FLIP"],
            "feature_recent_realised_outcome": last_closed_pnl,
            "feature_realised_drawdown": cumulative_realised - peak_realised,
            "feature_fee_accumulation_raw": cumulative_fee,
            "feature_funding_accumulation_raw": cumulative_funding,
            "feature_order_execution_style": strict_previous_style,
            "feature_ordering_confidence": strict_previous_ordering,
            "feature_accounting_confidence": strict_previous_accounting,
            "feature_history_last_decision_time": iso_utc(max(strict_prior_times)) if strict_prior_times else "",
        }
        output.append({"decision_episode_id": str(decision.get("decision_episode_id", "")), "decision_time": decision_time, **row})

        action = str(decision.get("action", ""))
        kind = _action_kind(action)
        prior_decisions.append((decision_time, action))
        prior_action_kinds.append((decision_time, kind))
        previous_action = action
        previous_ordering_confidence = str(decision.get("ordering_confidence", ""))
        previous_accounting_confidence = str(decision.get("accounting_confidence", ""))
        source_order_id = str(decision.get("source_order_episode_id", ""))
        current_order = orders_by_id.get(source_order_id)
        if current_order and current_order.get("execution_count"):
            previous_order_style = f"{current_order.get('ordType', '') or 'UNKNOWN'}_{'MULTI_FILL' if int(current_order.get('execution_count') or 0) > 1 else 'SINGLE_FILL'}"
        target_position = _number(decision.get("target_position"))
        if target_position and active_cycle_start is None:
            active_cycle_start = decision_time
        if not target_position:
            active_cycle_start = None
    return output


__all__ = ["POSITION_SCALE_CONTRACTS", "build_account_features"]
