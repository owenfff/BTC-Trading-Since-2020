"""Audit cross-venue event and hourly labels for state/action/timing consistency."""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_EVENTS = ROOT / "quant" / "outputs" / "cross_venue_model_dataset_v3.csv"
DEFAULT_TEMPORAL = ROOT / "quant" / "outputs" / "cross_venue_temporal_dataset_v3.csv"
DEFAULT_REPORT = ROOT / "quant" / "reports" / "cross_venue_temporal_label_audit.json"
DEFAULT_MARKDOWN = ROOT / "quant" / "reports" / "cross_venue_temporal_label_audit.md"
DEFAULT_BY_SYMBOL = ROOT / "quant" / "reports" / "cross_venue_temporal_label_audit_by_symbol.csv"
UTC = timezone.utc

LEGACY_ACTIONS = {
    "": "NO_TRADE",
    "NO_POSITION_CHANGE": "NO_TRADE",
    "HOLD_LONG": "NO_TRADE",
    "HOLD_SHORT": "NO_TRADE",
    "FLIP_LONG_TO_SHORT": "FLIP_SHORT",
    "FLIP_SHORT_TO_LONG": "FLIP_LONG",
}


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def state_key(row: Mapping[str, Any]) -> tuple[str, str]:
    return str(row.get("source_venue") or ""), str(row.get("canonical_asset") or row.get("symbol") or "")


def canonical_action(action: Any) -> str:
    raw = str(action or "").strip()
    return LEGACY_ACTIONS.get(raw, raw or "NO_TRADE")


def action_from_transition(before: float, after: float) -> str:
    epsilon = 1e-12
    if abs(after - before) <= epsilon:
        return "NO_TRADE"
    if abs(before) <= epsilon:
        return "OPEN_LONG" if after > 0 else "OPEN_SHORT"
    if before > 0 and after < 0:
        return "FLIP_SHORT"
    if before < 0 and after > 0:
        return "FLIP_LONG"
    if before > 0 and abs(after) <= epsilon:
        return "CLOSE_LONG"
    if before < 0 and abs(after) <= epsilon:
        return "CLOSE_SHORT"
    if before > 0 and after > before:
        return "ADD_LONG"
    if before < 0 and after < before:
        return "ADD_SHORT"
    return "REDUCE_LONG" if before > 0 else "REDUCE_SHORT"


def read_grouped(path: Path) -> dict[tuple[str, str], list[dict[str, Any]]]:
    grouped: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            grouped[state_key(row)].append(dict(row))
    for rows in grouped.values():
        rows.sort(key=lambda row: (parse_time(row.get("decision_time")) or datetime.max.replace(tzinfo=UTC), str(row.get("decision_episode_id"))))
    return dict(grouped)


def audit_event_rows(grouped: Mapping[tuple[str, str], list[Mapping[str, Any]]]) -> dict[str, Any]:
    checks = Counter()
    counts = Counter()
    by_symbol: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for key, rows in grouped.items():
        # The temporal replay intentionally merges historical aliases into a
        # canonical instrument (for example XBTUSD/XBTM21 -> BTC-PERP), but
        # event labels were originally built per raw symbol.  Validate the
        # next-event label within that raw-symbol stream; validating it after
        # canonical merging would falsely compare an alias's next event.
        label_groups: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
        for row in rows:
            label_groups[str(row.get("source_symbol") or row.get("symbol") or "")].append(row)
        previous_time: datetime | None = None
        for index, row in enumerate(rows):
            counts["rows"] += 1
            by_symbol[key]["event_rows"] += 1
            decision = parse_time(row.get("decision_time"))
            if decision is None:
                checks["invalid_decision_time"] += 1
            if previous_time is not None and decision is not None:
                if decision < previous_time:
                    checks["event_time_out_of_order"] += 1
                if decision == previous_time:
                    checks["same_timestamp_event_ties"] += 1
            previous_time = decision or previous_time

            before = number(row.get("raw_current_position_contracts"))
            after = number(row.get("raw_target_position_contracts"))
            observed = canonical_action(row.get("observed_action"))
            if before is None or after is None:
                checks["invalid_event_position"] += 1
            else:
                derived = action_from_transition(before, after)
                if observed != derived:
                    checks["event_action_target_mismatch"] += 1
                by_symbol[key][f"derived_{derived}"] += 1

            label_time = parse_time(row.get("label_next_decision_time"))
            if label_time is not None and decision is not None and label_time <= decision:
                checks["event_label_not_future"] += 1
            if str(row.get("label_status") or "") == "AVAILABLE" and label_time is None:
                checks["available_event_label_missing_time"] += 1

        for label_rows in label_groups.values():
            label_rows.sort(key=lambda row: (parse_time(row.get("decision_time")) or datetime.max.replace(tzinfo=UTC), str(row.get("decision_episode_id"))))
            actions_by_time: defaultdict[datetime, set[str]] = defaultdict(set)
            for label_row in label_rows:
                label_time = parse_time(label_row.get("decision_time"))
                if label_time is not None:
                    actions_by_time[label_time].add(canonical_action(label_row.get("observed_action")))
            for index, row in enumerate(label_rows):
                decision = parse_time(row.get("decision_time"))
                next_index = index + 1
                while next_index < len(label_rows) and parse_time(label_rows[next_index].get("decision_time")) == decision:
                    next_index += 1
                if next_index < len(label_rows) and str(row.get("label_status") or "") == "AVAILABLE":
                    next_time = parse_time(label_rows[next_index].get("decision_time"))
                    expected_actions = actions_by_time.get(next_time, set())
                    actual = canonical_action(row.get("label_next_action"))
                    if actual not in expected_actions:
                        checks["event_next_action_label_mismatch"] += 1
        by_symbol[key]["same_timestamp_event_ties"] += sum(
            1
            for left, right in zip(rows, rows[1:])
            if parse_time(left.get("decision_time")) is not None
            and parse_time(left.get("decision_time")) == parse_time(right.get("decision_time"))
        )
    return {"rows": counts["rows"], "checks": dict(checks), "by_symbol": by_symbol}


