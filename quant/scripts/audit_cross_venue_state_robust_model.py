#!/usr/bin/env python3
"""Audit a state-robust two-stage behavioral model.

This is an independent research candidate.  It addresses the distribution
shift between teacher-state rows and a zero-start autonomous replay by
augmenting *training rows only*.  For observed non-idle actions, deterministic
zero/intermediate state variants retain the same future target and receive a
causally recomputed action label.  No test row, future observation, or active
Demo artifact is changed.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
for path in (ROOT, SRC, ROOT / "quant" / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from audit_cross_venue_probability_calibrated_stability import (  # noqa: E402
    DATASET_TEMPORAL,
    FEE_RATE,
    WINDOWS,
    _behavior_metrics,
    _causal_audit,
    _load_bars,
    _number,
    _per_symbol_rows,
    _rates,
    _replay_portfolio,
    _stability_summary,
    _venue_coverage,
    _window_rows,
    _read_temporal,
    _split_training_rows,
)
from audit_cross_venue_two_stage_model import _predictions  # noqa: E402
from quant_bot.strategy.feature_contract import strategy_input_from_row  # noqa: E402
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


VERSION = "behavioral-distillation-v3.9-state-robust-autonomous-threshold"
REPORT = ROOT / "quant" / "reports" / "cross_venue_state_robust_autonomous_threshold_audit.json"
REPORT_MD = ROOT / "quant" / "reports" / "cross_venue_state_robust_autonomous_threshold_audit.md"
PER_SYMBOL = ROOT / "quant" / "reports" / "cross_venue_state_robust_autonomous_threshold_by_symbol.csv"
UTC = timezone.utc


def _transition_action(before: float, after: float) -> str:
    """Classify the synthetic state transition without looking ahead."""

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
    if before > 0:
        return "REDUCE_LONG"
    return "REDUCE_SHORT"


def _synthetic_state_row(row: Mapping[str, Any], current: float, *, variant: str) -> dict[str, Any]:
    """Reset teacher-dynamic state while keeping exogenous features intact."""

    output = dict(row)
    scale = max(1.0, _number(row.get("feature_position_scale_contracts"), 1.0) or 1.0)
    target = _number(row.get("label_next_target_exposure"), 0.0) or 0.0
    output.update({
        "feature_current_net_position_contracts": current * scale,
        "feature_current_normalized_exposure": current,
        "feature_cycle_duration_seconds": None,
        "feature_latest_action": "",
        "feature_recent_add_count_24h": 0.0,
        "feature_recent_reduce_count_24h": 0.0,
        "feature_recent_flip_count_24h": 0.0,
        "feature_recent_realised_outcome": 0.0,
        "feature_realised_drawdown": 0.0,
        "feature_fee_accumulation_raw": 0.0,
        "feature_funding_accumulation_raw": 0.0,
        "feature_order_execution_style": "AUTONOMOUS_LIMIT_POST_ONLY",
        "feature_ordering_confidence": "HIGH",
        "feature_accounting_confidence": "HIGH",
        "feature_history_last_decision_time": "",
        "label_next_action": _transition_action(current, target),
        "state_augmentation": variant,
    })
    return output


def _augment_training_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Add deterministic state variants for non-idle training actions only."""

    output = [dict(row, state_augmentation="ORIGINAL") for row in rows]
    idle = TwoStageCrossAssetStrategy.IDLE_ACTIONS
    for row in rows:
        original_action = str(row.get("label_next_action") or "")
        if original_action in idle:
            continue
        current = _number(row.get("feature_current_normalized_exposure"), 0.0) or 0.0
        target = _number(row.get("label_next_target_exposure"), 0.0) or 0.0
        candidates = (0.0, current * 0.5)
        for index, synthetic_current in enumerate(candidates):
            if abs(synthetic_current - current) <= 1e-12:
                continue
            variant = "ZERO_START" if index == 0 else "HALF_TEACHER_STATE"
            synthetic = _synthetic_state_row(row, synthetic_current, variant=variant)
            if str(synthetic["label_next_action"]) in idle:
                # A close-to-zero teacher action cannot be an action when the
                # autonomous state is already zero; do not invent a timing
                # label just to balance the classes.
                continue
            synthetic["label_next_target_exposure"] = target
            output.append(synthetic)
    return output


