#!/usr/bin/env python3
"""Evaluate v4.6 with conditional and strict autonomous cross-venue replay."""

from __future__ import annotations

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

from audit_cross_venue_strategy import (  # noqa: E402
    DATASET_V3,
    FROZEN_CUTOFF,
    REPORTS,
    WINDOWS,
    Window,
    _audit_leakage,
    _behavior_metrics,
    _conditional_predictions,
    _load_bars,
    _protected_hash_audit,
    _replay_portfolio,
    _sha256,
    _window_rows,
    _write_csv,
)
from build_unified_distillation_model import _prepare  # noqa: E402
from quant_bot.strategy.deployment import load_deployment_bundle  # noqa: E402
from quant_bot.strategy.supervised_models import CrossAssetNumpyLogisticStrategy  # noqa: E402
from quant_bot.strategy.unified_distillation import UNIFIED_MODEL_VERSION  # noqa: E402
from research.autonomous_replay import normalize_window_rows, roll_forward_predictions, state_key  # noqa: E402


ARTIFACT = ROOT / "quant" / "outputs" / "cross_asset_deployment_model_v46.json"
REPORT = REPORTS / "unified_distillation_audit.json"
REPORT_MD = REPORTS / "unified_distillation_audit.md"
BY_WINDOW = REPORTS / "unified_distillation_by_window.csv"
BY_VENUE = REPORTS / "unified_distillation_by_venue.csv"
COSTS = REPORTS / "unified_distillation_cost_sensitivity.csv"


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _eligible(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [dict(row) for row in rows if str(row.get("model_eligible", "")).lower() == "true" and str(row.get("label_status", "")) == "AVAILABLE" and str(row.get("label_next_action", ""))]


def _fit_candidate(train_rows: list[dict[str, Any]]) -> tuple[Any, dict[str, float], dict[str, Any]]:
    fit_rows, scales, ambiguous, weighting = _prepare(train_rows)
    if not fit_rows:
        raise ValueError("no candidate training rows in walk-forward window")
    model = __import__("quant_bot.strategy.unified_distillation", fromlist=["UnifiedDistilledStrategy"]).UnifiedDistilledStrategy(target_l2=1.0).fit(fit_rows)
    ordered = sorted(fit_rows, key=lambda row: _parse_time(row.get("decision_time")) or datetime.max.replace(tzinfo=timezone.utc))
    split = max(1, int(len(ordered) * 0.8))
    calibration = model.calibrate_action_threshold(ordered[split:]) if split < len(ordered) else {"calibration_rows": 0, "selected_threshold": model.action_threshold}
    return model, scales, {"fit_rows": len(fit_rows), "ambiguous_rows": ambiguous, "weighting": weighting, "threshold_calibration": calibration}


def _baseline(train_rows: list[dict[str, Any]]) -> CrossAssetNumpyLogisticStrategy:
    model = CrossAssetNumpyLogisticStrategy()
    model.version = "behavioral-distillation-v3-cross-venue-indicators"
    fit_rows = [dict(row, dataset_split="TRAIN") for row in train_rows if str(row.get("label_status")) == "AVAILABLE" and str(row.get("label_next_action"))]
    model.fit(fit_rows)
    model.version = "behavioral-distillation-v3-cross-venue-indicators"
    return model


def _venue_coverage(rows: list[dict[str, Any]], test_start: datetime, test_end: datetime) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for venue in ("BITMEX", "HYPERLIQUID"):
        subset = [row for row in rows if str(row.get("source_venue") or "").upper() == venue and test_start <= (_parse_time(row.get("decision_time")) or datetime.max.replace(tzinfo=timezone.utc)) < test_end]
        result[venue] = {"rows": len(subset), "eligible_rows": len(_eligible(subset)), "status": "PASS" if _eligible(subset) else "INSUFFICIENT_COVERAGE"}
    return result


def _gate_rows(window_rows: list[dict[str, Any]], cost_rows: list[dict[str, Any]], coverage: dict[str, Any], leakage: dict[str, Any], protected: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    details: list[dict[str, Any]] = [
        {"gate": "time_leakage_zero", "status": "PASS" if leakage.get("status") == "PASS" else "FAIL"},
        {"gate": "protected_raw_hashes_unchanged", "status": "PASS" if protected.get("status") == "PASS" else "FAIL"},
    ]
    for window in ("WF1", "WF2", "WF3"):
        item = coverage.get(window, {})
        both = all(item.get(venue, {}).get("status") == "PASS" for venue in ("BITMEX", "HYPERLIQUID"))
        details.append({"gate": f"both_venues_{window}_available", "status": "PASS" if both else "FAIL", "coverage": item})
        base = next((row for row in cost_rows if row.get("window") == window and row.get("cost_profile") == "BASE"), None)
        positive = bool(base and base.get("net_return") is not None and float(base["net_return"]) > 0)
        pf = bool(base and base.get("profit_factor") is not None and float(base["profit_factor"]) > 1)
        details.append({"gate": f"strict_autonomous_positive_{window}", "status": "PASS" if positive else "FAIL", "net_return": base.get("net_return") if base else None})
        details.append({"gate": f"strict_autonomous_profit_factor_{window}", "status": "PASS" if pf else "FAIL", "profit_factor": base.get("profit_factor") if base else None})
    for window in ("WF1", "WF2", "WF3"):
        candidate = next((row for row in window_rows if row.get("window") == window and row.get("model") == "v46" and row.get("track") == "CONDITIONAL_BEHAVIOR" and row.get("split") == "TEST"), {})
        baseline = next((row for row in window_rows if row.get("window") == window and row.get("model") == "v3" and row.get("track") == "CONDITIONAL_BEHAVIOR" and row.get("split") == "TEST"), {})
        f1_ok = candidate.get("action_macro_f1") is not None and baseline.get("action_macro_f1") is not None and float(candidate["action_macro_f1"]) >= float(baseline["action_macro_f1"]) - 0.02
        mae_ok = candidate.get("target_exposure_mae") is not None and baseline.get("target_exposure_mae") is not None and float(candidate["target_exposure_mae"]) <= float(baseline["target_exposure_mae"]) + 0.01
        details.append({"gate": f"behavior_macro_f1_not_worse_{window}", "status": "PASS" if f1_ok else "FAIL"})
        details.append({"gate": f"behavior_target_mae_not_worse_{window}", "status": "PASS" if mae_ok else "FAIL"})
    passed = all(item["status"] == "PASS" for item in details)
    return details, passed


def build(dataset_path: Path = DATASET_V3, artifact_path: Path = ARTIFACT) -> dict[str, Any]:
    if not dataset_path.exists():
        raise FileNotFoundError(dataset_path)
    if not artifact_path.exists():
        raise FileNotFoundError(artifact_path)
    rows = _read_csv(dataset_path)
    bundle = load_deployment_bundle(artifact_path, require_model_sha256=True)
    if bundle.model_version != UNIFIED_MODEL_VERSION:
        raise ValueError(f"candidate artifact version mismatch: {bundle.model_version}")
    bars, opens = _load_bars()
    window_metrics: list[dict[str, Any]] = []
    venue_metrics: list[dict[str, Any]] = []
    cost_metrics: list[dict[str, Any]] = []
    coverage: dict[str, Any] = {}
    for window in WINDOWS:
        train_raw = _window_rows(rows, None, window.train_end)
        validation_raw = _window_rows(rows, window.validation_start, window.validation_end)
        test_raw = _window_rows(rows, window.test_start, window.test_end)
        train_norm, scales = normalize_window_rows(train_raw, train_raw)
        validation_norm, _ = normalize_window_rows(validation_raw, train_raw)
        test_norm, _ = normalize_window_rows(test_raw, train_raw)
        train_eligible = _eligible(train_norm)
        validation_eligible = _eligible(validation_norm)
        test_eligible = _eligible(test_norm)
        coverage[window.name] = _venue_coverage(rows, window.test_start, window.test_end)
        if not train_eligible or not test_eligible:
            continue
        model, candidate_scales, fit_meta = _fit_candidate(train_raw)
        baseline = _baseline(train_eligible)
        for name, fitted in (("v46", model), ("v3", baseline)):
            for track, split, source in (("CONDITIONAL_BEHAVIOR", "VALIDATION", validation_eligible), ("CONDITIONAL_BEHAVIOR", "TEST", test_eligible)):
                predictions = _conditional_predictions(fitted, source)
                metrics = _behavior_metrics(source, predictions)
                window_metrics.append({"window": window.name, "model": name, "track": track, "split": split, **metrics})
            autonomous = roll_forward_predictions(fitted, test_eligible, scales, market_bar_opens=opens, include_state_overrides=False)
            auto_metrics = _behavior_metrics(test_eligible, autonomous["row_predictions"])
            window_metrics.append({"window": window.name, "model": name, "track": "STRICT_AUTONOMOUS", "split": "TEST", "state_source": autonomous["state_source"], **auto_metrics})
            if name == "v46":
                for profile, fee_mult, slip in (("BASE", 1.0, 1.0), ("STRESS", 1.5, 2.0)):
                    replay = _replay_portfolio(autonomous["merged_events"], bars, start=window.test_start, end=window.test_end, fee_rate=0.0005 * fee_mult, slippage_ticks=slip)
                    cost_metrics.append({"window": window.name, "model": "v46", "track": "STRICT_AUTONOMOUS", "cost_profile": profile, **{key: value for key, value in replay.items() if key != "per_symbol"}, "fit_rows": fit_meta["fit_rows"], "selected_threshold": fit_meta["threshold_calibration"].get("selected_threshold")})
                    for venue in ("BITMEX", "HYPERLIQUID"):
                        venue_events = [event for event in autonomous["merged_events"] if str(event.get("venue_symbol", "")).upper().startswith(f"{venue}:")]
                        venue_replay = _replay_portfolio(venue_events, bars, start=window.test_start, end=window.test_end, fee_rate=0.0005 * fee_mult, slippage_ticks=slip)
                        venue_metrics.append({"window": window.name, "model": "v46", "track": "STRICT_AUTONOMOUS", "venue": venue, "cost_profile": profile, "test_rows": len([row for row in test_eligible if str(row.get("source_venue") or "").upper() == venue]), **{key: value for key, value in venue_replay.items() if key != "per_symbol"}})
        active_keys = sorted({state_key(row) for row in test_eligible})
        hold_events = [{"venue_symbol": key, "decision_time": window.test_start, "target_exposure": 1.0, "action": "BUY_HOLD", "confidence": 1.0} for key in active_keys]
        hold = _replay_portfolio(hold_events, bars, start=window.test_start, end=window.test_end)
        none = _replay_portfolio([], bars, start=window.test_start, end=window.test_end)
        for name, replay in (("EQUAL_WEIGHT_LONG", hold), ("NO_TRADE", none)):
            cost_metrics.append({"window": window.name, "model": name, "track": "STRICT_AUTONOMOUS", "cost_profile": "BASE", **{key: value for key, value in replay.items() if key != "per_symbol"}})
    leakage = _audit_leakage(rows)
    protected = _protected_hash_audit()
    gates, all_pass = _gate_rows(window_metrics, cost_metrics, coverage, leakage, protected)
    status = "CANDIDATE_ELIGIBLE_FOR_HUMAN_REVIEW" if all_pass else "CANDIDATE_NOT_PROMOTED"
    result = {
        "report_version": "M16-UNIFIED-DISTILLATION-AUDIT-1.0",
        "status": status,
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "model_version": bundle.model_version,
        "feature_contract_version": bundle.feature_contract_version,
        "artifact": str(artifact_path.relative_to(ROOT)),
        "artifact_model_sha256": bundle.model_sha256,
        "training_data_sha256": bundle.training_data_sha256,
        "dataset_sha256": _sha256(dataset_path),
        "frozen_cutoff": bundle.frozen_cutoff,
        "data_sources": {"bitmex": "frozen cross-venue dataset", "hyperliquid": "pinned public snapshot", "source_venue_model_feature": False},
        "coverage": coverage,
        "window_metrics": window_metrics,
        "venue_metrics": venue_metrics,
        "cost_metrics": cost_metrics,
        "promotion_gates": gates,
        "promotion_allowed": all_pass,
        "rollout_authorized": False,
        "active_demo_model_changed": False,
        "online_training": False,
        "missing_context": ["historical pre-action L2/order-book context is unavailable", "Hyperliquid coverage is recent and must pass each independent window"],
        "next_action": "Keep current v3 Demo model; do not switch or add Demo orders unless every v4.6 gate passes and a human explicitly approves the rollout.",
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    _write_csv(BY_WINDOW, window_metrics)
    _write_csv(BY_VENUE, venue_metrics)
    _write_csv(COSTS, cost_metrics)
    lines = [
        "# Unified Distillation v4.6 Audit",
        "",
        f"- status: **{status}**",
        f"- model: `{bundle.model_version}`",
        f"- feature contract: `{bundle.feature_contract_version}`",
        f"- frozen cutoff: `{bundle.frozen_cutoff}`",
        f"- dataset SHA256: `{result['dataset_sha256']}`",
        f"- model SHA256: `{bundle.model_sha256}`",
        "- track 1: `CONDITIONAL_BEHAVIOR`",
        "- track 2: `STRICT_AUTONOMOUS_REPLAY` from zero state",
        "- source venue is used for balancing/reporting only, not as a learned signal",
        f"- candidate promotion gates: **{'PASS' if all_pass else 'FAIL'}**",
        "- rollout authorization: **no**",
        "- active v3 Demo model changed: **no**",
        "- Demo orders submitted by this audit: **no**",
        "",
        "## Coverage",
        "",
    ]
    for name, item in coverage.items():
        lines.append(f"- `{name}`: {item}")
    lines.extend(["", "## Promotion gates", ""])
    for gate in gates:
        lines.append(f"- `{gate['gate']}`: **{gate['status']}**")
    lines.extend(["", "## Interpretation", "", "This report evaluates a unified behavioral approximation. It does not recover private triggers, prove profitability, or authorize mainnet/live trading.", "", "## Outputs", "", f"- `{BY_WINDOW.relative_to(ROOT)}`", f"- `{BY_VENUE.relative_to(ROOT)}`", f"- `{COSTS.relative_to(ROOT)}`"])
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = build()
    print(json.dumps({"status": result["status"], "promotion_allowed": result["promotion_allowed"], "report": str(REPORT.relative_to(ROOT))}, ensure_ascii=False))