def audit_temporal_rows(
    grouped: Mapping[tuple[str, str], list[Mapping[str, Any]]],
    event_grouped: Mapping[tuple[str, str], list[Mapping[str, Any]]],
) -> dict[str, Any]:
    checks = Counter()
    counts = Counter()
    by_symbol: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
    for key, rows in grouped.items():
        event_rows = event_grouped.get(key, [])
        event_times = [parse_time(row.get("decision_time")) for row in event_rows]
        event_times = [value for value in event_times if value is not None]
        event_actions = [canonical_action(row.get("observed_action")) for row in event_rows]
        previous_time: datetime | None = None
        for row in rows:
            counts["rows"] += 1
            by_symbol[key]["temporal_rows"] += 1
            if str(row.get("model_eligible") or "").lower() == "true":
                counts["eligible_rows"] += 1
                by_symbol[key]["eligible_rows"] += 1
            decision = parse_time(row.get("decision_time"))
            label_time = parse_time(row.get("label_next_decision_time"))
            if decision is None:
                checks["invalid_decision_time"] += 1
            if label_time is None or decision is None or label_time <= decision:
                checks["temporal_label_not_future"] += 1
            if previous_time is not None and decision is not None and decision <= previous_time:
                checks["temporal_clock_not_strict"] += 1
            previous_time = decision or previous_time

            before = number(row.get("raw_current_position_contracts"))
            after = number(row.get("raw_next_target_position_contracts"))
            label = canonical_action(row.get("label_next_action"))
            if before is None or after is None:
                checks["invalid_temporal_position"] += 1
            else:
                derived = action_from_transition(before, after)
                if derived != label:
                    checks["temporal_label_target_mismatch"] += 1
                by_symbol[key][f"label_{label}"] += 1
                expected_type = "NO_TRADE" if label == "NO_TRADE" else "NEXT_BAR_TRANSITION"
                if str(row.get("temporal_row_type")) != expected_type:
                    checks["temporal_type_label_mismatch"] += 1

            if decision is not None and label_time is not None:
                gap = (label_time - decision).total_seconds()
                if abs(gap - 3600.0) > 1e-6:
                    checks["temporal_non_one_hour_gap"] += 1
                if event_times:
                    first = bisect_left(event_times, decision)
                    last = bisect_left(event_times, label_time)
                    interval_actions = event_actions[first:last]
                    non_idle = [action for action in interval_actions if action != "NO_TRADE"]
                    by_symbol[key]["source_actions_in_hour"] += len(non_idle)
                    if label == "NO_TRADE" and non_idle:
                        checks["net_zero_label_hides_source_action"] += 1
                        by_symbol[key]["net_zero_label_hides_source_action"] += 1
        by_symbol[key]["temporal_checks"] += sum(value for name, value in checks.items() if name.startswith("temporal_"))
    return {"rows": counts["rows"], "eligible_rows": counts["eligible_rows"], "checks": dict(checks), "by_symbol": by_symbol}


def _merge_by_symbol(*audits: Mapping[str, Any]) -> list[dict[str, Any]]:
    keys: set[tuple[str, str]] = set()
    for audit in audits:
        keys.update(audit.get("by_symbol", {}).keys())
    output: list[dict[str, Any]] = []
    for key in sorted(keys):
        row: dict[str, Any] = {"source_venue": key[0], "canonical_asset": key[1]}
        for audit in audits:
            values = audit.get("by_symbol", {}).get(key, {})
            row.update({str(name): int(value) for name, value in values.items()})
        output.append(row)
    return output


