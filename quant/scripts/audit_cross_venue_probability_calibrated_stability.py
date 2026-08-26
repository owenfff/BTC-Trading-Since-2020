#!/usr/bin/env python3
"""Audit train-only probability calibration and per-symbol stability.

This is an independent research candidate.  It never changes the active Demo
artifact and never calls a private exchange endpoint.  Each walk-forward
training interval is split chronologically into a fit segment, a probability
calibration segment, and a threshold-selection segment before the untouched
test interval is replayed from zero simulated state.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
for path in (ROOT, SRC, ROOT / "quant" / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from audit_cross_venue_temporal_model import (  # noqa: E402
    DATASET_TEMPORAL,
    FEE_RATE,
    WINDOWS,
    _behavior_metrics,
    _causal_audit,
    _conditional_predictions,
    _load_bars,
    _number,
    _read_temporal,
    _rates,
    _replay_portfolio,
    _select_threshold,
    _window_rows,
    _fit_temporal,
)
from research.autonomous_replay import (  # noqa: E402
    normalize_window_rows,
    roll_forward_predictions,
    state_key,
)
from quant_bot.strategy.feature_contract import strategy_input_from_row  # noqa: E402


UTC = timezone.utc
VERSION = "behavioral-distillation-v3.6-probability-calibrated"
REPORT = ROOT / "quant" / "reports" / "cross_venue_probability_calibrated_stability_audit.json"
REPORT_MD = ROOT / "quant" / "reports" / "cross_venue_probability_calibrated_stability_audit.md"
PER_SYMBOL = ROOT / "quant" / "reports" / "cross_venue_probability_calibrated_by_symbol.csv"
PREVIOUS_REPORT = ROOT / "quant" / "reports" / "cross_venue_temporal_threshold_calibrated_autonomous_audit.json"
MIN_SYMBOL_ROWS = 100


def _split_training_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Create fit/calibration/threshold segments without a random split."""

    ordered = sorted((dict(row) for row in rows), key=lambda row: str(row.get("decision_time")))
    if len(ordered) < 3:
        return [], [], []
    fit_end = max(1, int(len(ordered) * 0.60))
    calibration_end = max(fit_end + 1, int(len(ordered) * 0.80))
    calibration_end = min(len(ordered) - 1, calibration_end)
    return ordered[:fit_end], ordered[fit_end:calibration_end], ordered[calibration_end:]


def _probability_metrics(model: Any, rows: Iterable[Mapping[str, Any]]) -> dict[str, float | int | None]:
    """Measure probabilistic calibration on a labeled, non-test segment."""

    rows = [row for row in rows if row.get("label_status") == "AVAILABLE" and str(row.get("label_next_action") or "") in model.actions]
    if not rows:
        return {"rows": 0, "nll": None, "brier": None, "ece": None}
    action_index = {action: index for index, action in enumerate(model.actions)}
    probabilities = []
    labels = []
    for row in rows:
        try:
            probabilities.append(model.predict_proba(strategy_input_from_row(row)))
            labels.append(action_index[str(row["label_next_action"])])
        except (KeyError, TypeError, ValueError):
            continue
    if not probabilities:
        return {"rows": 0, "nll": None, "brier": None, "ece": None}
    import numpy as np

    matrix = np.asarray(probabilities, dtype=float)
    label_array = np.asarray(labels, dtype=int)
    nll = float(-np.mean(np.log(np.clip(matrix[np.arange(len(label_array)), label_array], 1e-12, 1.0))))
    one_hot = np.eye(len(model.actions), dtype=float)[label_array]
    brier = float(np.mean(np.sum((matrix - one_hot) ** 2, axis=1)))
    confidence = matrix.max(axis=1)
    predicted = matrix.argmax(axis=1)
    ece = 0.0
    for lower in np.linspace(0.0, 0.9, 10):
        upper = lower + 0.1
        mask = (confidence >= lower) & (confidence < upper if upper < 1.0 else confidence <= upper)
        if mask.any():
            ece += float(mask.mean()) * abs(float(confidence[mask].mean()) - float((predicted[mask] == label_array[mask]).mean()))
    return {"rows": len(label_array), "nll": nll, "brier": brier, "ece": float(ece)}


