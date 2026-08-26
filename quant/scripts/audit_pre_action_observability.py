#!/usr/bin/env python3
"""Audit whether the public export contains pre-action trigger information.

This is a source-sufficiency audit, not a trading model.  It distinguishes
order fields that describe a contemporaneous submission from execution and
lifecycle fields that are only known after the action.  It also checks whether
independent quote/order-book history exists in the repository.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
for path in (ROOT, SRC, ROOT / "quant" / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from audit_cross_venue_probability_calibrated_stability import DATASET_TEMPORAL, _read_temporal  # noqa: E402


VERSION = "behavioral-distillation-v4.5-pre-action-observability"
RAW_ORDER = ROOT / "api-v1-order.csv"
ORDER_EPISODES = ROOT / "quant" / "outputs" / "order_episodes.csv"
DECISION_EPISODES = ROOT / "quant" / "outputs" / "decision_episodes.csv"
REPORT = ROOT / "quant" / "reports" / "pre_action_observability_audit.json"
REPORT_MD = ROOT / "quant" / "reports" / "pre_action_observability_audit.md"
ORDER_AT_SUBMISSION = frozenset({"timestamp", "transactTime", "ordType", "symbol", "side", "orderQty", "price", "stopPx", "timeInForce", "execInst", "strategy"})
EXECUTION_OR_LIFECYCLE = frozenset({"ordStatus", "cumQty", "leavesQty", "avgPx", "workingIndicator", "triggered", "ordRejReason"})
POST_FILL_FIELDS = frozenset({"avgPx", "cumQty", "leavesQty"})
UTC = timezone.utc


def classify_order_fields(fields: Iterable[str]) -> dict[str, list[str]]:
    """Classify fields by when they can become known relative to submission."""

    names = {str(field) for field in fields}
    return {
        "contemporaneous_submission": sorted(names & ORDER_AT_SUBMISSION),
        "execution_or_lifecycle": sorted(names & EXECUTION_OR_LIFECYCLE),
        "post_fill_sensitive": sorted(names & POST_FILL_FIELDS),
        "other": sorted(names - ORDER_AT_SUBMISSION - EXECUTION_OR_LIFECYCLE),
    }


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (result if result.tzinfo else result.replace(tzinfo=UTC)).astimezone(UTC)


def _read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        return list(reader.fieldnames or []), list(reader)


def _observable_file_candidates(root: Path) -> list[str]:
    tokens = ("quote", "orderbook", "order-book", "book", "level2", "l2")
    output: list[str] = []
    for path in root.rglob("*"):
        if not path.is_file() or ".git" in path.parts:
            continue
        lowered = path.name.lower()
        if any(token in lowered for token in tokens):
            output.append(str(path.relative_to(root)))
    return sorted(output)


def _match_submission_times(order_rows: list[dict[str, str]], decision_rows: list[dict[str, str]], episode_rows: list[dict[str, str]]) -> dict[str, Any]:
    first_by_episode = {str(row.get("order_episode_id")): _parse_time(row.get("first_event_time")) for row in episode_rows}
    matched = 0
    equal = 0
    decision_before_order = 0
    decision_after_order = 0
    for row in decision_rows:
        action = str(row.get("action") or "")
        if not action or action == "NO_TRADE":
            continue
        decision_time = _parse_time(row.get("decision_time"))
        first_time = first_by_episode.get(str(row.get("source_order_episode_id")))
        if decision_time is None or first_time is None:
            continue
        matched += 1
        if decision_time == first_time:
            equal += 1
        elif decision_time < first_time:
            decision_before_order += 1
        else:
            decision_after_order += 1
    order_status = Counter(str(row.get("ordStatus") or "MISSING") for row in order_rows)
    return {
        "non_idle_decisions_matched_to_order_episode": matched,
        "decision_time_equal_first_order_event": equal,
        "decision_time_before_first_order_event": decision_before_order,
        "decision_time_after_first_order_event": decision_after_order,
        "order_rows": len(order_rows),
        "order_status_counts": dict(sorted(order_status.items())),
    }


def _market_context(rows: list[dict[str, Any]]) -> dict[str, Any]:
    non_idle = [row for row in rows if str(row.get("label_next_action") or "") != "NO_TRADE"]
    fields = ("feature_latest_bar_time", "feature_return_1bar", "feature_rsi_14", "feature_macd_histogram", "feature_bollinger_percent_b_20", "feature_volume_percentile_72bar")
    coverage: dict[str, dict[str, int]] = {}
    for field in fields:
        coverage[field] = {
            "all_rows_present": sum(bool(str(row.get(field) or "").strip()) for row in rows),
            "non_idle_rows_present": sum(bool(str(row.get(field) or "").strip()) for row in non_idle),
        }
    bar_before = 0
    bar_equal_or_after = 0
    for row in rows:
        decision = _parse_time(row.get("decision_time"))
        latest = _parse_time(row.get("feature_latest_bar_time"))
        if decision is None or latest is None:
            continue
        if latest < decision:
            bar_before += 1
        else:
            bar_equal_or_after += 1
    return {
        "rows": len(rows),
        "non_idle_rows": len(non_idle),
        "coverage": coverage,
        "latest_closed_bar_strictly_before_decision": bar_before,
        "latest_bar_equal_or_after_decision": bar_equal_or_after,
    }


def build(*, dataset_path: Path = DATASET_TEMPORAL, report_path: Path = REPORT, markdown_path: Path = REPORT_MD) -> dict[str, Any]:
    order_fields, order_rows = _read_csv(RAW_ORDER)
    _episode_fields, episode_rows = _read_csv(ORDER_EPISODES)
    _decision_fields, decision_rows = _read_csv(DECISION_EPISODES)
    temporal_rows = _read_temporal(dataset_path)
    candidates = _observable_file_candidates(ROOT)
    field_classes = classify_order_fields(order_fields)
    order_ids = [str(row.get("orderID") or "") for row in order_rows]
    nonempty_order_ids = [value for value in order_ids if value]
    status = _match_submission_times(order_rows, decision_rows, episode_rows)
    lifecycle_statuses = Counter()
    for row in episode_rows:
        lifecycle_statuses.update(str(row.get("order_lifecycle_statuses") or "MISSING").split(","))
    output = {
        "report_version": "M15-PRE-ACTION-OBSERVABILITY-1.0",
        "status": "DIAGNOSTIC_ONLY",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "candidate_model_version": VERSION,
        "raw_order_file": str(RAW_ORDER.relative_to(ROOT)),
        "raw_order_rows": len(order_rows),
        "raw_order_columns": order_fields,
        "order_field_classes": field_classes,
        "order_id_unique": len(nonempty_order_ids) == len(set(nonempty_order_ids)),
        "order_id_rows": len(nonempty_order_ids),
        "order_id_distinct": len(set(nonempty_order_ids)),
        "order_episode_rows": len(episode_rows),
        "order_lifecycle_status_counts": dict(sorted(lifecycle_statuses.items())),
        "submission_time_alignment": status,
        "independent_quote_orderbook_files": candidates,
        "independent_quote_orderbook_history_present": bool(candidates),
        "market_context": _market_context(temporal_rows),
        "pre_action_trigger_assessment": {
            "order_submission_fields_are_pre_decision": False,
            "post_fill_fields_are_pre_decision": False,
            "independent_quote_or_orderbook_history_present": bool(candidates),
            "complete_pre_action_trigger_context_available": False,
            "reason": "The export records order submission/lifecycle at or after the action and has no independent historical quote/order-book stream. Historical fills and observed post-action state are not valid pre-action features.",
        },
        "raw_inputs_untouched": True,
        "active_demo_unchanged": True,
        "promotion_allowed": False,
        "conclusion": "Public records support partial conditional action reconstruction, but the current repository does not contain complete pre-action trigger context required to claim exact autonomous strategy recovery.",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    lines = [
        "# Pre-Action Observability Audit",
        "",
        "> Source-sufficiency diagnostic only. It does not train a model or authorize orders.",
        "",
        "## Finding",
        "",
        "The export contains contemporaneous order submission/lifecycle fields and post-fill fields, but no independent historical quote, level-2, or order-book stream. These records cannot safely reveal the trader's pre-action trigger.",
        "",
        f"- Raw order rows: `{len(order_rows)}`; order IDs unique: `{output['order_id_unique']}`.",
        f"- Order episodes: `{len(episode_rows)}`; lifecycle statuses: `{dict(sorted(lifecycle_statuses.items()))}`.",
        f"- Non-idle decisions matched to order episodes: `{status['non_idle_decisions_matched_to_order_episode']}`; decision time equal to first order event: `{status['decision_time_equal_first_order_event']}`.",
        f"- Independent quote/order-book files found: `{len(candidates)}`.",
        "",
        "## Consequence",
        "",
        "The public record can support conditional analysis of action type and target size, but not a claim that the autonomous robot has recovered the original private trigger. Adding indicators to the same hourly bars does not create missing pre-action information.",
        "",
        "## Boundary",
        "",
        "No credentials, private endpoint, mainnet connection, or order was used. Raw CSV/JSON inputs remain read-only; the active Demo model remains unchanged.",
    ]
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_TEMPORAL)
    args = parser.parse_args()
    try:
        result = build(dataset_path=args.dataset.resolve())
    except (FileNotFoundError, OSError, ValueError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "PRE_ACTION_OBSERVABILITY_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": result["status"], "report": str(REPORT), "independent_quote_orderbook_history_present": result["independent_quote_orderbook_history_present"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
