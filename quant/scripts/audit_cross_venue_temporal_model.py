#!/usr/bin/env python3
"""Audit a market-clock candidate without changing the active Demo model."""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from datetime import datetime, timezone
from dataclasses import replace
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
for path in (ROOT, SRC, ROOT / "quant" / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from audit_cross_venue_strategy import (  # noqa: E402
    DATASET_V3,
    FEE_RATE,
    FROZEN_CUTOFF,
    WINDOWS,
    _behavior_metrics,
    _load_bars,
    _read_dataset,
    _replay_portfolio,
    _window_rows,
)
from quant_bot.strategy.supervised_models import CrossAssetNumpyLogisticStrategy  # noqa: E402
from research.autonomous_replay import normalize_window_rows, roll_forward_predictions  # noqa: E402


UTC = timezone.utc
DATASET_TEMPORAL = ROOT / "quant" / "outputs" / "cross_venue_temporal_dataset_v3.csv"
REPORT = ROOT / "quant" / "reports" / "cross_venue_temporal_autonomous_audit.json"
REPORT_MD = ROOT / "quant" / "reports" / "cross_venue_temporal_autonomous_audit.md"
TEMPORAL_VERSION = "behavioral-distillation-v3-cross-venue-temporal-clock"
BALANCED_TEMPORAL_VERSION = "behavioral-distillation-v3-cross-venue-temporal-balanced"
CALIBRATED_TEMPORAL_VERSION = "behavioral-distillation-v3.4-calibrated-action-target"
THRESHOLD_TEMPORAL_VERSION = "behavioral-distillation-v3.5-cost-calibrated-threshold"
EVENT_BASELINE_VERSION = "behavioral-distillation-v3.2-event-supervision-baseline"


def _parse_time(value: Any) -> datetime | None:
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


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _read_temporal(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)
    rows = [row for row in _read_dataset(path)]
    rows.sort(key=lambda row: (str(row.get("decision_time")), str(row.get("source_venue")), str(row.get("canonical_asset")), str(row.get("decision_episode_id"))))
    return rows


def _fit_temporal(rows: list[dict[str, Any]], *, balanced: bool = False, calibrated: bool = False, min_action_confidence: float | None = None) -> CrossAssetNumpyLogisticStrategy:
    train = [dict(row, dataset_split="TRAIN") for row in rows if str(row.get("label_status")) == "AVAILABLE"]
    model = CrossAssetNumpyLogisticStrategy(
        target_l2=1.0,
        class_weighting="sqrt_balanced" if calibrated else ("balanced" if balanced else None),
        enforce_action_target_consistency=calibrated,
        min_action_confidence=min_action_confidence,
    ).fit(train)
    model.version = CALIBRATED_TEMPORAL_VERSION if calibrated else (BALANCED_TEMPORAL_VERSION if balanced else TEMPORAL_VERSION)
    return model


def _threshold_predictions(predictions: list[tuple[dict[str, Any], Any]], threshold: float) -> list[tuple[dict[str, Any], Any]]:
    output = []
    for row, signal in predictions:
        if signal.confidence < threshold and signal.action != "NO_TRADE":
            current = _number(row.get("feature_current_normalized_exposure"), 0.0) or 0.0
            output.append((row, replace(signal, action="NO_TRADE", target_exposure=current)))
        else:
            output.append((row, signal))
    return output


def _select_threshold(model: CrossAssetNumpyLogisticStrategy, calibration_rows: list[dict[str, Any]]) -> tuple[float, dict[str, Any]]:
    """Select an abstention threshold using only a chronological train tail.

    The selection score rewards action macro-F1, penalizes a mismatch to the
    observed no-trade rate, and applies a small turnover/fee proxy.  The
    selected value is then frozen before the out-of-time window is evaluated.
    """

    raw = _conditional_predictions(model, calibration_rows)
    observed_rate = sum(str(row.get("label_next_action")) == "NO_TRADE" for row in calibration_rows) / len(calibration_rows) if calibration_rows else 0.0
    candidates: list[dict[str, Any]] = []
    threshold_grid = [round(0.01 * index, 2) for index in range(51)] + [0.55, 0.65, 0.75, 0.85, 0.95]
    for threshold in threshold_grid:
        predicted = _threshold_predictions(raw, threshold)
        metrics = _behavior_metrics(calibration_rows, predicted)
        turnover_proxy = sum(abs(float(signal.target_exposure) - (_number(row.get("feature_current_normalized_exposure"), 0.0) or 0.0)) for row, signal in predicted if signal.action != "NO_TRADE") / len(predicted) if predicted else 0.0
        predicted_rate = sum(signal.action == "NO_TRADE" for _, signal in predicted) / len(predicted) if predicted else 0.0
        score = float(metrics.get("action_macro_f1") or 0.0) - 0.25 * abs(predicted_rate - observed_rate) - 10.0 * FEE_RATE * turnover_proxy
        candidates.append({
            "threshold": threshold,
            "score": score,
            "action_macro_f1": metrics.get("action_macro_f1"),
            "target_exposure_mae": metrics.get("target_exposure_mae"),
            "observed_no_trade_rate": observed_rate,
            "predicted_no_trade_rate": predicted_rate,
            "turnover_proxy": turnover_proxy,
        })
    selected = max(candidates, key=lambda row: (float(row["score"]), float(row.get("action_macro_f1") or 0.0), -float(row["turnover_proxy"]), -float(row["threshold"]))) if candidates else {"threshold": 0.5, "score": 0.0}
    return float(selected["threshold"]), {"selected": selected, "candidates": candidates, "selection_data_rows": len(calibration_rows), "selection_contract": "train-only chronological tail; macro-F1 minus no-trade-rate mismatch and fee turnover proxy"}


def _fit_event_baseline(rows: list[dict[str, Any]]) -> CrossAssetNumpyLogisticStrategy:
    train = [dict(row, dataset_split="TRAIN") for row in rows if str(row.get("label_status")) == "AVAILABLE"]
    model = CrossAssetNumpyLogisticStrategy(target_l2=1.0).fit(train)
    model.version = EVENT_BASELINE_VERSION
    return model


def _max_target_coefficient(model: CrossAssetNumpyLogisticStrategy) -> float:
    if model.target_coef is None:
        return float("inf")
    return float(max(abs(float(value)) for value in model.target_coef))


def _event_baseline_rows(rows: list[dict[str, Any]], window: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, float]]:
    event_rows = _read_dataset(DATASET_V3)
    event_train_raw = _window_rows(event_rows, None, window.train_end)
    event_test_raw = _window_rows(event_rows, window.test_start, window.test_end)
    event_train, scales = normalize_window_rows(event_train_raw, event_train_raw)
    event_test, _ = normalize_window_rows(event_test_raw, event_train_raw)
    return (
        [row for row in event_train if str(row.get("model_eligible")).lower() == "true"],
        [row for row in event_test if str(row.get("model_eligible")).lower() == "true"],
        scales,
    )