def _fit_candidate(train_rows: list[dict[str, Any]]) -> tuple[Any, dict[str, Any]]:
    fit_rows, calibration_rows, threshold_rows = _split_training_rows(train_rows)
    if not fit_rows or not calibration_rows or not threshold_rows:
        raise ValueError("nested temporal split requires fit, calibration, and threshold rows")
    model = _fit_temporal(fit_rows, calibrated=True)
    calibration = model.calibrate_probabilities(calibration_rows)
    calibration["evaluation"] = _probability_metrics(model, calibration_rows)
    threshold, selection = _select_threshold(model, threshold_rows)
    model.min_action_confidence = threshold
    model.version = VERSION
    return model, {
        "fit_rows": len(fit_rows),
        "calibration_rows": len(calibration_rows),
        "threshold_rows": len(threshold_rows),
        "probability_calibration": calibration,
        "threshold_selection": selection,
    }


def _per_symbol_rows(
    rows: list[dict[str, Any]],
    predictions: list[tuple[dict[str, Any], Any]],
    replay: Mapping[str, Any],
    window: str,
) -> list[dict[str, Any]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    predicted: defaultdict[str, list[tuple[dict[str, Any], Any]]] = defaultdict(list)
    for row in rows:
        grouped[state_key(row)].append(row)
    for row, signal in predictions:
        predicted[state_key(row)].append((row, signal))
    replay_by_key = dict(replay.get("per_symbol") or {})
    output: list[dict[str, Any]] = []
    for key in sorted(grouped):
        subset = grouped[key]
        subset_predictions = predicted.get(key, [])
        behavior = _behavior_metrics(subset, subset_predictions)
        replay_metrics = dict(replay_by_key.get(key) or {})
        actions = [signal for _, signal in subset_predictions]
        output.append({
            "window": window,
            "state_key": key,
            "source_venue": str(subset[0].get("source_venue") or ""),
            "canonical_asset": str(subset[0].get("canonical_asset") or ""),
            "rows": len(subset),
            "prediction_rows": len(subset_predictions),
            "action_count": sum(signal.action != "NO_TRADE" for signal in actions),
            "mean_confidence": (sum(float(signal.confidence) for signal in actions) / len(actions)) if actions else None,
            "net_return": replay_metrics.get("net_return"),
            "profit_factor": replay_metrics.get("profit_factor"),
            "executed_adjustments": replay_metrics.get("executed_adjustments"),
            "fees": replay_metrics.get("fees"),
            "funding": replay_metrics.get("funding"),
            "slippage": replay_metrics.get("slippage"),
            "action_macro_f1": behavior.get("action_macro_f1"),
            "target_exposure_mae": behavior.get("target_exposure_mae"),
            "predicted_no_trade_rate": _rates(subset, subset_predictions).get("predicted_no_trade_rate"),
            "status": "STABLE_SAMPLE" if len(subset) >= MIN_SYMBOL_ROWS else "LOW_SAMPLE",
        })
    return output


def _stability_summary(rows: list[dict[str, Any]], window: str) -> dict[str, Any]:
    selected = [row for row in rows if row["window"] == window and row["status"] == "STABLE_SAMPLE" and row.get("net_return") is not None]
    returns = [float(row["net_return"]) for row in selected]
    pfs = [float(row["profit_factor"]) for row in selected if row.get("profit_factor") is not None]
    venues = sorted({str(row.get("source_venue") or "") for row in selected})
    return {
        "window": window,
        "stable_symbol_count": len(selected),
        "venue_count": len(venues),
        "venues": venues,
        "positive_net_fraction": (sum(value > 0 for value in returns) / len(returns)) if returns else None,
        "profit_factor_gt_one_fraction": (sum(value > 1 for value in pfs) / len(pfs)) if pfs else None,
        "median_net_return": (sorted(returns)[len(returns) // 2] if returns else None),
        "minimum_net_return": min(returns) if returns else None,
        "maximum_net_return": max(returns) if returns else None,
    }


def _venue_coverage(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Describe which venues can actually enter each global test window."""

    output: dict[str, Any] = {}
    for venue in sorted({str(row.get("source_venue") or "UNKNOWN") for row in rows}):
        venue_rows = [row for row in rows if str(row.get("source_venue") or "UNKNOWN") == venue]
        times = sorted(str(row.get("decision_time")) for row in venue_rows)
        output[venue] = {
            "rows": len(venue_rows),
            "first_decision_time": times[0] if times else None,
            "last_decision_time": times[-1] if times else None,
            "global_test_rows": {window.name: len(_window_rows(venue_rows, window.test_start, window.test_end)) for window in WINDOWS},
        }
    return output


def _native_venue_diagnostics(venue_rows: list[dict[str, Any]], bars: Mapping[str, Any], opens: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Run a within-venue holdout for a venue absent from global test windows.

    This is descriptive only: it tests whether the candidate can behave
    consistently within the pinned venue snapshot, but it is not a substitute
    for a shared cross-venue out-of-time test and is never a promotion gate.
    """

    ordered = sorted(venue_rows, key=lambda row: str(row.get("decision_time")))
    if len(ordered) < 20:
        return []
    train_end = max(3, min(len(ordered) - 1, int(len(ordered) * 0.80)))
    train_raw = ordered[:train_end]
    test_raw = ordered[train_end:]
    train, scales = normalize_window_rows(train_raw, train_raw)
    test, _ = normalize_window_rows(test_raw, train_raw)
    train = [row for row in train if str(row.get("model_eligible")).lower() == "true"]
    test = [row for row in test if str(row.get("model_eligible")).lower() == "true"]
    if not train or not test:
        return [{"source_venue": str(ordered[0].get("source_venue") or ""), "status": "INSUFFICIENT_TRAIN_SCALE", "train_rows": len(train), "test_rows": len(test)}]
    model, stages = _fit_candidate(train)
    autonomous = roll_forward_predictions(model, test, scales, market_bar_opens=opens, include_state_overrides=False)
    first = datetime.fromisoformat(str(test[0]["decision_time"]).replace("Z", "+00:00")).astimezone(UTC)
    last = datetime.fromisoformat(str(test[-1]["decision_time"]).replace("Z", "+00:00")).astimezone(UTC) + timedelta(hours=1)
    replay = _replay_portfolio(autonomous["merged_events"], bars, start=first, end=last, fee_rate=FEE_RATE)
    conditional_predictions = _conditional_predictions(model, test)
    return [{
        "source_venue": str(ordered[0].get("source_venue") or ""),
        "status": "DIAGNOSTIC_ONLY",
        "train_rows": len(train),
        "test_rows": len(test),
        "nested_stages": stages,
        "behavior": {
            "conditional": {**_behavior_metrics(test, conditional_predictions), **_rates(test, conditional_predictions)},
            "strict_autonomous": {**_behavior_metrics(test, autonomous["row_predictions"]), **_rates(test, autonomous["row_predictions"])},
        },
        "performance": {key: value for key, value in replay.items() if key != "per_symbol"},
    }]


def _previous_comparison() -> dict[str, Any] | None:
    if not PREVIOUS_REPORT.exists():
        return None
    try:
        payload = json.loads(PREVIOUS_REPORT.read_text(encoding="utf-8"))
        return {
            str(row.get("window")): {
                "net_return": row.get("net_return"),
                "profit_factor": row.get("profit_factor"),
            }
            for row in payload.get("performance_results", [])
            if row.get("model") == "TEMPORAL" and row.get("track") == "STRICT_AUTONOMOUS"
        }
    except (OSError, ValueError, TypeError):
        return None


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
        model, stages = _fit_candidate(train)
        test_predictions = _conditional_predictions(model, test)
        autonomous = roll_forward_predictions(model, test, scales, market_bar_opens=opens, include_state_overrides=False)
        autonomous_metrics = _behavior_metrics(test, autonomous["row_predictions"])
        replay = _replay_portfolio(autonomous["merged_events"], bars, start=window.test_start, end=window.test_end, fee_rate=FEE_RATE)
        symbol_rows = _per_symbol_rows(test, autonomous["row_predictions"], replay, window.name)
        per_symbol.extend(symbol_rows)
        behavior.extend([
            {"window": window.name, "model": "V3.6", "track": "CONDITIONAL_BEHAVIOR", **_behavior_metrics(test, test_predictions), **_rates(test, test_predictions)},
            {"window": window.name, "model": "V3.6", "track": "STRICT_AUTONOMOUS", **autonomous_metrics, **_rates(test, autonomous["row_predictions"]), "teacher_state_fields_consumed": autonomous["teacher_state_fields_consumed"]},
        ])
        performance.append({
            "window": window.name,
            "model": "V3.6",
            "track": "STRICT_AUTONOMOUS",
            "cost_profile": "BASE",
            "target_coefficient_max_abs": max(abs(float(value)) for value in model.target_coef) if model.target_coef is not None else None,
            **{key: value for key, value in replay.items() if key != "per_symbol"},
        })
        windows.append({
            "window": window.name,
            "status": "TEST_DATA_AVAILABLE",
            "train_rows": len(train),
            "test_rows": len(test),
            "nested_stages": stages,
            "test_probability_metrics": _probability_metrics(model, test),
            "per_symbol_stability": _stability_summary(per_symbol, window.name),
        })
        del model, test_predictions, autonomous, train, test

    performance_rows = [row for row in performance if row.get("model") == "V3.6"]
    venue_coverage = _venue_coverage(rows)
    native_venue_diagnostics: list[dict[str, Any]] = []
    for venue, summary in venue_coverage.items():
        summary["global_model_test_rows"] = {window.name: model_test_counts.get(venue, {}).get(window.name, 0) for window in WINDOWS}
        if not any(int(value or 0) > 0 for value in summary.get("global_model_test_rows", {}).values()):
            native_venue_diagnostics.extend(_native_venue_diagnostics(
                [row for row in rows if str(row.get("source_venue") or "UNKNOWN") == venue], bars, opens
            ))
    calibration_ok = all(
        (window.get("nested_stages", {}).get("probability_calibration", {}).get("nll_after") is not None)
        and float(window["nested_stages"]["probability_calibration"]["nll_after"]) <= float(window["nested_stages"]["probability_calibration"]["nll_before"]) + 1e-9
        for window in windows if window.get("status") == "TEST_DATA_AVAILABLE"
    )
    gates = {
        "causal_audit_pass": causal.get("status") == "PASS",
        "all_walk_forward_windows_available": len(performance_rows) == len(WINDOWS),
        "calibration_nll_not_worse_on_training_holdouts": calibration_ok,
        "target_coefficients_finite_and_bounded": all(row.get("target_coefficient_max_abs") is not None and float(row["target_coefficient_max_abs"]) < 100.0 for row in performance_rows),
        "global_cross_venue_test_coverage": all(
            sum(int(value or 0) for value in summary.get("global_model_test_rows", {}).values()) > 0
            for summary in venue_coverage.values()
        ),
        "strict_autonomous_positive_all_windows": all(row.get("net_return") is not None and float(row["net_return"]) > 0 for row in performance_rows),
        "strict_autonomous_profit_factor_gt_one_all_windows": all(row.get("profit_factor") is not None and float(row["profit_factor"]) > 1 for row in performance_rows),
        "per_symbol_results_complete": all(window.get("per_symbol_stability", {}).get("stable_symbol_count", 0) > 0 for window in windows if window.get("status") == "TEST_DATA_AVAILABLE"),
    }
    previous = _previous_comparison()
    result = {
        "report_version": "M15-PROBABILITY-CALIBRATED-STABILITY-1.0",
        "status": "DEMO_CONTINUE_LIVE_BLOCKED" if not all(gates.values()) else "CANDIDATE_REVIEW_REQUIRED",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "active_model_unchanged": True,
        "candidate_model_version": VERSION,
        "dataset": str(dataset_path.relative_to(ROOT)),
        "dataset_rows": len(rows),
        "dataset_eligible_rows": sum(str(row.get("model_eligible")).lower() == "true" for row in rows),
        "causal_audit": causal,
        "windows": windows,
        "behavior_results": behavior,
        "performance_results": performance,
        "per_symbol_results": per_symbol,
        "venue_coverage": venue_coverage,
        "native_venue_diagnostics": native_venue_diagnostics,
        "previous_v3_5_comparison": previous,
        "gates": gates,
        "calibration_contract": "fit first 60% of each training window; calibrate probabilities on next 20%; select abstention threshold on final 20%; evaluate only on untouched test window",
        "conclusion": "Probability calibration and per-symbol stability remain research-only. No Demo switch or order is authorized unless every strict autonomous promotion gate passes.",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    _write_csv(per_symbol_path, per_symbol)
    lines = [
        "# Cross-Venue Probability Calibration and Stability Audit",
        "",
        f"- status: **{result['status']}**",
        f"- candidate: `{VERSION}`",
        "- active Demo model changed: **no**",
        f"- dataset rows: `{len(rows)}`",
        "",
        "## Venue coverage",
        "",
    ]
    for venue, summary in venue_coverage.items():
        raw_counts = ", ".join(f"{name}={count}" for name, count in summary["global_test_rows"].items())
        model_counts = ", ".join(f"{name}={count}" for name, count in summary["global_model_test_rows"].items())
        lines.append(f"- `{venue}`: `{summary['rows']}` rows, `{summary['first_decision_time']}` to `{summary['last_decision_time']}`; raw global test rows `{raw_counts}`; model-eligible global test rows `{model_counts}`.")
    lines += [
        "- A venue with no global test rows is not silently treated as validated; its within-venue holdout appears below as diagnostic-only.",
        "",
        "## Temporal calibration contract",
        "",
        "Fit uses the first 60% of each training window, probability calibration uses the next 20%, and threshold selection uses the final 20%. The walk-forward test interval is untouched until evaluation.",
        "",
        "## Strict autonomous costed replay",
        "",
        "| window | net return | profit factor | target MAE | observed no-trade | predicted no-trade | stable symbols |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    behavior_by_window = {(row["window"], row["track"]): row for row in behavior}
    performance_by_window = {row["window"]: row for row in performance_rows}
    for window in WINDOWS:
        item = performance_by_window.get(window.name, {})
        metrics = behavior_by_window.get((window.name, "STRICT_AUTONOMOUS"), {})
        stability = next((entry.get("per_symbol_stability", {}) for entry in windows if entry.get("window") == window.name), {})
        fmt = lambda value: "—" if value is None else f"{float(value):.6f}"
        lines.append(f"| {window.name} | {fmt(item.get('net_return'))} | {fmt(item.get('profit_factor'))} | {fmt(metrics.get('target_exposure_mae'))} | {float(metrics.get('observed_no_trade_rate', 0)):.2%} | {float(metrics.get('predicted_no_trade_rate', 0)):.2%} | {stability.get('stable_symbol_count', 0)} |")
    lines += [
        "",
        "## Per-symbol stability",
        "",
        f"- Minimum sample for a stable-symbol statistic: `{MIN_SYMBOL_ROWS}` rows.",
        f"- Detail CSV: `{per_symbol_path.relative_to(ROOT)}`.",
    ]
    for window in WINDOWS:
        stability = next((entry.get("per_symbol_stability", {}) for entry in windows if entry.get("window") == window.name), {})
        lines.append(f"- `{window.name}`: `{stability.get('stable_symbol_count', 0)}` stable symbols; positive-net fraction `{stability.get('positive_net_fraction')}`; PF>1 fraction `{stability.get('profit_factor_gt_one_fraction')}`.")
    lines += ["", "## Native venue diagnostics", ""]
    if native_venue_diagnostics:
        for item in native_venue_diagnostics:
            performance_item = item.get("performance", {})
            lines.append(f"- `{item.get('source_venue')}` (`{item.get('status')}`): train `{item.get('train_rows')}`, test `{item.get('test_rows')}`, strict net `{performance_item.get('net_return')}`, PF `{performance_item.get('profit_factor')}`. This does not satisfy the global cross-venue gate.")
    else:
        lines.append("- No venue-native diagnostic was available.")
    lines += [
        "",
        "## Gates",
        "",
        *[f"- `{key}`: **{'PASS' if value else 'FAIL'}**" for key, value in gates.items()],
        "",
        "## Boundary",
        "",
        "This is a causal behavioral approximation from public trade records. It does not prove exact strategy recovery, future profitability, or deployability; credentials, private endpoints, mainnet connections, and orders were not used.",
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
        print(json.dumps({"status": "BLOCKED", "error_code": "PROBABILITY_CALIBRATION_AUDIT_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": result["status"], "gates": result["gates"], "report": str(REPORT), "per_symbol": str(PER_SYMBOL)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
