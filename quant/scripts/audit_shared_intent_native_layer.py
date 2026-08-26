#!/usr/bin/env python3
"""Audit a venue-neutral intent model with venue-native exposure calibration.

This is a research-only candidate.  It asks a narrower, falsifiable question
than a single cross-venue model: can a shared action intent transfer between
venues when contract scale and exposure are calibrated separately on a
chronological training slice?  The final test slice is untouched by both the
shared fit and the venue calibration.  No active Demo artifact is replaced.
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
from typing import Any, Iterable, Mapping

import numpy as np

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
    _per_symbol_rows,
    _rates,
    _read_temporal,
    _replay_portfolio,
)
from quant_bot.strategy.base import StrategySignal  # noqa: E402
from quant_bot.strategy.feature_contract import strategy_input_from_row  # noqa: E402
from quant_bot.strategy.supervised_models import CrossAssetNumpyLogisticStrategy  # noqa: E402
from research.autonomous_replay import (  # noqa: E402
    AutonomousState,
    merge_same_time_signals,
    normalize_window_rows,
    override_dynamic_state,
    parse_time,
    roll_forward_predictions,
    state_key,
)


VERSION = "behavioral-distillation-v4.2-shared-intent-native-layer"
REPORT = ROOT / "quant" / "reports" / "shared_intent_native_layer_audit.json"
REPORT_MD = ROOT / "quant" / "reports" / "shared_intent_native_layer_audit.md"
PER_SYMBOL = ROOT / "quant" / "reports" / "shared_intent_native_layer_by_symbol.csv"
UTC = timezone.utc
IDLE_ACTIONS = frozenset({"NO_TRADE", "HOLD_LONG", "HOLD_SHORT"})


def intent_action(action: Any) -> str:
    """Collapse direction-specific actions into venue-neutral intent families."""

    value = str(action or "").upper()
    if not value or value in IDLE_ACTIONS:
        return "NO_TRADE"
    if "FLIP" in value:
        return "FLIP"
    if "OPEN" in value:
        return "OPEN"
    if "ADD" in value:
        return "ADD"
    if "REDUCE" in value or "CLOSE" in value:
        return "REDUCE"
    return "NO_TRADE"


def neutralize_for_shared_intent(row: Mapping[str, Any]) -> dict[str, Any]:
    """Remove venue contract/unit categories from the shared model inputs.

    Market returns, volatility, indicators, and normalized simulated state are
    retained.  Contract lot/multiplier, quote/settlement currency, payout
    model, mark/index basis, and funding are deliberately not allowed to
    create a fake universal execution rule.  Missingness remains explicit.
    """

    output = dict(row)
    output["label_next_action"] = intent_action(row.get("label_next_action"))
    canonical = str(row.get("canonical_asset") or row.get("feature_symbol") or "UNKNOWN")
    output["feature_symbol"] = canonical
    output["feature_payout_model"] = "VENUE_NEUTRAL"
    output["feature_quote_currency"] = "VENUE_NEUTRAL"
    output["feature_settlement_currency"] = "VENUE_NEUTRAL"
    output["feature_contract_lot_size"] = 1.0
    output["feature_multiplier_major"] = 1.0
    current = _number(row.get("feature_current_normalized_exposure"), 0.0) or 0.0
    output["feature_current_net_position_contracts"] = current
    output["feature_position_scale_contracts"] = 1.0
    output["feature_funding_rate"] = None
    output["feature_funding_rate_missing"] = True
    output["feature_mark_index_basis"] = None
    output["feature_mark_index_basis_missing"] = True
    output["feature_order_execution_style"] = "SHARED_INTENT"
    output["feature_ordering_confidence"] = "HIGH"
    output["feature_accounting_confidence"] = "HIGH"
    return output


def _number(value: Any, default: float | None = None) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if np.isfinite(result) else default


def chronological_three_way(rows: Iterable[Mapping[str, Any]], *, train_fraction: float = 0.60, calibration_fraction: float = 0.20) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Return train/calibration/untouched-test segments in time order."""

    ordered = sorted((dict(row) for row in rows), key=lambda row: str(row.get("decision_time")))
    if len(ordered) < 3:
        return ordered, [], []
    train_end = max(1, min(len(ordered) - 2, int(len(ordered) * train_fraction)))
    calibration_size = max(1, int(len(ordered) * calibration_fraction))
    calibration_end = min(len(ordered) - 1, train_end + calibration_size)
    if calibration_end <= train_end:
        calibration_end = train_end + 1
    return ordered[:train_end], ordered[train_end:calibration_end], ordered[calibration_end:]