def _rates(rows: list[Mapping[str, Any]], predictions: list[tuple[Mapping[str, Any], Any]]) -> dict[str, float | int]:
    observed = Counter(str(row.get("label_next_action") or "NO_TRADE") for row in rows)
    predicted = Counter(str(signal.action) for _, signal in predictions)
    observed_no_trade = observed.get("NO_TRADE", 0)
    predicted_no_trade = predicted.get("NO_TRADE", 0)
    return {
        "observed_no_trade_rows": observed_no_trade,
        "predicted_no_trade_rows": predicted_no_trade,
        "observed_no_trade_rate": observed_no_trade / len(rows) if rows else 0.0,
        "predicted_no_trade_rate": predicted_no_trade / len(predictions) if predictions else 0.0,
    }


def _causal_audit(rows: list[Mapping[str, Any]]) -> dict[str, Any]:
    checks = Counter()
    previous_by_key: dict[tuple[str, str], datetime] = {}
    for row in rows:
        decision = _parse_time(row.get("decision_time"))
        latest = _parse_time(row.get("feature_latest_bar_time"))
        funding = _parse_time(row.get("feature_funding_source_time"))
        key = (str(row.get("source_venue")), str(row.get("canonical_asset")))
        if decision is None:
            checks["invalid_decision_time"] += 1
            continue
        if latest is not None and latest >= decision:
            checks["future_market_bar"] += 1
        if funding is not None and funding > decision:
            checks["future_funding"] += 1
        if key in previous_by_key and decision <= previous_by_key[key]:
            checks["non_strict_clock_order"] += 1
        previous_by_key[key] = decision
        label_time = _parse_time(row.get("label_next_decision_time"))
        if label_time is None or label_time <= decision:
            checks["non_future_label"] += 1
    values = {
        "invalid_decision_time": checks["invalid_decision_time"],
        "future_market_bar": checks["future_market_bar"],
        "future_funding": checks["future_funding"],
        "non_strict_clock_order": checks["non_strict_clock_order"],
        "non_future_label": checks["non_future_label"],
    }
    return {"status": "PASS" if not any(values.values()) else "BLOCKED", "checks": values}


