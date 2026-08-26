#!/usr/bin/env python3
"""Compare v3 indicators with the frozen v2 evaluation and decide rollout."""

from __future__ import annotations

import csv
import json
import math
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
REPORTS = ROOT / "quant" / "reports"
OUTPUTS = ROOT / "quant" / "outputs"


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _metric(rows: list[dict[str, str]], window: str, field: str) -> float:
    row = next(row for row in rows if row.get("window") == window and row.get("split") == "TEST" and row.get("model") == "cross_asset_logistic")
    value = _float(row.get(field))
    if value is None:
        raise ValueError(f"missing {field} for {window}")
    return value


def _coverage(dataset_rows: list[dict[str, str]]) -> dict[str, Any]:
    eligible = [row for row in dataset_rows if row.get("model_eligible", "").lower() == "true"]
    fields = {
        "rsi14": "feature_rsi_14",
        "macd_line": "feature_macd_line_12_26",
        "macd_signal": "feature_macd_signal_9",
        "macd_histogram": "feature_macd_histogram",
        "bollinger_zscore": "feature_bollinger_zscore_20",
        "bollinger_percent_b": "feature_bollinger_percent_b_20",
        "volume_percentile_72": "feature_volume_percentile_72bar",
        "funding_rate": "feature_funding_rate",
        "mark_index_basis": "feature_mark_index_basis",
    }
    result: dict[str, Any] = {}
    for name, field in fields.items():
        present = sum(_float(row.get(field)) is not None for row in eligible)
        result[name] = {"field": field, "present_rows": present, "eligible_rows": len(eligible), "coverage": present / len(eligible) if eligible else 0.0, "missing_rows": len(eligible) - present}
    return result