def _eligible(rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
    return [
        neutralize_for_shared_intent(row)
        for row in rows
        if str(row.get("model_eligible")).lower() == "true"
        and str(row.get("label_status")) == "AVAILABLE"
        and row.get("label_next_action")
    ]


def _fit_shared(rows: list[dict[str, Any]]) -> CrossAssetNumpyLogisticStrategy:
    train = [dict(row, dataset_split="TRAIN") for row in rows if row.get("label_next_action")]
    if not train:
        raise ValueError("shared intent model requires labeled training rows")
    model = CrossAssetNumpyLogisticStrategy(
        target_l2=1.0,
        class_weighting="sqrt_balanced",
        enforce_action_target_consistency=True,
    ).fit(train)
    model.version = VERSION
    return model


def fit_native_exposure_layer(
    calibration_rows: list[dict[str, Any]],
    predictions: list[tuple[dict[str, Any], StrategySignal]],
) -> dict[str, Any]:
    """Fit one bounded affine target mapping from shared intent to native scale."""

    pairs: list[tuple[float, float]] = []
    predicted_ids = {str(row.get("decision_episode_id")): signal for row, signal in predictions}
    for row in calibration_rows:
        signal = predicted_ids.get(str(row.get("decision_episode_id")))
        actual = _number(row.get("label_next_target_exposure"))
        if signal is not None and actual is not None and np.isfinite(actual):
            pairs.append((float(signal.target_exposure), actual))
    if len(pairs) < 20:
        return {
            "status": "INSUFFICIENT_CALIBRATION",
            "rows": len(pairs),
            "intercept": 0.0,
            "slope": 1.0,
            "residual_mae": None,
        }
    x = np.asarray([item[0] for item in pairs], dtype=float)
    y = np.asarray([item[1] for item in pairs], dtype=float)
    design = np.column_stack([np.ones(len(x)), x])
    coefficients, *_ = np.linalg.lstsq(design, y, rcond=None)
    raw_intercept, raw_slope = float(coefficients[0]), float(coefficients[1])
    # A native execution layer may resize exposure, but it must not silently
    # reverse direction or become an unbounded second strategy.
    status = "PASS"
    if raw_slope < 0.0:
        status = "SIGN_INVERSION_BLOCKED"
    intercept = float(np.clip(raw_intercept, -0.25, 0.25))
    slope = float(np.clip(raw_slope, 0.0, 2.0))
    residual = y - np.clip(intercept + slope * x, -1.0, 1.0)
    return {
        "status": status,
        "rows": len(pairs),
        "intercept": intercept,
        "slope": slope,
        "raw_intercept": raw_intercept,
        "raw_slope": raw_slope,
        "residual_mae": float(np.mean(np.abs(residual))),
        "direction_reversal_blocked": raw_slope < 0.0,
    }


def apply_native_layer(signal: StrategySignal, layer: Mapping[str, Any]) -> StrategySignal:
    """Resize non-idle target exposure without changing shared intent."""

    if intent_action(signal.action) in IDLE_ACTIONS:
        return signal
    target = float(layer.get("intercept", 0.0)) + float(layer.get("slope", 1.0)) * float(signal.target_exposure)
    return replace(
        signal,
        target_exposure=float(np.clip(target, -1.0, 1.0)),
        risk_tags=tuple(dict.fromkeys((*signal.risk_tags, "VENUE_NATIVE_EXPOSURE_LAYER"))),
    )


def roll_forward_layered(
    model: CrossAssetNumpyLogisticStrategy,
    rows: Iterable[Mapping[str, Any]],
    scales: Mapping[str, float],
    layers: Mapping[str, Mapping[str, Any]],
    *,
    market_bar_opens: Mapping[str, list[datetime]] | None = None,
    fee_rate: float = 0.0005,
) -> dict[str, Any]:
    """Replay shared intent while applying the native layer before state update."""

    from bisect import bisect_right

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
            grouped[(state_key(row), when)].append(dict(row))
    row_predictions: list[tuple[dict[str, Any], StrategySignal]] = []
    merged_events: list[dict[str, Any]] = []
    for (key, when), group in grouped.items():
        state = states[key]
        while pending[key] and pending[key][0][0] <= when:
            execution_time, target, action = pending[key].pop(0)
            state.apply_execution(target, action, execution_time, fee_rate)
        scale = max(1.0, _number(scales.get(key), _number(group[0].get("feature_position_scale_contracts"), 1.0)) or 1.0)
        local: list[tuple[dict[str, Any], StrategySignal]] = []
        layer = layers.get(key) or layers.get(key.split(":", 1)[0]) or {"intercept": 0.0, "slope": 1.0}
        for row in group:
            overridden = override_dynamic_state(row, state, scale, when)
            signal = apply_native_layer(model.predict(strategy_input_from_row(overridden)), layer)
            local.append((row, signal))
            row_predictions.append((row, signal))
        merged = merge_same_time_signals(local, key=key, decision_time=when)
        if merged is None:
            continue
        merged_events.append(merged)
        opens = (market_bar_opens or {}).get(key, [])
        index = bisect_right(opens, when)
        execution_time = opens[index] if index < len(opens) else when + timedelta(hours=1)
        pending[key].append((execution_time, float(merged["target_exposure"]), str(merged["action"])))
    return {
        "row_predictions": row_predictions,
        "merged_events": merged_events,
        "state_source": "SIMULATED_ZERO_START",
        "teacher_state_fields_consumed": 0,
    }


def _causal_check(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    violations: defaultdict[str, int] = defaultdict(int)
    previous: dict[str, datetime] = {}
    for row in rows:
        decision = parse_time(row.get("decision_time"))
        if decision is None:
            violations["invalid_decision_time"] += 1
            continue
        key = state_key(row)
        latest = parse_time(row.get("feature_latest_bar_time"))
        funding = parse_time(row.get("feature_funding_source_time"))
        label_time = parse_time(row.get("label_next_decision_time"))
        if latest is not None and latest >= decision:
            violations["future_market_bar"] += 1
        if funding is not None and funding > decision:
            violations["future_funding"] += 1
        if key in previous and decision <= previous[key]:
            violations["non_strict_clock_order"] += 1
        if label_time is None or label_time <= decision:
            violations["non_future_label"] += 1
        previous[key] = decision
    checks = {
        "invalid_decision_time": violations["invalid_decision_time"],
        "future_market_bar": violations["future_market_bar"],
        "future_funding": violations["future_funding"],
        "non_strict_clock_order": violations["non_strict_clock_order"],
        "non_future_label": violations["non_future_label"],
    }
    return {"status": "PASS" if not any(checks.values()) else "BLOCKED", "checks": checks}


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


def _compact_performance(replay: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in replay.items() if key != "per_symbol"}


def build(*, dataset_path: Path = DATASET_TEMPORAL, report_path: Path = REPORT, markdown_path: Path = REPORT_MD, per_symbol_path: Path = PER_SYMBOL) -> dict[str, Any]:
    raw_rows = _read_temporal(dataset_path)
    causal = _causal_check(raw_rows)
    bars, opens = _load_bars()
    by_venue: dict[str, dict[str, list[dict[str, Any]]]] = {}
    all_train: list[dict[str, Any]] = []
    venue_meta: dict[str, dict[str, Any]] = {}
    for venue in sorted({str(row.get("source_venue") or "UNKNOWN") for row in raw_rows}):
        source_rows = [row for row in raw_rows if str(row.get("source_venue") or "UNKNOWN") == venue]
        train_raw, calibration_raw, test_raw = chronological_three_way(source_rows)
        train, scales = normalize_window_rows(train_raw, train_raw)
        calibration, _ = normalize_window_rows(calibration_raw, train_raw)
        test, _ = normalize_window_rows(test_raw, train_raw)
        parts = {"train": _eligible(train), "calibration": _eligible(calibration), "test": _eligible(test)}
        by_venue[venue] = parts
        all_train.extend(parts["train"])
        venue_meta[venue] = {
            "raw_rows": len(source_rows),
            "train_rows": len(parts["train"]),
            "calibration_rows": len(parts["calibration"]),
            "test_rows": len(parts["test"]),
            "scales": scales,
            "train_boundary": train_raw[-1].get("decision_time") if train_raw else None,
            "calibration_boundary": calibration_raw[-1].get("decision_time") if calibration_raw else None,
            "test_first_time": test_raw[0].get("decision_time") if test_raw else None,
            "test_last_time": test_raw[-1].get("decision_time") if test_raw else None,
        }
    if not all_train:
        raise ValueError("no eligible venue-native training rows")
    model = _fit_shared(all_train)
    results: list[dict[str, Any]] = []
    per_symbol: list[dict[str, Any]] = []
    for venue, parts in by_venue.items():
        train = parts["train"]
        calibration = parts["calibration"]
        test = parts["test"]
        if not calibration or not test:
            result = {"venue": venue, "status": "INSUFFICIENT_NATIVE_COVERAGE", **venue_meta[venue], "promotion_allowed": False}
            results.append(result)
            continue
        scales = venue_meta[venue]["scales"]
        calibration_base = roll_forward_predictions(model, calibration, scales, market_bar_opens=opens, include_state_overrides=False)
        layer = fit_native_exposure_layer(calibration, calibration_base["row_predictions"])
        base = roll_forward_predictions(model, test, scales, market_bar_opens=opens, include_state_overrides=False)
        layered = roll_forward_layered(model, test, scales, {venue: layer}, market_bar_opens=opens)
        first = parse_time(test[0].get("decision_time"))
        last = parse_time(test[-1].get("decision_time"))
        if first is None or last is None:
            raise ValueError(f"invalid test time for {venue}")
        last = last + timedelta(hours=1)
        base_replay = _replay_portfolio(base["merged_events"], bars, start=first, end=last, fee_rate=FEE_RATE)
        layered_replay = _replay_portfolio(layered["merged_events"], bars, start=first, end=last, fee_rate=FEE_RATE)
        behavior_base = {**_behavior_metrics(test, base["row_predictions"]), **_rates(test, base["row_predictions"])}
        behavior_layered = {**_behavior_metrics(test, layered["row_predictions"]), **_rates(test, layered["row_predictions"])}
        result = {
            "venue": venue,
            "status": "DIAGNOSTIC_ONLY",
            **venue_meta[venue],
            "shared_model_version": VERSION,
            "native_exposure_layer": layer,
            "shared_intent_base": {"behavior": behavior_base, "performance": _compact_performance(base_replay)},
            "shared_intent_native_layer": {"behavior": behavior_layered, "performance": _compact_performance(layered_replay)},
            "active_model_unchanged": True,
            "promotion_allowed": False,
        }
        results.append(result)
        details = _per_symbol_rows(test, layered["row_predictions"], layered_replay, f"SHARED_INTENT_NATIVE_{venue}")
        per_symbol.extend(details)
    output = {
        "report_version": "M15-SHARED-INTENT-NATIVE-LAYER-1.0",
        "status": "DIAGNOSTIC_ONLY",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "candidate_model_version": VERSION,
        "dataset": str(dataset_path.relative_to(ROOT)),
        "dataset_rows": len(raw_rows),
        "shared_model_train_rows": len(all_train),
        "shared_input_boundary": "venue-specific contract/unit categories removed; normalized state and common market features retained",
        "split_contract": "per venue chronological 60% train, 20% calibration, 20% untouched test; no random split",
        "causal_audit": causal,
        "venue_results": results,
        "raw_inputs_untouched": True,
        "active_demo_unchanged": True,
        "promotion_allowed": False,
        "conclusion": "The layered audit separates common action intent from venue-native exposure scaling. It is diagnostic evidence only and cannot prove exact strategy recovery or authorize a Demo model switch.",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    _write_csv(per_symbol_path, per_symbol)
    lines = [
        "# Shared Intent / Venue-Native Layer Audit",
        "",
        "> Diagnostic only. One venue-neutral intent model is fitted on the first 60%; exposure layers use the next 20%; the final 20% is untouched.",
        "",
        "| venue | train | calibration | untouched test | base net return | layered net return | base actions | layered actions |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        base = result.get("shared_intent_base", {})
        layered = result.get("shared_intent_native_layer", {})
        base_behavior = base.get("behavior", {})
        layered_behavior = layered.get("behavior", {})
        base_perf = base.get("performance", {})
        layered_perf = layered.get("performance", {})
        base_rate = 1.0 - float(base_behavior.get("predicted_no_trade_rate", 1.0))
        layered_rate = 1.0 - float(layered_behavior.get("predicted_no_trade_rate", 1.0))
        fmt = lambda value: "—" if value is None else f"{float(value):.6f}"
        lines.append(
            f"| `{result['venue']}` | {result.get('train_rows', 0)} | {result.get('calibration_rows', 0)} | {result.get('test_rows', 0)} | {fmt(base_perf.get('net_return'))} | {fmt(layered_perf.get('net_return'))} | {base_rate:.2%} | {layered_rate:.2%} |"
        )
    lines += [
        "",
        "## Interpretation",
        "",
        "A useful result would preserve intent while making the venue-native layer explainable and stable on the untouched slice. A positive return is not a profitability guarantee; a negative result does not prove the trader changed strategy.",
        "",
        "## Boundary",
        "",
        "No credentials, private endpoint, mainnet connection, or order was used. The active Demo model remains unchanged and raw CSV/JSON inputs remain read-only.",
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
        print(json.dumps({"status": "BLOCKED", "error_code": "SHARED_INTENT_NATIVE_LAYER_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": result["status"], "report": str(REPORT), "venues": [item["venue"] for item in result["venue_results"]]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