def _autonomous_probability_rows(
    model: TwoStageCrossAssetStrategy,
    rows: list[dict[str, Any]],
    scales: Mapping[str, float],
) -> list[tuple[dict[str, Any], Any, float, float]]:
    """Collect timing probabilities using the same zero-start state as replay."""

    ordered = sorted(
        rows,
        key=lambda row: (
            parse_time(row.get("decision_time")) or datetime.max.replace(tzinfo=UTC),
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
    output: list[tuple[dict[str, Any], Any, float, float]] = []
    original_threshold = model.timing_threshold
    model.timing_threshold = 0.0
    try:
        for (key, when), group in grouped.items():
            state = states[key]
            while pending[key] and pending[key][0][0] <= when:
                execution_time, target, action = pending[key].pop(0)
                state.apply_execution(target, action, execution_time)
            scale = max(1.0, float(scales.get(key, _number(group[0].get("feature_position_scale_contracts"), 1.0) or 1.0)))
            local: list[tuple[dict[str, Any], Any]] = []
            for row in group:
                overridden = override_dynamic_state(row, state, scale, when)
                strategy_input = strategy_input_from_row(overridden)
                probability = model.action_probability(strategy_input)
                signal = model.predict(strategy_input)
                local.append((row, signal))
                output.append((row, signal, probability, float(strategy_input.current_strategy_position)))
            merged = merge_same_time_signals(local, key=key, decision_time=when)
            if merged is not None:
                pending[key].append((when + timedelta(hours=1), float(merged["target_exposure"]), str(merged["action"])))
    finally:
        model.timing_threshold = original_threshold
    return output


def _select_threshold_autonomous(
    model: TwoStageCrossAssetStrategy,
    rows: list[dict[str, Any]],
    scales: Mapping[str, float],
) -> tuple[float, dict[str, Any]]:
    """Select a timing threshold from train-only autonomous-state rows."""

    if not rows:
        return 0.5, {"selection_rows": 0, "selected": {"threshold": 0.5}}
    observed_rate = sum(str(row.get("label_next_action") or "") not in model.IDLE_ACTIONS for row in rows) / len(rows)
    raw = _autonomous_probability_rows(model, rows, scales)
    candidates: list[dict[str, Any]] = []
    for threshold in [round(index / 100, 2) for index in range(0, 101)]:
        predictions: list[tuple[dict[str, Any], Any]] = []
        turnover = 0.0
        for row, signal, probability, current in raw:
            if probability < threshold:
                idle_action = "HOLD_LONG" if current > 0 else "HOLD_SHORT" if current < 0 else "NO_TRADE"
                signal = replace(
                    signal,
                    action=idle_action,
                    target_exposure=current,
                    confidence=max(0.0, min(1.0, 1.0 - probability)),
                    risk_tags=tuple(dict.fromkeys((*signal.risk_tags, "ACTION_PROBABILITY_BELOW_THRESHOLD"))),
                )
            else:
                turnover += abs(float(signal.target_exposure) - current)
            predictions.append((row, signal))
        metrics = _behavior_metrics(rows, predictions)
        predicted_rate = sum(signal.action not in model.IDLE_ACTIONS for _, signal in predictions) / len(predictions) if predictions else 0.0
        turnover_proxy = turnover / len(predictions) if predictions else 0.0
        score = float(metrics.get("action_macro_f1") or 0.0) - 0.25 * abs(predicted_rate - observed_rate) - 10.0 * FEE_RATE * turnover_proxy
        candidates.append({
            "threshold": threshold,
            "score": score,
            "action_macro_f1": metrics.get("action_macro_f1"),
            "target_exposure_mae": metrics.get("target_exposure_mae"),
            "observed_action_rate": observed_rate,
            "predicted_action_rate": predicted_rate,
            "turnover_proxy": turnover_proxy,
        })
    selected = max(candidates, key=lambda item: (float(item["score"]), float(item.get("action_macro_f1") or 0.0), -float(item["turnover_proxy"]), -float(item["threshold"])))
    return float(selected["threshold"]), {
        "selection_rows": len(rows),
        "selection_contract": "train-only chronological threshold selection using autonomous zero-start state probabilities; action Macro-F1 minus action-rate mismatch and fee turnover proxy",
        "selected": selected,
        "candidates": candidates,
    }


def _fit_candidate(train_rows: list[dict[str, Any]], scales: Mapping[str, float]) -> tuple[TwoStageCrossAssetStrategy, dict[str, Any]]:
    fit_rows, calibration_rows, threshold_rows = _split_training_rows(train_rows)
    if not fit_rows or not calibration_rows or not threshold_rows:
        raise ValueError("state-robust nested split requires fit, calibration, and threshold rows")
    augmented_fit = _augment_training_rows(fit_rows)
    model = TwoStageCrossAssetStrategy(target_l2=1.0)
    model.fit(augmented_fit)
    calibration = model.calibrate_action_probability(calibration_rows)
    threshold, selection = _select_threshold_autonomous(model, threshold_rows, scales)
    model.timing_threshold = threshold
    model.version = VERSION
    model.timing_model.version = f"{VERSION}:timing"
    model.action_model.version = f"{VERSION}:action"
    return model, {
        "fit_rows_original": len(fit_rows),
        "fit_rows_augmented": len(augmented_fit),
        "synthetic_rows_added": len(augmented_fit) - len(fit_rows),
        "calibration_rows": len(calibration_rows),
        "threshold_rows": len(threshold_rows),
        "probability_calibration": calibration,
        "threshold_selection": selection,
    }


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


def build(*, dataset_path: Path = DATASET_TEMPORAL, report_path: Path = REPORT, report_md_path: Path = REPORT_MD, per_symbol_path: Path = PER_SYMBOL) -> dict[str, Any]:
    rows = _read_temporal(dataset_path)
    causal = _causal_audit(rows)
    bars, opens = _load_bars()
    behavior: list[dict[str, Any]] = []
    performance: list[dict[str, Any]] = []
    per_symbol: list[dict[str, Any]] = []
    windows: list[dict[str, Any]] = []
    model_test_counts: defaultdict[str, dict[str, int]] = defaultdict(dict)
    for window in WINDOWS:
        train_raw = _window_rows(rows, None, window.train_end)
        test_raw = _window_rows(rows, window.test_start, window.test_end)
        train, scales = normalize_window_rows(train_raw, train_raw)
        test, _ = normalize_window_rows(test_raw, train_raw)
        train = [row for row in train if str(row.get("model_eligible")).lower() == "true"]
        test = [row for row in test if str(row.get("model_eligible")).lower() == "true"]
        for venue in sorted({str(row.get("source_venue") or "UNKNOWN") for row in rows}):
            model_test_counts[venue][window.name] = sum(str(row.get("source_venue") or "UNKNOWN") == venue for row in test)
        if not train or not test:
            windows.append({"window": window.name, "status": "NO_DATA", "train_rows": len(train), "test_rows": len(test)})
            continue
        model, stages = _fit_candidate(train, scales)
        conditional = _predictions(model, test)
        autonomous = roll_forward_predictions(model, test, scales, market_bar_opens=opens, include_state_overrides=False)
        auto_metrics = _behavior_metrics(test, autonomous["row_predictions"])
        replay = _replay_portfolio(autonomous["merged_events"], bars, start=window.test_start, end=window.test_end, fee_rate=FEE_RATE)
        per_symbol.extend(_per_symbol_rows(test, autonomous["row_predictions"], replay, window.name))
        behavior.extend([
            {"window": window.name, "model": "V3.9", "track": "CONDITIONAL_BEHAVIOR", **_behavior_metrics(test, conditional), **_rates(test, conditional)},
            {"window": window.name, "model": "V3.9", "track": "STRICT_AUTONOMOUS", **auto_metrics, **_rates(test, autonomous["row_predictions"]), "teacher_state_fields_consumed": autonomous["teacher_state_fields_consumed"]},
        ])
        performance.append({
            "window": window.name,
            "model": "V3.9",
            "track": "STRICT_AUTONOMOUS",
            "cost_profile": "BASE",
            "target_coefficient_max_abs": max(abs(float(value)) for value in model.action_model.target_coef) if model.action_model.target_coef is not None else None,
            **{key: value for key, value in replay.items() if key != "per_symbol"},
        })
        windows.append({
            "window": window.name,
            "status": "TEST_DATA_AVAILABLE",
            "train_rows": len(train),
            "test_rows": len(test),
            "nested_stages": stages,
            "per_symbol_stability": _stability_summary(per_symbol, window.name),
        })
        del model, conditional, autonomous, train, test

    venue_coverage = _venue_coverage(rows)
    for venue, summary in venue_coverage.items():
        summary["global_model_test_rows"] = {window.name: model_test_counts.get(venue, {}).get(window.name, 0) for window in WINDOWS}
    performance_rows = [row for row in performance if row.get("model") == "V3.9"]
    gates = {
        "causal_audit_pass": causal.get("status") == "PASS",
        "all_walk_forward_windows_available": len(performance_rows) == len(WINDOWS),
        "target_coefficients_finite_and_bounded": all(row.get("target_coefficient_max_abs") is not None and float(row["target_coefficient_max_abs"]) < 100.0 for row in performance_rows),
        "global_cross_venue_test_coverage": all(sum(int(value or 0) for value in summary.get("global_model_test_rows", {}).values()) > 0 for summary in venue_coverage.values()),
        "strict_autonomous_positive_all_windows": all(row.get("net_return") is not None and float(row["net_return"]) > 0 for row in performance_rows),
        "strict_autonomous_profit_factor_gt_one_all_windows": all(row.get("profit_factor") is not None and float(row["profit_factor"]) > 1 for row in performance_rows),
        "per_symbol_results_complete": all(window.get("per_symbol_stability", {}).get("stable_symbol_count", 0) > 0 for window in windows if window.get("status") == "TEST_DATA_AVAILABLE"),
    }
    result = {
        "report_version": "M15-STATE-ROBUST-AUTONOMOUS-THRESHOLD-AUDIT-1.0",
        "status": "DEMO_CONTINUE_LIVE_BLOCKED" if not all(gates.values()) else "CANDIDATE_REVIEW_REQUIRED",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "active_model_unchanged": True,
        "candidate_model_version": VERSION,
        "dataset": str(dataset_path.relative_to(ROOT)),
        "dataset_rows": len(rows),
        "causal_audit": causal,
        "augmentation_contract": "Training-only non-idle rows receive deterministic ZERO_START and HALF_TEACHER_STATE variants; test rows are untouched; synthetic targets use the original next target and actions are recomputed from the synthetic current state. Threshold selection also uses autonomous zero-start state probabilities from a training-only chronological segment.",
        "windows": windows,
        "behavior_results": behavior,
        "performance_results": performance,
        "per_symbol_results": per_symbol,
        "venue_coverage": venue_coverage,
        "gates": gates,
        "conclusion": "The state-robust candidate remains research-only until causal, cross-venue coverage, stable costed autonomous performance, and per-symbol gates all pass.",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    _write_csv(per_symbol_path, per_symbol)
    lines = [
        "# Cross-Venue State-Robust Autonomous-Threshold Audit",
        "",
        f"- status: **{result['status']}**",
        f"- candidate: `{VERSION}`",
        "- active Demo model changed: **no**",
        "",
        "## Training contract",
        "",
        "Only the chronological training fit segment receives deterministic zero-start and half-teacher-state variants for observed non-idle actions. Calibration, threshold selection, and every walk-forward test row remain untouched.",
        "",
        "## Venue coverage",
        "",
    ]
    for venue, summary in venue_coverage.items():
        counts = ", ".join(f"{name}={count}" for name, count in summary["global_model_test_rows"].items())
        lines.append(f"- `{venue}`: `{summary['rows']}` rows; model-eligible global test rows `{counts}`.")
    lines += [
        "",
        "## Strict autonomous costed replay",
        "",
        "| window | net return | profit factor | target MAE | observed action rate | predicted action rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    behavior_by_window = {(row["window"], row["track"]): row for row in behavior}
    performance_by_window = {row["window"]: row for row in performance_rows}
    for window in WINDOWS:
        item = performance_by_window.get(window.name, {})
        metrics = behavior_by_window.get((window.name, "STRICT_AUTONOMOUS"), {})
        observed_action = 1.0 - float(metrics.get("observed_no_trade_rate", 1.0))
        predicted_action = 1.0 - float(metrics.get("predicted_no_trade_rate", 1.0))
        fmt = lambda value: "—" if value is None else f"{float(value):.6f}"
        lines.append(f"| {window.name} | {fmt(item.get('net_return'))} | {fmt(item.get('profit_factor'))} | {fmt(metrics.get('target_exposure_mae'))} | {observed_action:.2%} | {predicted_action:.2%} |")
    lines += [
        "",
        "## Gates",
        "",
        *[f"- `{key}`: **{'PASS' if value else 'FAIL'}**" for key, value in gates.items()],
        "",
        "## Boundary",
        "",
        "This is a causal behavioral approximation from public trade records. It does not prove exact strategy recovery, future profitability, or deployability; no credential, private endpoint, mainnet connection, or order was used.",
    ]
    report_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_TEMPORAL)
    args = parser.parse_args()
    try:
        result = build(dataset_path=args.dataset.resolve())
    except (FileNotFoundError, OSError, ValueError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "STATE_ROBUST_AUDIT_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": result["status"], "gates": result["gates"], "report": str(REPORT), "per_symbol": str(PER_SYMBOL)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