def build(*, dataset_path: Path = DATASET_TEMPORAL, balanced: bool = False, calibrated: bool = False, threshold_calibrated: bool = False, report_path: Path = REPORT, report_md_path: Path = REPORT_MD) -> dict[str, Any]:
    rows = _read_temporal(dataset_path)
    candidate_version = THRESHOLD_TEMPORAL_VERSION if threshold_calibrated else (CALIBRATED_TEMPORAL_VERSION if calibrated else (BALANCED_TEMPORAL_VERSION if balanced else TEMPORAL_VERSION))
    causal = _causal_audit(rows)
    bars, opens = _load_bars()
    behavior: list[dict[str, Any]] = []
    performance: list[dict[str, Any]] = []
    windows: list[dict[str, Any]] = []
    for window in WINDOWS:
        train_raw = _window_rows(rows, None, window.train_end)
        test_raw = _window_rows(rows, window.test_start, window.test_end)
        train, scales = normalize_window_rows(train_raw, train_raw)
        test, _ = normalize_window_rows(test_raw, train_raw)
        train = [row for row in train if str(row.get("model_eligible")).lower() == "true"]
        test = [row for row in test if str(row.get("model_eligible")).lower() == "true"]
        if not train or not test:
            windows.append({"window": window.name, "status": "NO_DATA", "train_rows": len(train), "test_rows": len(test)})
            continue

        threshold_selection = None
        if threshold_calibrated:
            ordered_train = sorted(train, key=lambda row: str(row.get("decision_time")))
            split_at = max(1, min(len(ordered_train) - 1, int(len(ordered_train) * 0.80)))
            calibration_fit = _fit_temporal(ordered_train[:split_at], calibrated=True)
            selected_threshold, threshold_selection = _select_threshold(calibration_fit, ordered_train[split_at:])
            temporal_model = _fit_temporal(train, calibrated=True, min_action_confidence=selected_threshold)
        else:
            temporal_model = _fit_temporal(train, balanced=balanced, calibrated=calibrated)
        event_train, event_test, event_scales = _event_baseline_rows(rows, window)
        event_model = _fit_event_baseline(event_train)
        event_test_on_temporal, _ = normalize_window_rows(test_raw, event_train)
        event_test_on_temporal = [row for row in event_test_on_temporal if str(row.get("model_eligible")).lower() == "true"]

        temporal_conditional_predictions = _conditional_predictions(temporal_model, test)
        temporal_conditional = _behavior_metrics(test, temporal_conditional_predictions)
        temporal_auto = roll_forward_predictions(temporal_model, test, scales, market_bar_opens=opens, include_state_overrides=False)
        temporal_auto_metrics = _behavior_metrics(test, temporal_auto["row_predictions"])
        temporal_replay = _replay_portfolio(temporal_auto["merged_events"], bars, start=window.test_start, end=window.test_end, fee_rate=FEE_RATE)

        event_conditional_predictions = _conditional_predictions(event_model, event_test_on_temporal)
        event_conditional = _behavior_metrics(event_test_on_temporal, event_conditional_predictions)
        event_auto = roll_forward_predictions(event_model, event_test_on_temporal, event_scales, market_bar_opens=opens, include_state_overrides=False)
        event_auto_metrics = _behavior_metrics(event_test_on_temporal, event_auto["row_predictions"])
        event_replay = _replay_portfolio(event_auto["merged_events"], bars, start=window.test_start, end=window.test_end, fee_rate=FEE_RATE)

        behavior.extend([
            {"window": window.name, "model": "TEMPORAL", "track": "CONDITIONAL_BEHAVIOR", **temporal_conditional, **_rates(test, temporal_conditional_predictions)},
            {"window": window.name, "model": "TEMPORAL", "track": "STRICT_AUTONOMOUS", **temporal_auto_metrics, **_rates(test, temporal_auto["row_predictions"]), "teacher_state_fields_consumed": temporal_auto["teacher_state_fields_consumed"]},
            {"window": window.name, "model": "EVENT_BASELINE", "track": "CONDITIONAL_BEHAVIOR", **event_conditional, **_rates(event_test_on_temporal, event_conditional_predictions)},
            {"window": window.name, "model": "EVENT_BASELINE", "track": "STRICT_AUTONOMOUS", **event_auto_metrics, **_rates(event_test_on_temporal, event_auto["row_predictions"]), "teacher_state_fields_consumed": event_auto["teacher_state_fields_consumed"]},
        ])
        performance.extend([
            {"window": window.name, "model": "TEMPORAL", "track": "STRICT_AUTONOMOUS", "cost_profile": "BASE", "target_coefficient_max_abs": _max_target_coefficient(temporal_model), **{key: value for key, value in temporal_replay.items() if key != "per_symbol"}},
            {"window": window.name, "model": "EVENT_BASELINE", "track": "STRICT_AUTONOMOUS", "cost_profile": "BASE", "target_coefficient_max_abs": _max_target_coefficient(event_model), **{key: value for key, value in event_replay.items() if key != "per_symbol"}},
        ])
        windows.append({
            "window": window.name,
            "status": "TEST_DATA_AVAILABLE",
            "train_rows": len(train),
            "test_rows": len(test),
            "event_baseline_train_rows": len(event_train),
            "event_baseline_test_rows": len(event_test_on_temporal),
            "threshold_selection": threshold_selection,
        })
        del temporal_conditional_predictions, event_conditional_predictions, temporal_auto, event_auto, temporal_model, event_model
        if threshold_selection is not None:
            del calibration_fit

    temporal_perf = [row for row in performance if row["model"] == "TEMPORAL"]
    event_perf = [row for row in performance if row["model"] == "EVENT_BASELINE"]
    gates = {
        "causal_audit_pass": causal["status"] == "PASS",
        "all_walk_forward_windows_available": len(temporal_perf) == len(WINDOWS),
        "target_coefficients_finite_and_bounded": all(float(row.get("target_coefficient_max_abs", float("inf"))) < 100.0 for row in temporal_perf),
        "strict_autonomous_positive_all_windows": all(row.get("net_return") is not None and float(row["net_return"]) > 0 for row in temporal_perf),
        "strict_autonomous_profit_factor_gt_one_all_windows": all(row.get("profit_factor") is not None and float(row["profit_factor"]) > 1 for row in temporal_perf),
        "temporal_model_beats_event_baseline_net_all_windows": all(float(left.get("net_return", -math.inf)) > float(right.get("net_return", math.inf)) for left, right in zip(temporal_perf, event_perf)),
    }
    result = {
        "report_version": "M15-TEMPORAL-AUTONOMOUS-AUDIT-1.0",
        "status": "DEMO_CONTINUE_LIVE_BLOCKED" if not all(gates.values()) else "CANDIDATE_REVIEW_REQUIRED",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "active_model_unchanged": True,
        "candidate_model_version": candidate_version,
        "baseline_model_version": EVENT_BASELINE_VERSION,
        "dataset": str(dataset_path.relative_to(ROOT)),
        "dataset_rows": len(rows),
        "dataset_eligible_rows": sum(str(row.get("model_eligible")).lower() == "true" for row in rows),
        "dataset_no_trade_rate": sum(row.get("label_next_action") == "NO_TRADE" for row in rows) / len(rows) if rows else None,
        "causal_audit": causal,
        "windows": windows,
        "behavior_results": behavior,
        "performance_results": performance,
        "gates": gates,
        "conclusion": "The temporal candidate teaches explicit market-clock no-trade periods. It remains non-active until strict autonomous, costed walk-forward gates pass; no Demo switch or new order is authorized.",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    lines = [
        "# Cross-Venue Temporal Autonomous Audit",
        "",
        f"- status: **{result['status']}**",
        f"- candidate: `{candidate_version}`",
        f"- baseline: `{EVENT_BASELINE_VERSION}`",
        f"- dataset rows: `{len(rows)}`; explicit `NO_TRADE` rate: `{result['dataset_no_trade_rate']:.4%}`",
        f"- active Demo model changed: **no**",
        "",
        "## Causal audit",
        "",
        f"- status: **{causal['status']}**",
        *[f"- `{key}`: `{value}`" for key, value in causal["checks"].items()],
        "",
        "## Strict autonomous costed replay",
        "",
        "| window | temporal net | event baseline net | temporal PF | baseline PF | temporal target MAE | no-trade observed | no-trade predicted |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    by_window = {(row["window"], row["model"]): row for row in performance}
    by_behavior = {(row["window"], row["model"], row["track"]): row for row in behavior}
    for window in WINDOWS:
        temporal = by_window.get((window.name, "TEMPORAL"), {})
        baseline = by_window.get((window.name, "EVENT_BASELINE"), {})
        metrics = by_behavior.get((window.name, "TEMPORAL", "STRICT_AUTONOMOUS"), {})
        fmt = lambda value: "—" if value is None else f"{float(value):.6f}"
        lines.append(f"| {window.name} | {fmt(temporal.get('net_return'))} | {fmt(baseline.get('net_return'))} | {fmt(temporal.get('profit_factor'))} | {fmt(baseline.get('profit_factor'))} | {fmt(metrics.get('target_exposure_mae'))} | {float(metrics.get('observed_no_trade_rate', 0)):.2%} | {float(metrics.get('predicted_no_trade_rate', 0)):.2%} |")
    lines += [
        "",
        "## Gates",
        "",
        *[f"- `{key}`: **{'PASS' if value else 'FAIL'}**" for key, value in gates.items()],
        "",
        "## Boundary",
        "",
        "This report measures whether a robot trained on a market clock can reproduce behavior while using its own simulated state. It does not prove the original trader used these indicators, does not promise profitability, and does not activate the Demo model.",
    ]
    report_md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def _conditional_predictions(model: CrossAssetNumpyLogisticStrategy, rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], Any]]:
    from quant_bot.strategy.feature_contract import strategy_input_from_row

    output = []
    for row in rows:
        try:
            output.append((row, model.predict(strategy_input_from_row(row))))
        except (KeyError, TypeError, ValueError):
            continue
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_TEMPORAL)
    parser.add_argument("--balanced", action="store_true", help="use explicit inverse-frequency class weighting")
    parser.add_argument("--calibrated", action="store_true", help="use sqrt-balanced weighting and action-target consistency")
    parser.add_argument("--threshold-calibrated", action="store_true", help="select a train-only confidence threshold with a fee/turnover proxy")
    args = parser.parse_args()
    try:
        if args.threshold_calibrated:
            report_path = ROOT / "quant" / "reports" / "cross_venue_temporal_threshold_calibrated_autonomous_audit.json"
            report_md_path = ROOT / "quant" / "reports" / "cross_venue_temporal_threshold_calibrated_autonomous_audit.md"
        elif args.calibrated:
            report_path = ROOT / "quant" / "reports" / "cross_venue_temporal_calibrated_autonomous_audit.json"
            report_md_path = ROOT / "quant" / "reports" / "cross_venue_temporal_calibrated_autonomous_audit.md"
        elif args.balanced:
            report_path = ROOT / "quant" / "reports" / "cross_venue_temporal_balanced_autonomous_audit.json"
            report_md_path = ROOT / "quant" / "reports" / "cross_venue_temporal_balanced_autonomous_audit.md"
        else:
            report_path = REPORT
            report_md_path = REPORT_MD
        result = build(dataset_path=args.dataset.resolve(), balanced=args.balanced, calibrated=args.calibrated, threshold_calibrated=args.threshold_calibrated, report_path=report_path, report_md_path=report_md_path)
    except (FileNotFoundError, OSError, ValueError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "TEMPORAL_AUDIT_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": result["status"], "dataset_rows": result["dataset_rows"], "gates": result["gates"], "report": str(report_path)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
