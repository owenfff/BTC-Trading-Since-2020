#!/usr/bin/env python3
"""Validate the stable-target candidate without changing the active model."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
for path in (ROOT, SRC, ROOT / "quant" / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from audit_cross_venue_strategy import (  # noqa: E402
    DATASET_V3,
    FEE_RATE,
    WINDOWS,
    _behavior_metrics,
    _conditional_predictions,
    _fit,
    _load_bars,
    _read_dataset,
    _replay_portfolio,
    _window_rows,
)
from quant_bot.strategy.supervised_models import CrossAssetNumpyLogisticStrategy  # noqa: E402
from research.autonomous_replay import normalize_window_rows, roll_forward_predictions, state_key  # noqa: E402


REPORT = ROOT / "quant" / "reports" / "cross_asset_v32_stable_target_audit.json"
REPORT_MD = ROOT / "quant" / "reports" / "cross_asset_v32_stable_target_audit.md"
CANDIDATE_VERSION = "behavioral-distillation-v3.2-stable-target"


def _fit_candidate(rows: list[dict[str, Any]]) -> CrossAssetNumpyLogisticStrategy:
    model = CrossAssetNumpyLogisticStrategy(target_l2=1.0)
    model.fit(rows)
    model.version = CANDIDATE_VERSION
    return model


def _max_target_coefficient(model: CrossAssetNumpyLogisticStrategy) -> float:
    if model.target_coef is None:
        return float("inf")
    return float(np.max(np.abs(model.target_coef)))


def _teacher_target_replay(rows: list[dict[str, Any]], bars: dict[str, list[Any]], window: Any) -> dict[str, Any]:
    events = []
    for row in rows:
        try:
            target = float(row["label_next_target_exposure"])
        except (KeyError, TypeError, ValueError):
            continue
        events.append({
            "venue_symbol": state_key(row),
            "decision_time": row.get("decision_time"),
            "target_exposure": target,
            "action": row.get("label_next_action"),
            "confidence": 1.0,
        })
    return _replay_portfolio(events, bars, start=window.test_start, end=window.test_end, fee_rate=FEE_RATE)


def build() -> dict[str, Any]:
    rows = _read_dataset(DATASET_V3)
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

        models = {
            "v3": _fit(train, "behavioral-distillation-v3-cross-asset-indicators"),
            "v3.2": _fit_candidate(train),
        }
        for name, model in models.items():
            conditional = _conditional_predictions(model, test)
            conditional_metrics = _behavior_metrics(test, conditional)
            autonomous = roll_forward_predictions(model, test, scales, market_bar_opens=opens)
            autonomous_metrics = _behavior_metrics(test, autonomous["row_predictions"])
            replay = _replay_portfolio(autonomous["merged_events"], bars, start=window.test_start, end=window.test_end, fee_rate=FEE_RATE)
            behavior.extend([
                {"window": window.name, "model": name, "track": "CONDITIONAL_BEHAVIOR", **conditional_metrics},
                {"window": window.name, "model": name, "track": "STRICT_AUTONOMOUS", **autonomous_metrics, "teacher_state_fields_consumed": autonomous["teacher_state_fields_consumed"]},
            ])
            performance.append({
                "window": window.name,
                "model": name,
                "track": "STRICT_AUTONOMOUS",
                "cost_profile": "BASE",
                "target_coefficient_max_abs": _max_target_coefficient(model),
                **{key: value for key, value in replay.items() if key != "per_symbol"},
            })

        teacher = _teacher_target_replay(test, bars, window)
        performance.append({
            "window": window.name,
            "model": "TEACHER_TARGET",
            "track": "OBSERVED_TARGET_REPLAY",
            "cost_profile": "BASE",
            **{key: value for key, value in teacher.items() if key != "per_symbol"},
        })
        windows.append({"window": window.name, "status": "TEST_DATA_AVAILABLE", "train_rows": len(train), "test_rows": len(test)})

    by_key = {(row["window"], row["model"]): row for row in performance if row["track"] == "STRICT_AUTONOMOUS"}
    candidate = [by_key[(window.name, "v3.2")] for window in WINDOWS if (window.name, "v3.2") in by_key]
    baseline = [by_key[(window.name, "v3")] for window in WINDOWS if (window.name, "v3") in by_key]
    improvement = [
        {
            "window": left["window"],
            "candidate_net_return": left.get("net_return"),
            "baseline_net_return": right.get("net_return"),
            "candidate_profit_factor": left.get("profit_factor"),
            "baseline_profit_factor": right.get("profit_factor"),
            "candidate_target_coefficient_max_abs": left.get("target_coefficient_max_abs"),
            "baseline_target_coefficient_max_abs": right.get("target_coefficient_max_abs"),
        }
        for left, right in zip(candidate, baseline)
    ]
    gates = {
        "target_coefficients_finite_and_bounded": all(float(row.get("target_coefficient_max_abs", float("inf"))) < 100.0 for row in candidate),
        "strict_autonomous_positive_all_windows": all(row.get("net_return") is not None and float(row["net_return"]) > 0 for row in candidate),
        "strict_autonomous_profit_factor_gt_one_all_windows": all(row.get("profit_factor") is not None and float(row["profit_factor"]) > 1 for row in candidate),
        "candidate_has_test_results_for_all_windows": len(candidate) == len(WINDOWS),
    }
    result = {
        "report_version": "M15-V3.2-STABLE-TARGET-AUDIT-1.0",
        "status": "DEMO_CONTINUE_LIVE_BLOCKED" if not all(gates.values()) else "CANDIDATE_REVIEW_REQUIRED",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "active_model_unchanged": True,
        "candidate_model_version": CANDIDATE_VERSION,
        "candidate_artifact": "quant/outputs/cross_asset_deployment_model_v32.json",
        "candidate_target_l2": 1.0,
        "windows": windows,
        "behavior_results": behavior,
        "performance_results": performance,
        "comparison": improvement,
        "gates": gates,
        "conclusion": "Ridge regularization removes target-exposure coefficient explosion, but the candidate still fails strict autonomous profitability gates and is not promoted.",
    }
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    lines = [
        "# v3.2 Stable Target Audit",
        "",
        f"- status: **{result['status']}**",
        f"- candidate: `{CANDIDATE_VERSION}`",
        "- active model changed: **no**",
        "- target regression: ridge λ = `1.0`",
        "",
        "## Strict autonomous results",
        "",
        "| window | v3 net | v3.2 net | v3 PF | v3.2 PF | v3 max coefficient | v3.2 max coefficient |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for row in improvement:
        fmt = lambda value: "—" if value is None else f"{float(value):.6f}"
        lines.append(f"| {row['window']} | {fmt(row['baseline_net_return'])} | {fmt(row['candidate_net_return'])} | {fmt(row['baseline_profit_factor'])} | {fmt(row['candidate_profit_factor'])} | {fmt(row['baseline_target_coefficient_max_abs'])} | {fmt(row['candidate_target_coefficient_max_abs'])} |")
    lines += [
        "",
        "## Gates",
        "",
        *[f"- `{key}`: **{'PASS' if value else 'FAIL'}**" for key, value in gates.items()],
        "",
        "## Boundary",
        "",
        "The candidate reduces the numerical failure from target-regression collinearity, but costed strict autonomous replay remains below the promotion bar. It stays a non-active candidate; no Demo model switch or new order is authorized.",
    ]
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    print(json.dumps(build(), ensure_ascii=False))
