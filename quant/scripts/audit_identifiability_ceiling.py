#!/usr/bin/env python3
"""Measure the gap between event-conditioned behavior and autonomous timing.

An event-conditioned benchmark is intentionally allowed to know that a
non-idle event occurred and to consume the historical state visible at that
event.  It estimates how much action-family/target information is present in
the public record once the impossible timing problem is removed.  It is not a
deployable strategy and cannot be used to authorize orders.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
for path in (ROOT, SRC, ROOT / "quant" / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from audit_cross_venue_probability_calibrated_stability import DATASET_TEMPORAL, _behavior_metrics, _read_temporal  # noqa: E402
from audit_shared_intent_timing import chronological_three_way  # noqa: E402
from quant_bot.strategy.feature_contract import strategy_input_from_row  # noqa: E402
from quant_bot.strategy.supervised_models import CrossAssetNumpyLogisticStrategy  # noqa: E402
from research.autonomous_replay import normalize_window_rows  # noqa: E402


VERSION = "behavioral-distillation-v4.4-identifiability-ceiling"
REPORT = ROOT / "quant" / "reports" / "identifiability_ceiling_audit.json"
REPORT_MD = ROOT / "quant" / "reports" / "identifiability_ceiling_audit.md"
PER_SYMBOL = ROOT / "quant" / "reports" / "identifiability_ceiling_by_venue.csv"
IDLE = frozenset({"NO_TRADE", "HOLD_LONG", "HOLD_SHORT"})
TIMING_REPORT = ROOT / "quant" / "reports" / "shared_intent_timing_audit.json"


def event_rows(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    """Keep only labeled non-idle events for the oracle-timing benchmark."""

    return [
        dict(row)
        for row in rows
        if str(row.get("model_eligible")).lower() == "true"
        and str(row.get("label_status")) == "AVAILABLE"
        and str(row.get("label_next_action") or "") not in IDLE
    ]


def _fit_event_model(rows: list[dict[str, Any]]) -> CrossAssetNumpyLogisticStrategy:
    train = [dict(row, dataset_split="TRAIN") for row in rows if row.get("label_next_action")]
    if not train:
        raise ValueError("event-conditioned model requires non-idle labeled rows")
    model = CrossAssetNumpyLogisticStrategy(
        target_l2=1.0,
        class_weighting="balanced",
        enforce_action_target_consistency=False,
    ).fit(train)
    model.version = VERSION
    return model


def _predict(model: CrossAssetNumpyLogisticStrategy, rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], Any]]:
    output: list[tuple[dict[str, Any], Any]] = []
    for row in rows:
        try:
            output.append((row, model.predict(strategy_input_from_row(row))))
        except (KeyError, TypeError, ValueError):
            continue
    return output


def _timing_results() -> dict[str, dict[str, Any]]:
    if not TIMING_REPORT.exists():
        return {}
    try:
        payload = json.loads(TIMING_REPORT.read_text(encoding="utf-8"))
        return {str(item.get("venue")): item for item in payload.get("venue_results", [])}
    except (OSError, ValueError, TypeError):
        return {}


def build(*, dataset_path: Path = DATASET_TEMPORAL, report_path: Path = REPORT, markdown_path: Path = REPORT_MD, per_venue_path: Path = PER_SYMBOL) -> dict[str, Any]:
    rows = _read_temporal(dataset_path)
    timing = _timing_results()
    results: list[dict[str, Any]] = []
    distribution: dict[str, dict[str, int]] = {}
    per_venue: list[dict[str, Any]] = []
    for venue in sorted({str(row.get("source_venue") or "UNKNOWN") for row in rows}):
        source = [row for row in rows if str(row.get("source_venue") or "UNKNOWN") == venue]
        train_raw, _calibration_raw, test_raw = chronological_three_way(source)
        train, _scales = normalize_window_rows(train_raw, train_raw)
        test, _ = normalize_window_rows(test_raw, train_raw)
        train_events = event_rows(train)
        test_events = event_rows(test)
        counts = Counter(str(row.get("label_next_action") or "UNKNOWN") for row in source if str(row.get("label_next_action") or "") not in IDLE)
        distribution[venue] = dict(sorted(counts.items()))
        if not train_events or not test_events:
            results.append({"venue": venue, "status": "INSUFFICIENT_EVENT_COVERAGE", "train_event_rows": len(train_events), "test_event_rows": len(test_events), "promotion_allowed": False})
            continue
        model = _fit_event_model(train_events)
        predictions = _predict(model, test_events)
        behavior = _behavior_metrics(test_events, predictions)
        timing_result = timing.get(venue, {})
        timing_metrics = timing_result.get("timing_metrics", {})
        conditional_f1 = behavior.get("action_macro_f1")
        autonomous_f1 = timing_metrics.get("f1")
        gap = float(conditional_f1) - float(autonomous_f1) if conditional_f1 is not None and autonomous_f1 is not None else None
        result = {
            "venue": venue,
            "status": "DIAGNOSTIC_ONLY",
            "candidate_model_version": VERSION,
            "train_event_rows": len(train_events),
            "test_event_rows": len(test_events),
            "conditional_event_type": {
                **behavior,
                "benchmark": "oracle_non_idle_event_given; historical teacher state fields intentionally available",
                "teacher_state_fields_consumed": [
                    "feature_current_normalized_exposure",
                    "feature_cycle_duration_seconds",
                    "feature_latest_action",
                    "feature_action_lag_1/2/3",
                    "feature_recent_*",
                    "feature_realised_*",
                    "feature_fee_accumulation_raw",
                    "feature_funding_accumulation_raw",
                ],
            },
            "strict_autonomous_timing_reference": timing_metrics,
            "conditional_minus_autonomous_timing_f1": gap,
            "active_model_unchanged": True,
            "promotion_allowed": False,
        }
        results.append(result)
        per_venue.append({
            "venue": venue,
            "train_event_rows": len(train_events),
            "test_event_rows": len(test_events),
            "conditional_action_macro_f1": conditional_f1,
            "conditional_target_exposure_mae": behavior.get("target_exposure_mae"),
            "autonomous_timing_f1": autonomous_f1,
            "conditional_minus_autonomous_timing_f1": gap,
            "status": "DIAGNOSTIC_ONLY",
        })
    output = {
        "report_version": "M15-IDENTIFIABILITY-CEILING-1.0",
        "status": "DIAGNOSTIC_ONLY",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "candidate_model_version": VERSION,
        "dataset": str(dataset_path.relative_to(ROOT)),
        "dataset_rows": len(rows),
        "label_distribution_non_idle": distribution,
        "benchmark_definition": "Train on non-idle historical events and evaluate only on non-idle events in the final untouched chronological slice; the event occurrence is an oracle and historical dynamic state is intentionally available.",
        "timing_reference": str(TIMING_REPORT.relative_to(ROOT)) if TIMING_REPORT.exists() else None,
        "venue_results": results,
        "raw_inputs_untouched": True,
        "active_demo_unchanged": True,
        "promotion_allowed": False,
        "conclusion": "The conditional benchmark measures action-type information after removing the timing problem. Its score is not an autonomous signal and cannot prove exact strategy recovery; the gap to strict autonomous timing is the public-record identifiability shortfall.",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    with per_venue_path.open("w", encoding="utf-8", newline="") as handle:
        fields = list(per_venue[0].keys()) if per_venue else ["status"]
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(per_venue)
    lines = [
        "# Public-Record Identifiability Ceiling Audit",
        "",
        "> The conditional benchmark is an oracle-timing diagnostic, not a deployable strategy. It is compared with v4.3 strict autonomous timing on a separate final chronological slice.",
        "",
        "| venue | train event rows | untouched event rows | conditional action F1 | autonomous timing F1 | gap |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        conditional = result.get("conditional_event_type", {})
        timing_metrics = result.get("strict_autonomous_timing_reference", {})
        fmt = lambda value: "—" if value is None else f"{float(value):.6f}"
        lines.append(f"| `{result['venue']}` | {result.get('train_event_rows', 0)} | {result.get('test_event_rows', 0)} | {fmt(conditional.get('action_macro_f1'))} | {fmt(timing_metrics.get('f1'))} | {fmt(result.get('conditional_minus_autonomous_timing_f1'))} |")
    lines += [
        "",
        "## Interpretation",
        "",
        "A large conditional/autonomous gap means the public record contains information about the type or size of an action once an event is known, but does not identify when the action should be initiated. This is a direct limitation on autonomous imitation, not evidence that the original trader used a particular indicator.",
        "",
        "## Boundary",
        "",
        "No credentials, private endpoint, mainnet connection, or order was used. Historical state is explicitly allowed only in this conditional diagnostic; it is forbidden in the strict autonomous path. The active Demo model remains unchanged.",
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
        print(json.dumps({"status": "BLOCKED", "error_code": "IDENTIFIABILITY_AUDIT_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": result["status"], "report": str(REPORT), "venues": [item["venue"] for item in result["venue_results"]]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