def audit(events_path: Path = DEFAULT_EVENTS, temporal_path: Path = DEFAULT_TEMPORAL) -> dict[str, Any]:
    events = read_grouped(events_path)
    temporal = read_grouped(temporal_path)
    event_audit = audit_event_rows(events)
    temporal_audit = audit_temporal_rows(temporal, events)
    checks = Counter(event_audit["checks"])
    checks.update(temporal_audit["checks"])
    hard_check_names = {
        "invalid_decision_time",
        "event_time_out_of_order",
        "invalid_event_position",
        "event_action_target_mismatch",
        "event_label_not_future",
        "available_event_label_missing_time",
        "event_next_action_label_mismatch",
        "temporal_label_not_future",
        "temporal_clock_not_strict",
        "invalid_temporal_position",
        "temporal_label_target_mismatch",
        "temporal_type_label_mismatch",
    }
    hard_failures = {name: value for name, value in checks.items() if name in hard_check_names and value}
    warnings = {name: value for name, value in checks.items() if name not in hard_check_names and value}
    result = {
        "report_version": "M15-TEMPORAL-LABEL-AUDIT-1.0",
        "status": "BLOCKED" if hard_failures else ("PASS_WITH_WARNINGS" if warnings else "PASS"),
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "event_dataset": str(events_path.relative_to(ROOT)),
        "temporal_dataset": str(temporal_path.relative_to(ROOT)),
        "event_keys": len(events),
        "temporal_keys": len(temporal),
        "event_rows": event_audit["rows"],
        "temporal_rows": temporal_audit["rows"],
        "temporal_eligible_rows": temporal_audit["eligible_rows"],
        "checks": dict(checks),
        "hard_failures": hard_failures,
        "warnings": warnings,
        "interpretation": {
            "event_action_target_consistency": "PASS" if not any(name in hard_failures for name in ("event_action_target_mismatch", "event_next_action_label_mismatch")) else "BLOCKED",
            "temporal_action_target_consistency": "PASS" if not any(name in hard_failures for name in ("temporal_label_target_mismatch", "temporal_type_label_mismatch")) else "BLOCKED",
            "same_hour_net_zero_warning": "Some hourly labels can hide offsetting source actions; this is retained as a warning, not silently relabeled.",
            "execution_semantics": "A decision at t uses state strictly before t and labels the net target before the next hourly decision; autonomous replay executes at the next bar open.",
        },
        "by_symbol": _merge_by_symbol(event_audit, temporal_audit),
    }
    return result


def write_outputs(result: Mapping[str, Any], report_path: Path, markdown_path: Path, by_symbol_path: Path) -> None:
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    by_symbol = list(result.get("by_symbol", []))
    fields: list[str] = []
    for row in by_symbol:
        for field in row:
            if field not in fields:
                fields.append(field)
    with by_symbol_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["source_venue", "canonical_asset"])
        writer.writeheader()
        writer.writerows(by_symbol)
    checks = result.get("checks", {})
    markdown_path.write_text(
        "\n".join([
            "# Cross-Venue Temporal Label Audit",
            "",
            f"- status: **{result['status']}**",
            f"- event rows: `{result['event_rows']}` across `{result['event_keys']}` state keys",
            f"- temporal rows: `{result['temporal_rows']}`; eligible: `{result['temporal_eligible_rows']}`",
            f"- strategy fidelity: `{result['strategy_fidelity']}`",
            "",
            "## Checks",
            "",
            "| check | count | classification |",
            "| --- | ---: | --- |",
            *[f"| `{name}` | {value} | {'HARD_FAILURE' if name in result.get('hard_failures', {}) else 'WARNING' if name in result.get('warnings', {}) else 'PASS'} |" for name, value in sorted(checks.items())],
            "",
            "## Interpretation",
            "",
            f"- event action/target consistency: **{result['interpretation']['event_action_target_consistency']}**",
            f"- temporal action/target consistency: **{result['interpretation']['temporal_action_target_consistency']}**",
            f"- same-hour net-zero: {result['interpretation']['same_hour_net_zero_warning']}",
            f"- execution semantics: {result['interpretation']['execution_semantics']}",
            "",
            "Detailed per-venue/per-instrument counts are in `cross_venue_temporal_label_audit_by_symbol.csv`.",
        ]) + "\n",
        encoding="utf-8",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument("--temporal", type=Path, default=DEFAULT_TEMPORAL)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument("--markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--by-symbol", type=Path, default=DEFAULT_BY_SYMBOL)
    args = parser.parse_args()
    try:
        result = audit(args.events.resolve(), args.temporal.resolve())
        write_outputs(result, args.report.resolve(), args.markdown.resolve(), args.by_symbol.resolve())
    except (OSError, ValueError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "TEMPORAL_LABEL_AUDIT_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": result["status"], "event_rows": result["event_rows"], "temporal_rows": result["temporal_rows"], "report": str(args.report.resolve())}, ensure_ascii=False))
    return 0 if result["status"] != "BLOCKED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