def build() -> dict[str, Any]:
    v2_fidelity = _read_json(REPORTS / "cross_asset_strategy_fidelity.json")
    v3_fidelity = _read_json(REPORTS / "cross_asset_strategy_fidelity_v3.json")
    v2_walk = _read_csv(REPORTS / "cross_asset_walk_forward.csv")
    v3_walk = _read_csv(REPORTS / "cross_asset_walk_forward_v3.csv")
    dataset_rows = _read_csv(OUTPUTS / "cross_asset_model_dataset_v3.csv")

    v2_metrics = v2_fidelity["global_metrics"]["cross_asset_logistic"]
    v3_metrics = v3_fidelity["global_metrics"]["cross_asset_logistic"]
    windows: list[dict[str, Any]] = []
    for window in ("WF1", "WF2", "WF3"):
        v2_macro = _metric(v2_walk, window, "action_macro_f1")
        v3_macro = _metric(v3_walk, window, "action_macro_f1")
        v2_mae = _metric(v2_walk, window, "target_exposure_mae")
        v3_mae = _metric(v3_walk, window, "target_exposure_mae")
        windows.append({
            "window": window,
            "v2_action_macro_f1": v2_macro,
            "v3_action_macro_f1": v3_macro,
            "macro_f1_delta": v3_macro - v2_macro,
            "macro_f1_pass": v3_macro >= v2_macro - 0.02,
            "v2_target_exposure_mae": v2_mae,
            "v3_target_exposure_mae": v3_mae,
            "mae_delta": v3_mae - v2_mae,
            "mae_pass": v3_mae <= v2_mae + 0.01,
            "strict_mae_not_higher": v3_mae <= v2_mae,
        })

    global_macro_pass = v3_metrics["action_macro_f1"] >= v2_metrics["action_macro_f1"]
    global_mae_pass = v3_metrics["target_exposure_mae"] <= v2_metrics["target_exposure_mae"]
    leakage_text = (REPORTS / "cross_asset_v3_leakage_audit.md").read_text(encoding="utf-8")
    leakage_pass = all(f"| {field} | 0 |" in leakage_text for field in ("future_bar_observation_count", "future_funding_observation_count", "future_history_observation_count", "non_future_label_violation_count", "invalid_decision_time_count"))
    all_window_pass = all(item["macro_f1_pass"] and item["mae_pass"] for item in windows)
    approved = bool(global_macro_pass and global_mae_pass and all_window_pass and leakage_pass)
    result = {
        "report_version": "M13-CROSS-ASSET-INDICATOR-ABLATION-1.0",
        "feature_contract_version": "m13-v3-cross-asset-indicators",
        "v2_model_version": "behavioral-distillation-v2-cross-asset-logistic",
        "v3_model_version": "behavioral-distillation-v3-cross-asset-indicators",
        "status": "APPROVED_FOR_DEMO_SWITCH" if approved else "NOT_APPROVED_V2_RETAINED",
        "v2_global": {"action_macro_f1": v2_metrics["action_macro_f1"], "target_exposure_mae": v2_metrics["target_exposure_mae"]},
        "v3_global": {"action_macro_f1": v3_metrics["action_macro_f1"], "target_exposure_mae": v3_metrics["target_exposure_mae"]},
        "global_checks": {"macro_f1_not_below_v2": global_macro_pass, "mae_not_above_v2": global_mae_pass},
        "walk_forward_checks": windows,
        "leakage_check": {"status": "PASS" if leakage_pass else "FAIL", "future_observation_violations": 0 if leakage_pass else None},
        "indicator_coverage": _coverage(dataset_rows),
        "raw_account_inputs_unchanged": bool(v3_fidelity.get("raw_account_inputs_unchanged")),
        "deployment_action": "switch_to_v3_after_safe_stop_and_reconciliation" if approved else "keep_v2_demo_running; do_not_switch",
        "interpretation": "Indicators are model inputs for behavioral approximation, not evidence of the original trader's exact indicators or future profitability.",
    }
    (REPORTS / "cross_asset_indicator_ablation_v3.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    with (REPORTS / "cross_asset_indicator_ablation_v3.csv").open("w", encoding="utf-8", newline="") as handle:
        fields = ["window", "v2_action_macro_f1", "v3_action_macro_f1", "macro_f1_delta", "macro_f1_pass", "v2_target_exposure_mae", "v3_target_exposure_mae", "mae_delta", "mae_pass", "strict_mae_not_higher"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(windows)
    md = [
        "# v2/v3 Cross-Asset Indicator Ablation",
        "",
        f"- status: **{result['status']}**",
        "- v2 remains the Demo deployment unless every gate passes.",
        f"- global Macro-F1: `{v2_metrics['action_macro_f1']:.6f}` -> `{v3_metrics['action_macro_f1']:.6f}`",
        f"- global target exposure MAE: `{v2_metrics['target_exposure_mae']:.6f}` -> `{v3_metrics['target_exposure_mae']:.6f}`",
        "",
        "| window | v2 Macro-F1 | v3 Macro-F1 | delta | v2 MAE | v3 MAE | MAE delta | gate |",
        "|---|---:|---:|---:|---:|---:|---:|---|",
    ]
    for item in windows:
        md.append(f"| {item['window']} | {item['v2_action_macro_f1']:.6f} | {item['v3_action_macro_f1']:.6f} | {item['macro_f1_delta']:+.6f} | {item['v2_target_exposure_mae']:.6f} | {item['v3_target_exposure_mae']:.6f} | {item['mae_delta']:+.6f} | {'PASS' if item['macro_f1_pass'] and item['mae_pass'] else 'FAIL'} |")
    md.extend([
        "",
        "## Decision",
        "",
        ("All configured rollout gates pass. v3 is eligible for a safe Demo switch after stopping new orders, cancelling bot-created orders, preserving positions, and re-running account/WebSocket reconciliation."
         if approved else
         "At least one rollout gate failed. v3 is not deployed and the running v2 Demo model is retained."),
        "",
        "Indicator values are only auditable model input evidence. They do not prove what the original trader used and do not imply profitability.",
    ])
    (REPORTS / "cross_asset_indicator_ablation_v3.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False))
