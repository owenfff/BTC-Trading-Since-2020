from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_bot.strategy.distilled_rules import DistilledRuleStrategy  # noqa: E402
from quant_bot.strategy.feature_contract import strategy_input_from_row  # noqa: E402
from quant_bot.strategy.imitation_model import HistoricalBehaviorBaseline  # noqa: E402
from quant_bot.strategy.supervised_models import NumpyDecisionTreeStrategy, NumpyLogisticStrategy  # noqa: E402
from quant_bot.strategy.signal_contract import (  # noqa: E402
    ADD_ACTIONS,
    CLOSE_ACTIONS,
    FLIP_ACTIONS,
    OPEN_ACTIONS,
    REDUCE_ACTIONS,
    action_family,
)
from quant_bot.strategy.manifest import STRATEGY_FIDELITY  # noqa: E402


DATASET = ROOT / "quant" / "outputs" / "model_dataset.csv"
REPORTS = ROOT / "quant" / "reports"


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def _corr(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    left_dev = [value - left_mean for value in left]
    right_dev = [value - right_mean for value in right]
    denominator = math.sqrt(sum(value * value for value in left_dev) * sum(value * value for value in right_dev))
    return sum(a * b for a, b in zip(left_dev, right_dev)) / denominator if denominator else 0.0


def _f1_scores(actual: list[str], predicted: list[str]) -> tuple[float | None, float | None]:
    labels = sorted(set(actual) | set(predicted))
    if not labels:
        return None, None
    scores: list[tuple[str, float, int]] = []
    for label in labels:
        true_positive = sum(a == label and p == label for a, p in zip(actual, predicted))
        false_positive = sum(a != label and p == label for a, p in zip(actual, predicted))
        false_negative = sum(a == label and p != label for a, p in zip(actual, predicted))
        precision = true_positive / (true_positive + false_positive) if true_positive + false_positive else 0.0
        recall = true_positive / (true_positive + false_negative) if true_positive + false_negative else 0.0
        score = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        support = sum(a == label for a in actual)
        scores.append((label, score, support))
    macro = sum(score for _, score, _ in scores) / len(scores)
    total = sum(support for _, _, support in scores)
    weighted = sum(score * support for _, score, support in scores) / total if total else None
    return macro, weighted


def _sign(value: float | None) -> int:
    if value is None or abs(value) < 1e-12:
        return 0
    return 1 if value > 0 else -1


def _is_open(action: str) -> bool:
    return action in OPEN_ACTIONS or action in FLIP_ACTIONS


def _is_close(action: str) -> bool:
    return action in CLOSE_ACTIONS or action in REDUCE_ACTIONS or action in FLIP_ACTIONS


def _evaluate(rows: list[dict[str, Any]], predictions: list[tuple[dict[str, Any], Any]]) -> dict[str, Any]:
    usable = [(row, signal) for row, signal in predictions if row.get("label_status") == "AVAILABLE" and row.get("label_next_action")]
    actual_actions = [str(row["label_next_action"]) for row, _ in usable]
    predicted_actions = [signal.action for _, signal in usable]
    actual_targets = [_float(row.get("label_next_target_exposure")) for row, _ in usable]
    predicted_targets = [float(signal.target_exposure) for _, signal in usable]
    pairs = [(a, p) for a, p in zip(actual_targets, predicted_targets) if a is not None]
    actual_target_values = [a for a, _ in pairs]
    predicted_target_values = [p for _, p in pairs]
    macro_f1, weighted_f1 = _f1_scores(actual_actions, predicted_actions)
    direction_matches = [
        _sign(actual) == _sign(predicted)
        for actual, predicted in zip(actual_target_values, predicted_target_values)
    ]
    true_times = [_float(row.get("label_time_to_next_action_seconds")) for row, _ in usable]
    timing_rows = [(row, signal, time) for (row, signal), time in zip(usable, true_times) if time is not None]

    def recall_for(actions: set[str]) -> float | None:
        relevant = [predicted in actions for actual, predicted in zip(actual_actions, predicted_actions) if actual in actions]
        return sum(relevant) / len(relevant) if relevant else None

    def timing_error(actions: set[str]) -> float | None:
        errors = []
        for row, signal, time in timing_rows:
            actual = str(row["label_next_action"])
            if actual in actions:
                errors.append(0.0 if signal.action in actions else float(time))
        return _mean(errors)

    confidence_gaps: list[float] = []
    for low, high in ((0.0, 0.2), (0.2, 0.4), (0.4, 0.6), (0.6, 0.8), (0.8, 1.000001)):
        bucket = [(actual == predicted, signal.confidence) for (actual, predicted), (_, signal) in zip(zip(actual_actions, predicted_actions), usable) if low <= signal.confidence < high]
        if bucket:
            confidence_gaps.append(abs(sum(correct for correct, _ in bucket) / len(bucket) - sum(conf for _, conf in bucket) / len(bucket)))

    return {
        "rows_seen": len(rows),
        "rows_with_future_label": len(usable),
        "action_accuracy": _mean([float(a == p) for a, p in zip(actual_actions, predicted_actions)]),
        "direction_accuracy": _mean([float(value) for value in direction_matches]),
        "action_macro_f1": macro_f1,
        "action_weighted_f1": weighted_f1,
        "target_exposure_mae": _mean([abs(a - p) for a, p in pairs]),
        "target_exposure_correlation": _corr(actual_target_values, predicted_target_values),
        "open_timing_error_seconds": timing_error(set(OPEN_ACTIONS) | set(FLIP_ACTIONS)),
        "close_timing_error_seconds": timing_error(set(CLOSE_ACTIONS) | set(REDUCE_ACTIONS) | set(FLIP_ACTIONS)),
        "add_recall": recall_for(set(ADD_ACTIONS)),
        "reduce_recall": recall_for(set(REDUCE_ACTIONS)),
        "flip_recall": recall_for(set(FLIP_ACTIONS)),
        "cycle_direction_match": _mean([float(_sign(a) == _sign(p)) for a, p in pairs if _sign(a) != 0]),
        "confidence_calibration_gap": _mean(confidence_gaps),
    }


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    if not DATASET.exists():
        raise FileNotFoundError(f"missing frozen M4 dataset: {DATASET}")
    with DATASET.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if not rows:
        raise ValueError("M4 dataset is empty")
    if [row.get("decision_time") for row in rows] != sorted(row.get("decision_time") for row in rows):
        raise ValueError("strategy evaluation requires chronological input")

    baseline = HistoricalBehaviorBaseline().fit(rows)
    rules = DistilledRuleStrategy()
    models = {
        "frequency_baseline": baseline,
        "distilled_rules": rules,
        "logistic_numpy": NumpyLogisticStrategy().fit(rows),
        "decision_tree_numpy": NumpyDecisionTreeStrategy().fit(rows),
    }
    predictions: dict[str, list[tuple[dict[str, Any], Any]]] = {}
    for name, model in models.items():
        predictions[name] = [(row, model.predict(strategy_input_from_row(row))) for row in rows]

    report_metrics: dict[str, dict[str, dict[str, Any]]] = {}
    confusion_rows: list[dict[str, Any]] = []
    tracking_rows: list[dict[str, Any]] = []
    regime_rows: list[dict[str, Any]] = []
    for model_name, model_predictions in predictions.items():
        report_metrics[model_name] = {}
        for split in ("TRAIN", "VALIDATION", "TEST"):
            split_rows = [row for row in rows if row.get("dataset_split") == split]
            split_predictions = [(row, signal) for row, signal in model_predictions if row.get("dataset_split") == split]
            report_metrics[model_name][split] = _evaluate(split_rows, split_predictions)
            counts: Counter[tuple[str, str]] = Counter(
                (str(row.get("label_next_action") or ""), signal.action)
                for row, signal in split_predictions
                if row.get("label_status") == "AVAILABLE" and row.get("label_next_action")
            )
            confusion_rows.extend({"model": model_name, "split": split, "true_action": actual, "predicted_action": predicted, "count": count} for (actual, predicted), count in sorted(counts.items()))
            tracking = report_metrics[model_name][split]
            tracking_rows.append({"model": model_name, "split": split, "rows_seen": tracking["rows_seen"], "rows_with_future_label": tracking["rows_with_future_label"], "target_exposure_mae": tracking["target_exposure_mae"], "target_exposure_correlation": tracking["target_exposure_correlation"], "direction_accuracy": tracking["direction_accuracy"]})
            for regime in sorted({str(row.get("feature_market_regime") or "UNKNOWN") for row in split_rows}):
                regime_pairs = [(row, signal) for row, signal in split_predictions if str(row.get("feature_market_regime") or "UNKNOWN") == regime and row.get("label_status") == "AVAILABLE" and row.get("label_next_action")]
                if regime_pairs:
                    regime_rows.append({"model": model_name, "split": split, "market_regime": regime, "row_count": len(regime_pairs), "action_accuracy": _mean([float(row["label_next_action"] == signal.action) for row, signal in regime_pairs]), "direction_accuracy": _mean([float(_sign(_float(row.get("label_next_target_exposure"))) == _sign(signal.target_exposure)) for row, signal in regime_pairs]), "target_exposure_mae": _mean([abs((_float(row.get("label_next_target_exposure")) or 0.0) - signal.target_exposure) for row, signal in regime_pairs])})

    _write_csv(REPORTS / "strategy_action_confusion.csv", confusion_rows, ["model", "split", "true_action", "predicted_action", "count"])
    _write_csv(REPORTS / "strategy_position_tracking.csv", tracking_rows, ["model", "split", "rows_seen", "rows_with_future_label", "target_exposure_mae", "target_exposure_correlation", "direction_accuracy"])
    _write_csv(REPORTS / "strategy_regime_fidelity.csv", regime_rows, ["model", "split", "market_regime", "row_count", "action_accuracy", "direction_accuracy", "target_exposure_mae"])

    manifest = json.loads((REPORTS / "model_dataset_manifest.json").read_text(encoding="utf-8"))
    result = {
        "report_version": "M5-STRATEGY-DISTILLATION-1.0",
        "source_commit": manifest.get("source_commit"),
        "analysis_commit": _git_commit(),
        "analysis_branch": "quant/autonomous-behavioral-quant-bot-v1",
        "strategy_fidelity": STRATEGY_FIDELITY,
        "training_policy": "Frequency baseline and supervised models fit TRAIN labels only; distilled rules are deterministic. Logistic and tree implementations use deterministic NumPy with no external ML dependency.",
        "input_contract": "M4 feature contract only; observed target/action and all label_* fields are excluded from Strategy Core inputs.",
        "dataset_rows": len(rows),
        "models": report_metrics,
        "raw_account_inputs_unchanged": manifest.get("raw_account_inputs_unchanged"),
        "market_warning": "Historical mark/index context remains explicitly missing and is never backfilled from a current snapshot.",
        "next_stage": "M5.3 optional LightGBM/XGBoost comparison only if a pinned dependency becomes available; otherwise proceed to walk-forward backtesting.",
    }
    (REPORTS / "strategy_fidelity.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    lines = [
        "# Strategy Fidelity",
        "",
        f"- strategy fidelity: **{STRATEGY_FIDELITY}**",
        f"- source dataset rows: `{len(rows)}`",
        f"- analysis commit: `{result['analysis_commit']}`",
        "- M5.1/M5.2 scope: behavior frequency baseline, deterministic interpretable rules, NumPy Logistic Regression, and a small NumPy Decision Tree.",
        "- Every fitted model uses TRAIN labels only; the rule strategy uses no labels and no exchange SDK.",
        "- Historical mark/index context is missing by source limitation and remains an explicit risk tag.",
        "",
        "## Metrics",
        "",
        "| model | split | action accuracy | macro F1 | weighted F1 | direction accuracy | target MAE | target correlation | add recall | reduce recall | flip recall | confidence gap |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for model_name, split_metrics in report_metrics.items():
        for split, metrics in split_metrics.items():
            def fmt(key: str) -> str:
                value = metrics.get(key)
                return "NA" if value is None else f"{value:.6f}"
            lines.append(f"| {model_name} | {split} | {fmt('action_accuracy')} | {fmt('action_macro_f1')} | {fmt('action_weighted_f1')} | {fmt('direction_accuracy')} | {fmt('target_exposure_mae')} | {fmt('target_exposure_correlation')} | {fmt('add_recall')} | {fmt('reduce_recall')} | {fmt('flip_recall')} | {fmt('confidence_calibration_gap')} |")
    lines.extend([
        "",
        "## Timing definitions",
        "",
        "Open and close timing error are conservative miss-latency proxies: when the next labeled action belongs to the relevant family but the strategy emits another family, the full time to that next action is charged; a correct family prediction receives zero error. They are not a claim that the strategy knows a future timestamp.",
        "",
        "## Boundary",
        "",
        "This artifact is a behavioral approximation from trade records. It does not establish profitability, exact intent recovery, or live-trading readiness. Optional boosted-tree comparison, walk-forward backtesting, funding/slippage/latency simulation, and exchange adapters remain later stages.",
    ])
    (REPORTS / "strategy_fidelity.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS", "rows": len(rows), "models": list(models), "analysis_commit": result["analysis_commit"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
