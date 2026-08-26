#!/usr/bin/env python3
"""Audit a causal, venue-neutral action-timing head.

The sparse hourly labels make a single action classifier prone to predicting
NO_TRADE forever.  This diagnostic separates the binary timing decision from
the action-family and target heads, calibrates the timing threshold on a
middle chronological slice, and evaluates only on the final untouched slice.
It never changes the active Demo model.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from bisect import bisect_right
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
for path in (ROOT, SRC, ROOT / "quant" / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from audit_cross_venue_probability_calibrated_stability import (  # noqa: E402
    DATASET_TEMPORAL,
    FEE_RATE,
    _behavior_metrics,
    _load_bars,
    _read_temporal,
    _replay_portfolio,
)
from audit_shared_intent_native_layer import (  # noqa: E402
    _causal_check,
    _number,
    chronological_three_way,
    neutralize_for_shared_intent,
)
from quant_bot.strategy.supervised_models import TwoStageCrossAssetStrategy  # noqa: E402
from research.autonomous_replay import (  # noqa: E402
    AutonomousState,
    merge_same_time_signals,
    normalize_window_rows,
    override_dynamic_state,
    parse_time,
    roll_forward_predictions,
    state_key,
)


VERSION = "behavioral-distillation-v4.3-shared-intent-timing"
REPORT = ROOT / "quant" / "reports" / "shared_intent_timing_audit.json"
REPORT_MD = ROOT / "quant" / "reports" / "shared_intent_timing_audit.md"
PER_SYMBOL = ROOT / "quant" / "reports" / "shared_intent_timing_by_symbol.csv"
IDLE_ACTIONS = TwoStageCrossAssetStrategy.IDLE_ACTIONS


def _eligible(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        neutralize_for_shared_intent(row)
        for row in rows
        if str(row.get("model_eligible")).lower() == "true"
        and str(row.get("label_status")) == "AVAILABLE"
        and row.get("label_next_action")
    ]


def timing_metrics(rows: Iterable[Mapping[str, Any]], predictions: Iterable[tuple[Mapping[str, Any], Any]]) -> dict[str, Any]:
    """Measure the binary ACTION/NO_TRADE head independently of action type."""

    by_id = {str(row.get("decision_episode_id")): signal for row, signal in predictions}
    actual: list[bool] = []
    guessed: list[bool] = []
    for row in rows:
        signal = by_id.get(str(row.get("decision_episode_id")))
        if signal is None:
            continue
        actual.append(str(row.get("label_next_action") or "NO_TRADE") not in IDLE_ACTIONS)
        guessed.append(str(signal.action) not in IDLE_ACTIONS)
    tp = sum(a and g for a, g in zip(actual, guessed))
    fp = sum((not a) and g for a, g in zip(actual, guessed))
    fn = sum(a and (not g) for a, g in zip(actual, guessed))
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2.0 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "rows": len(actual),
        "true_action_rows": sum(actual),
        "predicted_action_rows": sum(guessed),
        "observed_action_rate": sum(actual) / len(actual) if actual else 0.0,
        "predicted_action_rate": sum(guessed) / len(guessed) if guessed else 0.0,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "all_no_trade_baseline_f1": 0.0 if any(actual) else 1.0,
        "all_no_trade_baseline_accuracy": (sum(not item for item in actual) / len(actual)) if actual else 0.0,
    }


def _fit_shared(train_rows: list[dict[str, Any]]) -> TwoStageCrossAssetStrategy:
    train = [dict(row, dataset_split="TRAIN") for row in train_rows if row.get("label_next_action")]
    if not train:
        raise ValueError("shared timing model requires labeled training rows")
    model = TwoStageCrossAssetStrategy(target_l2=1.0)
    model.fit(train)
    model.version = VERSION
    model.timing_model.version = f"{VERSION}:timing"
    model.action_model.version = f"{VERSION}:action"
    return model


def _select_threshold(
    model: TwoStageCrossAssetStrategy,
    calibration_rows: list[dict[str, Any]],
    scales: Mapping[str, float],
    opens: Mapping[str, list[Any]],
) -> tuple[float, dict[str, Any]]:
    """Select timing threshold using only the middle chronological slice."""

    candidates: list[dict[str, Any]] = []
    observed_rate = sum(str(row.get("label_next_action") or "NO_TRADE") not in IDLE_ACTIONS for row in calibration_rows) / len(calibration_rows) if calibration_rows else 0.0
    # Generate the autonomous state trajectory once at threshold zero.  The
    # threshold grid is evaluated against those causal timing probabilities;
    # the final selected threshold is then replayed once on the untouched
    # test slice.  This avoids repeated full replays over tens of thousands of
    # rows while keeping selection strictly inside the calibration slice.
    raw = _autonomous_timing_probabilities(model, calibration_rows, scales, opens)
    for index in range(0, 21):
        threshold = round(index / 20.0, 2)
        predictions: list[tuple[dict[str, Any], Any]] = []
        for row, signal, probability in raw:
            if probability < threshold:
                signal = replace(signal, action="NO_TRADE", risk_tags=tuple(dict.fromkeys((*signal.risk_tags, "ACTION_PROBABILITY_BELOW_THRESHOLD"))))
            predictions.append((row, signal))
        metrics = timing_metrics(calibration_rows, predictions)
        score = float(metrics["f1"]) - 0.25 * abs(float(metrics["predicted_action_rate"]) - observed_rate)
        candidates.append({"threshold": threshold, "score": score, **metrics})
    selected = max(candidates, key=lambda row: (float(row["score"]), float(row["f1"]), -abs(float(row["predicted_action_rate"]) - observed_rate), -float(row["threshold"])))
    return float(selected["threshold"]), {
        "selection_rows": len(calibration_rows),
        "observed_action_rate": observed_rate,
        "selection_contract": "middle chronological calibration only; binary timing F1 minus action-rate mismatch",
        "selected": selected,
        "candidates": candidates,
    }


def _autonomous_timing_probabilities(
    model: TwoStageCrossAssetStrategy,
    rows: Iterable[Mapping[str, Any]],
    scales: Mapping[str, float],
    opens: Mapping[str, list[Any]],
) -> list[tuple[dict[str, Any], Any, float]]:
    """Collect causal timing probabilities along one zero-threshold path."""

    ordered = sorted(
        (dict(row) for row in rows),
        key=lambda row: (
            parse_time(row.get("decision_time")) or datetime.max.replace(tzinfo=timezone.utc),
            state_key(row),
            str(row.get("decision_episode_id")),
        ),
    )
    states: dict[str, AutonomousState] = defaultdict(AutonomousState)
    pending: dict[str, list[tuple[datetime, float, str]]] = defaultdict(list)
    grouped: defaultdict[tuple[str, datetime], list[dict[str, Any]]] = defaultdict(list)
    for row in ordered:
        when = parse_time(row.get("decision_time"))
        if when is not None:
            grouped[(state_key(row), when)].append(row)
    output: list[tuple[dict[str, Any], Any, float]] = []
    original_threshold = model.timing_threshold
    model.timing_threshold = 0.0
    try:
        for (key, when), group in grouped.items():
            state = states[key]
            while pending[key] and pending[key][0][0] <= when:
                execution_time, target, action = pending[key].pop(0)
                state.apply_execution(target, action, execution_time)
            scale = max(1.0, _number(scales.get(key), _number(group[0].get("feature_position_scale_contracts"), 1.0)) or 1.0)
            local: list[tuple[dict[str, Any], Any]] = []
            for row in group:
                overridden = override_dynamic_state(row, state, scale, when)
                strategy_input = _strategy_input(overridden)
                probability = float(model.action_probability(strategy_input))
                signal = model.predict(strategy_input)
                local.append((row, signal))
                output.append((row, signal, probability))
            merged = merge_same_time_signals(local, key=key, decision_time=when)
            if merged is None:
                continue
            bar_opens = opens.get(key, [])
            index = bisect_right(bar_opens, when)
            execution_time = bar_opens[index] if index < len(bar_opens) else when + timedelta(hours=1)
            pending[key].append((execution_time, float(merged["target_exposure"]), str(merged["action"])))
    finally:
        model.timing_threshold = original_threshold
    return output


def _strategy_input(row: Mapping[str, Any]):
    # Imported lazily to keep this module's public helper tests lightweight.
    from quant_bot.strategy.feature_contract import strategy_input_from_row

    return strategy_input_from_row(row)


def _symbol_rows(rows: list[dict[str, Any]], predictions: list[tuple[dict[str, Any], Any]], window: str) -> list[dict[str, Any]]:
    predicted = {str(row.get("decision_episode_id")): signal for row, signal in predictions}
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        key = f"{row.get('source_venue') or ''}:{row.get('canonical_asset') or ''}"
        grouped[key].append(row)
    output: list[dict[str, Any]] = []
    for key, subset in sorted(grouped.items()):
        subset_predictions = [(row, predicted[str(row.get("decision_episode_id"))]) for row in subset if str(row.get("decision_episode_id")) in predicted]
        metrics = timing_metrics(subset, subset_predictions)
        output.append({
            "window": window,
            "state_key": key,
            "source_venue": str(subset[0].get("source_venue") or ""),
            "canonical_asset": str(subset[0].get("canonical_asset") or ""),
            "rows": len(subset),
            "observed_action_rate": metrics["observed_action_rate"],
            "predicted_action_rate": metrics["predicted_action_rate"],
            "timing_f1": metrics["f1"],
            "timing_precision": metrics["precision"],
            "timing_recall": metrics["recall"],
            "status": "STABLE_SAMPLE" if len(subset) >= 100 else "LOW_SAMPLE",
        })
    return output


def build(*, dataset_path: Path = DATASET_TEMPORAL, report_path: Path = REPORT, markdown_path: Path = REPORT_MD, per_symbol_path: Path = PER_SYMBOL) -> dict[str, Any]:
    raw_rows = _read_temporal(dataset_path)
    causal = _causal_check(raw_rows)
    bars, opens = _load_bars()
    by_venue: dict[str, dict[str, Any]] = {}
    shared_train: list[dict[str, Any]] = []
    shared_calibration: list[dict[str, Any]] = []
    for venue in sorted({str(row.get("source_venue") or "UNKNOWN") for row in raw_rows}):
        source = [row for row in raw_rows if str(row.get("source_venue") or "UNKNOWN") == venue]
        train_raw, calibration_raw, test_raw = chronological_three_way(source)
        train, scales = normalize_window_rows(train_raw, train_raw)
        calibration, _ = normalize_window_rows(calibration_raw, train_raw)
        test, _ = normalize_window_rows(test_raw, train_raw)
        parts = {
            "train": _eligible(train),
            "calibration": _eligible(calibration),
            "test": _eligible(test),
            "scales": scales,
            "train_boundary": train_raw[-1].get("decision_time") if train_raw else None,
            "calibration_boundary": calibration_raw[-1].get("decision_time") if calibration_raw else None,
            "test_first_time": test_raw[0].get("decision_time") if test_raw else None,
            "test_last_time": test_raw[-1].get("decision_time") if test_raw else None,
            "raw_rows": len(source),
        }
        by_venue[venue] = parts
        shared_train.extend(parts["train"])
        shared_calibration.extend(parts["calibration"])
    model = _fit_shared(shared_train)
    if shared_calibration:
        calibration = model.calibrate_action_probability(shared_calibration)
    else:
        calibration = {"calibration_rows": 0}
    results: list[dict[str, Any]] = []
    per_symbol: list[dict[str, Any]] = []
    for venue, parts in by_venue.items():
        calibration_rows = parts["calibration"]
        test_rows = parts["test"]
        if not calibration_rows or not test_rows:
            results.append({"venue": venue, "status": "INSUFFICIENT_NATIVE_COVERAGE", "promotion_allowed": False, **{key: value for key, value in parts.items() if key != "scales"}})
            continue
        model.timing_threshold = 0.5
        threshold, selection = _select_threshold(model, calibration_rows, parts["scales"], opens)
        model.timing_threshold = threshold
        autonomous = roll_forward_predictions(model, test_rows, parts["scales"], market_bar_opens=opens, include_state_overrides=False)
        first = _parse_time(test_rows[0].get("decision_time"))
        last = _parse_time(test_rows[-1].get("decision_time"))
        if first is None or last is None:
            raise ValueError(f"invalid test time for {venue}")
        replay = _replay_portfolio(autonomous["merged_events"], bars, start=first, end=last + timedelta(hours=1), fee_rate=FEE_RATE)
        timing = timing_metrics(test_rows, autonomous["row_predictions"])
        action_behavior = _behavior_metrics(test_rows, autonomous["row_predictions"])
        results.append({
            "venue": venue,
            "status": "DIAGNOSTIC_ONLY",
            "candidate_model_version": VERSION,
            "active_model_unchanged": True,
            "promotion_allowed": False,
            "raw_rows": parts["raw_rows"],
            "train_rows": len(parts["train"]),
            "calibration_rows": len(calibration_rows),
            "test_rows": len(test_rows),
            "train_boundary": parts["train_boundary"],
            "calibration_boundary": parts["calibration_boundary"],
            "test_first_time": parts["test_first_time"],
            "test_last_time": parts["test_last_time"],
            "threshold_selection": selection,
            "timing_metrics": timing,
            "action_family_metrics": action_behavior,
            "performance": {key: value for key, value in replay.items() if key != "per_symbol"},
        })
        per_symbol.extend(_symbol_rows(test_rows, autonomous["row_predictions"], f"TIMING_{venue}"))
    output = {
        "report_version": "M15-SHARED-INTENT-TIMING-1.0",
        "status": "DIAGNOSTIC_ONLY",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "candidate_model_version": VERSION,
        "dataset": str(dataset_path.relative_to(ROOT)),
        "dataset_rows": len(raw_rows),
        "shared_train_rows": len(shared_train),
        "shared_calibration_rows": len(shared_calibration),
        "split_contract": "per venue chronological 60% train / 20% calibration / 20% untouched test",
        "input_contract": "venue-neutral categories and contract units; normalized state plus common market/indicator fields; no funding or mark/index basis",
        "causal_audit": causal,
        "probability_calibration": calibration,
        "venue_results": results,
        "active_demo_unchanged": True,
        "raw_inputs_untouched": True,
        "promotion_allowed": False,
        "conclusion": "The timing head is a diagnostic candidate. It is not a deployable strategy unless it produces stable autonomous actions and costed results on untouched windows.",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    _write_csv(per_symbol_path, per_symbol)
    lines = [
        "# Shared Intent Timing Audit",
        "",
        "> Diagnostic only. A venue-neutral timing head is fitted on 60%, calibrated on 20%, and evaluated on an untouched final 20% per venue.",
        "",
        "| venue | train | calibration | untouched test | selected threshold | timing F1 | predicted action rate | net return |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        metrics = result.get("timing_metrics", {})
        performance = result.get("performance", {})
        selected = result.get("threshold_selection", {}).get("selected", {})
        threshold = selected.get("threshold")
        fmt = lambda value: "—" if value is None else f"{float(value):.6f}"
        lines.append(f"| `{result['venue']}` | {result.get('train_rows', 0)} | {result.get('calibration_rows', 0)} | {result.get('test_rows', 0)} | {fmt(threshold)} | {fmt(metrics.get('f1'))} | {float(metrics.get('predicted_action_rate', 0.0)):.2%} | {fmt(performance.get('net_return'))} |")
    lines += [
        "",
        "## Interpretation",
        "",
        "The timing head is judged separately from action type. High F1 without stable costed autonomous execution is insufficient; an all-NO_TRADE classifier is explicitly treated as a failed action-timing candidate when the holdout contains actions.",
        "",
        "## Boundary",
        "",
        "No credentials, private endpoint, mainnet connection, or order was used. The active Demo model remains unchanged and raw CSV/JSON inputs remain read-only.",
    ]
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def _parse_time(value: Any):
    from research.autonomous_replay import parse_time

    return parse_time(value)


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_TEMPORAL)
    args = parser.parse_args()
    try:
        result = build(dataset_path=args.dataset.resolve())
    except (FileNotFoundError, OSError, ValueError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "SHARED_INTENT_TIMING_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": result["status"], "report": str(REPORT), "venues": [item["venue"] for item in result["venue_results"]]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
