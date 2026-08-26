#!/usr/bin/env python3
"""Run cross-venue indicator and strict-autonomous walk-forward research."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cross_asset.hyperliquid import load_candle_archive, load_funding  # noqa: E402
from quant_bot.strategy.base import StrategySignal  # noqa: E402
from quant_bot.strategy.feature_contract import strategy_input_from_row  # noqa: E402
from quant_bot.strategy.supervised_models import CrossAssetNumpyLogisticStrategy  # noqa: E402
from research.autonomous_replay import (  # noqa: E402
    normalize_window_rows,
    roll_forward_predictions,
    state_key,
)

from audit_strategy_effectiveness import (  # noqa: E402
    FEE_RATE,
    FROZEN_CUTOFF,
    MarketBar,
    _audit_leakage,
    _canonical_tick_sizes,
    _macro_f1,
    _number,
    _protected_hash_audit,
    _read_csv,
    _correlation,
    action_family,
    load_market_context,
    replay_next_bar,
)


UTC = timezone.utc
V2_VERSION = "behavioral-distillation-v2-cross-asset-logistic"
V3_VERSION = "behavioral-distillation-v3-cross-asset-indicators"
V3_CROSS_VENUE_VERSION = "behavioral-distillation-v3-cross-venue-indicators"
DATASET_V2 = ROOT / "quant" / "outputs" / "cross_venue_model_dataset_v2.csv"
DATASET_V3 = ROOT / "quant" / "outputs" / "cross_venue_model_dataset_v3.csv"
BITMEX_MARKET = ROOT / "quant" / "outputs" / "cross_asset_market_context.csv"
HL_SOURCE = ROOT / "quant" / "data" / "external" / "hyperliquid" / "paul"
REPORTS = ROOT / "quant" / "reports"


@dataclass(frozen=True)
class Window:
    name: str
    train_end: datetime
    validation_end: datetime
    test_end: datetime

    @property
    def validation_start(self) -> datetime:
        return self.train_end

    @property
    def test_start(self) -> datetime:
        return self.validation_end


WINDOWS = (
    Window("WF1", datetime(2023, 1, 1, tzinfo=UTC), datetime(2024, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC)),
    Window("WF2", datetime(2024, 1, 1, tzinfo=UTC), datetime(2025, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC)),
    Window("WF3", datetime(2025, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC), FROZEN_CUTOFF),
)


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


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_dataset(path: Path) -> list[dict[str, Any]]:
    return [row for row in _read_csv(path) if str(row.get("model_eligible", "")).lower() == "true" and (_parse_time(row.get("decision_time")) or datetime.max.replace(tzinfo=UTC)) <= FROZEN_CUTOFF]


def _window_rows(rows: Iterable[Mapping[str, Any]], start: datetime | None, end: datetime) -> list[dict[str, Any]]:
    output = []
    for row in rows:
        when = _parse_time(row.get("decision_time"))
        if when is not None and when < end and (start is None or when >= start):
            output.append(dict(row))
    return output


def _bar_key_for_bitmex(symbol: str) -> str:
    if symbol in {"XBTUSD", "XBTM21", "XBTU21"}:
        return "BITMEX:BTC-PERP"
    return f"BITMEX:{symbol}"


def _load_hyperliquid_bars(source_dir: Path) -> tuple[dict[str, list[MarketBar]], dict[str, list[datetime]]]:
    bars = load_candle_archive(source_dir / "candles_1h.json")
    funding = load_funding(source_dir / "userFunding.json", cutoff=FROZEN_CUTOFF)
    funding_by_time: dict[datetime, float] = {}
    for row in funding:
        try:
            when = datetime.fromtimestamp(int(row.get("time", 0)) / 1000, tz=UTC)
            rate = float((row.get("delta") or {}).get("fundingRate"))
        except (TypeError, ValueError):
            continue
        funding_by_time[when] = rate
    result: list[MarketBar] = []
    for bar in bars:
        if bar.open_time > FROZEN_CUTOFF:
            continue
        funding_time = next((timestamp for timestamp in funding_by_time if timestamp == bar.open_time), None)
        result.append(MarketBar(bar.open_time, bar.open, bar.close, funding_by_time.get(funding_time) if funding_time else None, funding_time))
    result.sort(key=lambda item: item.timestamp)
    return {"HYPERLIQUID:BTC-PERP": result}, {"HYPERLIQUID:BTC-PERP": [bar.timestamp for bar in result]}


def _load_bars(source_dir: Path | None = None) -> tuple[dict[str, list[MarketBar]], dict[str, list[datetime]]]:
    output: dict[str, list[MarketBar]] = {}
    source = load_market_context(BITMEX_MARKET)
    for symbol, bars in source.items():
        output[_bar_key_for_bitmex(symbol)] = bars
    if source_dir is None:
        source_dirs = sorted(item for item in HL_SOURCE.iterdir() if item.is_dir()) if HL_SOURCE.exists() else []
        source_dir = source_dirs[-1] if source_dirs else None
    if source_dir is not None:
        hl_bars, _ = _load_hyperliquid_bars(source_dir)
        output.update(hl_bars)
    opens = {key: [bar.timestamp for bar in values] for key, values in output.items()}
    return output, opens


def _fit(rows: list[dict[str, Any]], version: str) -> CrossAssetNumpyLogisticStrategy:
    model = CrossAssetNumpyLogisticStrategy()
    model.version = version
    train = [dict(row, dataset_split="TRAIN") for row in rows if str(row.get("label_status")) == "AVAILABLE"]
    model.fit(train)
    model.version = version
    return model


def _conditional_predictions(model: CrossAssetNumpyLogisticStrategy, rows: Iterable[Mapping[str, Any]]) -> list[tuple[dict[str, Any], StrategySignal]]:
    output: list[tuple[dict[str, Any], StrategySignal]] = []
    for original in rows:
        row = dict(original)
        try:
            output.append((row, model.predict(strategy_input_from_row(row))))
        except (KeyError, TypeError, ValueError):
            continue
    return output


def _behavior_metrics(rows: Iterable[Mapping[str, Any]], predictions: Iterable[tuple[Mapping[str, Any], StrategySignal]]) -> dict[str, Any]:
    by_id = {str(row.get("decision_episode_id")): (row, signal) for row, signal in predictions}
    labeled = [(row, by_id[str(row.get("decision_episode_id"))][1]) for row in rows if str(row.get("decision_episode_id")) in by_id and row.get("label_status") == "AVAILABLE" and row.get("label_next_action")]
    labels = [str(row.get("label_next_action")) for row, _ in labeled]
    predicted = [str(signal.action) for _, signal in labeled]
    actual_targets = [_number(row.get("label_next_target_exposure")) for row, _ in labeled]
    predicted_targets = [float(signal.target_exposure) for _, signal in labeled]
    pairs = [(actual, predicted) for actual, predicted in zip(actual_targets, predicted_targets) if actual is not None]
    recalls: dict[str, float | None] = {}
    for family in ("OPEN", "CLOSE", "ADD", "REDUCE", "FLIP"):
        relevant = [(actual, guess) for actual, guess in zip(labels, predicted) if action_family(actual) == family]
        recalls[f"{family.lower()}_recall"] = sum(action_family(guess) == family for _, guess in relevant) / len(relevant) if relevant else None
    return {
        "rows_seen": len(list(rows)) if not isinstance(rows, list) else len(rows),
        "labeled_rows": len(labeled),
        "action_macro_f1": _macro_f1(labels, predicted),
        "target_exposure_mae": sum(abs(actual - guess) for actual, guess in pairs) / len(pairs) if pairs else None,
        "target_exposure_correlation": _correlation([item[0] for item in pairs], [item[1] for item in pairs]),
        **recalls,
    }


def _events(predictions: Iterable[Mapping[str, Any] | tuple[Mapping[str, Any], StrategySignal]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in predictions:
        if isinstance(item, tuple):
            row, signal = item
            output.append({"venue_symbol": state_key(row), "decision_time": _parse_time(row.get("decision_time")), "target_exposure": float(signal.target_exposure), "action": str(signal.action), "confidence": float(signal.confidence)})
        else:
            output.append(dict(item))
    return [row for row in output if row.get("decision_time") is not None]


def _replay_portfolio(events: Iterable[Mapping[str, Any]], bars_by_key: Mapping[str, list[MarketBar]], *, start: datetime, end: datetime, fee_rate: float = FEE_RATE, slippage_ticks: float = 1.0) -> dict[str, Any]:
    grouped: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[str(event.get("venue_symbol"))].append(event)
    per_symbol: dict[str, dict[str, Any]] = {}
    for key, rows in grouped.items():
        bars = bars_by_key.get(key)
        if not bars:
            continue
        item = replay_next_bar(bars, rows, start_time=start, end_time=end, fee_rate=fee_rate, tick_size=0.1, slippage_ticks=slippage_ticks)
        per_symbol[key] = item
    if not per_symbol:
        return {"status": "NO_TEST_DATA", "active_symbols": 0, "per_symbol": {}, "net_return": None, "profit_factor": None, "executed_adjustments": 0}
    returns = [float(item["net_return"]) for item in per_symbol.values() if item.get("net_return") is not None]
    gains = sum(float(item.get("gross_profit") or 0.0) for item in per_symbol.values())
    losses = sum(float(item.get("gross_loss") or 0.0) for item in per_symbol.values())
    return {
        "status": "PASS",
        "active_symbols": len(per_symbol),
        "per_symbol": per_symbol,
        "net_return": sum(returns) / len(returns) if returns else None,
        "gross_profit": gains,
        "gross_loss": losses,
        "profit_factor": gains / losses if losses else None,
        "fees": sum(float(item.get("fees") or 0.0) for item in per_symbol.values()),
        "funding": sum(float(item.get("funding") or 0.0) for item in per_symbol.values()),
        "slippage": sum(float(item.get("slippage") or 0.0) for item in per_symbol.values()),
        "turnover": sum(float(item.get("turnover") or 0.0) for item in per_symbol.values()),
        "executed_adjustments": sum(int(item.get("executed_adjustments") or 0) for item in per_symbol.values()),
        "signal_count": sum(int(item.get("signal_count") or 0) for item in per_symbol.values()),
        "funding_events_observed": sum(int(item.get("funding_events_observed") or 0) for item in per_symbol.values()),
        "funding_events_missing": sum(int(item.get("funding_events_missing") or 0) for item in per_symbol.values()),
    }


def _coverage(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    rows = list(rows)
    status = Counter(str(row.get("row_market_coverage_status", "UNKNOWN")) for row in rows)
    indicators = ("feature_rsi_14", "feature_macd_histogram", "feature_bollinger_percent_b_20", "feature_volume_percentile_72bar")
    missing = {key: sum(_number(row.get(key)) is None for row in rows) for key in indicators}
    return {"row_status_counts": dict(status), "indicator_missing_counts": missing}


def _gates(behavior: list[dict[str, Any]], performance: list[dict[str, Any]], leakage: dict[str, Any], protected: dict[str, Any]) -> dict[str, Any]:
    details: list[dict[str, Any]] = []
    details.append({"gate": "time_leakage_zero", "status": "PASS" if leakage.get("status") == "PASS" else "FAIL", "checks": leakage.get("checks", {})})
    details.append({"gate": "protected_raw_hashes_unchanged", "status": "PASS" if protected.get("status") == "PASS" else "FAIL"})
    for window in ("WF1", "WF2", "WF3"):
        available = [row for row in behavior if row.get("window") == window and row.get("track") == "STRICT_AUTONOMOUS" and row.get("split") == "TEST" and row.get("labeled_rows", 0)]
        details.append({"gate": f"autonomous_test_{window}_available", "status": "PASS" if available else "FAIL", "available": bool(available)})
    v2 = {(row.get("window"), row.get("split")): row for row in behavior if row.get("model") == "v2"}
    v3 = {(row.get("window"), row.get("split")): row for row in behavior if row.get("model") == "v3"}
    comparisons = []
    for window in ("WF1", "WF2", "WF3"):
        left, right = v2.get((window, "TEST"), {}), v3.get((window, "TEST"), {})
        if left.get("action_macro_f1") is not None and right.get("action_macro_f1") is not None and left.get("target_exposure_mae") is not None and right.get("target_exposure_mae") is not None:
            comparisons.append((window, left, right))
    v3_not_worse = bool(comparisons) and all(item[2]["action_macro_f1"] >= item[1]["action_macro_f1"] - 0.02 and item[2]["target_exposure_mae"] <= item[1]["target_exposure_mae"] + 0.01 for item in comparisons)
    details.append({"gate": "v3_vs_v2_behavior_thresholds", "status": "PASS" if v3_not_worse else "FAIL", "compared_windows": len(comparisons)})
    base = {(row.get("window")): row for row in performance if row.get("model") == "v3" and row.get("track") == "STRICT_AUTONOMOUS" and row.get("cost_profile") == "BASE"}
    hold = {(row.get("window")): row for row in performance if row.get("model") == "EQUAL_WEIGHT_LONG" and row.get("track") == "STRICT_AUTONOMOUS"}
    available_base = [base.get(window) for window in ("WF1", "WF2", "WF3")]
    positive_all = all(item and item.get("net_return") is not None and item["net_return"] > 0 for item in available_base)
    pf_all = all(item and item.get("profit_factor") is not None and item["profit_factor"] > 1 for item in available_base)
    beat_hold = all(base[window].get("net_return") is not None and hold.get(window, {}).get("net_return") is not None and base[window]["net_return"] > hold[window]["net_return"] for window in base if window in hold) if hold else False
    details.extend([
        {"gate": "autonomous_positive_all_windows", "status": "PASS" if positive_all else "FAIL"},
        {"gate": "autonomous_profit_factor_gt_one", "status": "PASS" if pf_all else "FAIL"},
        {"gate": "autonomous_beats_equal_weight_hold", "status": "PASS" if beat_hold else "FAIL"},
    ])
    passed = all(item["status"] == "PASS" for item in details)
    return {"all_gates_pass": passed, "details": details, "behavior_gates_pass": v3_not_worse, "autonomous_net_gates_pass": positive_all and pf_all and beat_hold}


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


def build(dataset_v2: Path = DATASET_V2, dataset_v3: Path = DATASET_V3, source_dir: Path | None = None) -> dict[str, Any]:
    source_dirs = sorted(item for item in HL_SOURCE.iterdir() if item.is_dir()) if HL_SOURCE.exists() else []
    source_dir = source_dir or (source_dirs[-1] if source_dirs else None)
    if source_dir is None or not source_dir.exists():
        raise FileNotFoundError("pinned Hyperliquid source snapshot is required for cross-venue audit")
    v2_rows = _read_dataset(dataset_v2)
    v3_rows = _read_dataset(dataset_v3)
    all_rows = v3_rows
    leakage = _audit_leakage(all_rows)
    protected = _protected_hash_audit()
    bars_by_key, bar_opens = _load_bars(source_dir)
    behavior: list[dict[str, Any]] = []
    performance: list[dict[str, Any]] = []
    symbol_metrics: list[dict[str, Any]] = []
    window_summaries: list[dict[str, Any]] = []
    for window in WINDOWS:
        for model_name, raw_rows, version in (("v2", v2_rows, V2_VERSION), ("v3", v3_rows, V3_CROSS_VENUE_VERSION)):
            train_raw = _window_rows(raw_rows, None, window.train_end)
            val_raw = _window_rows(raw_rows, window.validation_start, window.validation_end)
            test_raw = _window_rows(raw_rows, window.test_start, window.test_end)
            train_rows, scales = normalize_window_rows(train_raw, train_raw)
            val_rows, _ = normalize_window_rows(val_raw, train_raw)
            test_rows, _ = normalize_window_rows(test_raw, train_raw)
            train_eligible = [row for row in train_rows if str(row.get("model_eligible")).lower() == "true"]
            val_eligible = [row for row in val_rows if str(row.get("model_eligible")).lower() == "true"]
            test_eligible = [row for row in test_rows if str(row.get("model_eligible")).lower() == "true"]
            if not train_eligible:
                continue
            model = _fit(train_eligible, version)
            for track, split, rows in (("CONDITIONAL_BEHAVIOR", "VALIDATION", val_eligible), ("CONDITIONAL_BEHAVIOR", "TEST", test_eligible)):
                predictions = _conditional_predictions(model, rows)
                metrics = _behavior_metrics(rows, predictions)
                behavior.append({"window": window.name, "model": model_name, "track": track, "split": split, "start": (window.validation_start if split == "VALIDATION" else window.test_start).isoformat(), "end": (window.validation_end if split == "VALIDATION" else window.test_end).isoformat(), **metrics})
            autonomous = roll_forward_predictions(model, test_eligible, scales, market_bar_opens=bar_opens)
            auto_metrics = _behavior_metrics(test_eligible, autonomous["row_predictions"])
            behavior.append({"window": window.name, "model": model_name, "track": "STRICT_AUTONOMOUS", "split": "TEST", "start": window.test_start.isoformat(), "end": window.test_end.isoformat(), "state_source": autonomous["state_source"], "teacher_state_fields_consumed": autonomous["teacher_state_fields_consumed"], **auto_metrics})
            for symbol in sorted({str(row.get("symbol")) for row in test_eligible}):
                subset = [row for row in test_eligible if str(row.get("symbol")) == symbol]
                subset_predictions = [(row, signal) for row, signal in autonomous["row_predictions"] if str(row.get("symbol")) == symbol]
                symbol_metrics.append({"window": window.name, "model": model_name, "track": "STRICT_AUTONOMOUS", "symbol": symbol, "source_venue": subset[0].get("source_venue", ""), **_behavior_metrics(subset, subset_predictions)})
            for profile, fee_mult, slip in (("BASE", 1.0, 1.0), ("STRESS", 1.5, 2.0)):
                replay = _replay_portfolio(autonomous["merged_events"], bars_by_key, start=window.test_start, end=window.test_end, fee_rate=FEE_RATE * fee_mult, slippage_ticks=slip)
                performance.append({"window": window.name, "model": model_name, "track": "STRICT_AUTONOMOUS", "cost_profile": profile, "test_rows": len(test_eligible), "test_start": window.test_start.isoformat(), "test_end": window.test_end.isoformat(), **{key: value for key, value in replay.items() if key != "per_symbol"}})
        auto_v3 = next((row for row in behavior if row["window"] == window.name and row["model"] == "v3" and row["track"] == "STRICT_AUTONOMOUS"), None)
        test_count = len(_window_rows(v3_rows, window.test_start, window.test_end))
        window_summaries.append({"window": window.name, "train_rows": len(_window_rows(v3_rows, None, window.train_end)), "validation_rows": len(_window_rows(v3_rows, window.validation_start, window.validation_end)), "test_rows": test_count, "autonomous_metrics_available": bool(auto_v3), "status": "TEST_DATA_AVAILABLE" if test_count else "NO_TEST_DATA"})
        v3_train = [row for row in _window_rows(v3_rows, None, window.train_end) if str(row.get("model_eligible")) == "True"]
        test_rows = [row for row in _window_rows(v3_rows, window.test_start, window.test_end) if str(row.get("model_eligible")) == "True"]
        if v3_train and test_rows:
            # Baselines use the same autonomous active key set and next-bar convention.
            active_keys = sorted({state_key(row) for row in test_rows})
            hold_events = [{"venue_symbol": key, "decision_time": window.test_start - timedelta(microseconds=1), "target_exposure": 1.0, "action": "BUY_HOLD", "confidence": 1.0} for key in active_keys]
            hold = _replay_portfolio(hold_events, bars_by_key, start=window.test_start, end=window.test_end)
            none = _replay_portfolio([], bars_by_key, start=window.test_start, end=window.test_end)
            for name, value in (("EQUAL_WEIGHT_LONG", hold), ("NO_TRADE", none)):
                performance.append({"window": window.name, "model": name, "track": "STRICT_AUTONOMOUS", "cost_profile": "BASE", "test_rows": len(test_rows), "test_start": window.test_start.isoformat(), "test_end": window.test_end.isoformat(), **{key: item for key, item in value.items() if key != "per_symbol"}})
    gates = _gates(behavior, performance, leakage, protected)
    status = "DEMO_CANDIDATE_LIVE_REVIEW_REQUIRED" if gates["all_gates_pass"] else "DEMO_CONTINUE_LIVE_BLOCKED"
    coverage = _coverage(all_rows)
    result = {
        "report_version": "M15-CROSS-VENUE-INDICATOR-AUTONOMOUS-1.0",
        "analysis_commit": _git_head(),
        "status": status,
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "live_trading_allowed": False,
        "demo_model_auto_switch": False,
        "data_sources": {
            "bitmex_dataset": str(dataset_v3.relative_to(ROOT)),
            "hyperliquid_source": str(source_dir.relative_to(ROOT)) if source_dir else None,
            "hyperliquid_source_role": "USER_CONFIRMED_SAME_TEACHER_CROSS_VENUE_RESEARCH",
        },
        "dataset": {"v2_rows": len(v2_rows), "v3_rows": len(v3_rows), "eligible_v3_rows": sum(str(row.get("model_eligible")).lower() == "true" for row in v3_rows), "source_counts": dict(Counter(str(row.get("source_venue")) for row in all_rows)), "frozen_cutoff": FROZEN_CUTOFF.isoformat()},
        "coverage": coverage,
        "model_versions": {"baseline_v2": V2_VERSION, "baseline_v3": V3_VERSION, "candidate": V3_CROSS_VENUE_VERSION},
        "candidate_model_manifest": {
            "model_version": V3_CROSS_VENUE_VERSION,
            "feature_contract_version": "m13-v3-cross-asset-indicators",
            "fit_policy": "per-window TRAIN-only deterministic NumPy logistic; no online training",
            "training_data_sha256": _sha256(dataset_v3),
            "artifact_status": "NOT_PROMOTED_AUTONOMOUS_GATES_FAILED",
            "artifact_path": None,
        },
        "walk_forward_windows": window_summaries,
        "behavior_results": behavior,
        "per_symbol_results": symbol_metrics,
        "performance_results": performance,
        "leakage_audit": leakage,
        "protected_input_hash_audit": protected,
        "autonomous_replay_policy": {"start_position": "ZERO", "state_source": "SIMULATED", "execution": "STRICT_NEXT_BAR_OPEN", "teacher_state_fields_consumed": 0, "same_time_aliases": "CONFIDENCE_WEIGHTED_NET_TARGET"},
        "indicator_policy": "RSI14, MACD 12/26/9, Bollinger 20/2, volume percentile 72 and existing causal market features; missing values remain explicit.",
        "gate_evaluation": gates,
        "next_action": "Keep current Demo model. Review the cross-venue autonomous report; no candidate promotion or new orders are authorized by this audit.",
    }
    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "cross_venue_indicator_model_manifest.json").write_text(json.dumps(result["candidate_model_manifest"], indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (REPORTS / "cross_venue_indicator_autonomous_audit.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    _write_csv(REPORTS / "cross_venue_indicator_by_window.csv", behavior)
    _write_csv(REPORTS / "cross_venue_indicator_by_symbol.csv", symbol_metrics)
    _write_csv(REPORTS / "cross_venue_indicator_cost_sensitivity.csv", performance)
    lines = [
        "# Cross-Venue Indicator and Autonomous Replay Audit", "", f"- 状态：**{status}**", "- 策略保真度：`BEHAVIORAL_APPROXIMATION`", "- 本次不连接私有 API、不提交订单、不切换 Demo 模型。", "", "## 数据与覆盖", "", f"- BitMEX 行：`{len(v3_rows) - sum(str(row.get('source_venue')) == 'HYPERLIQUID' for row in v3_rows)}`；Hyperliquid 行：`{sum(str(row.get('source_venue')) == 'HYPERLIQUID' for row in v3_rows)}`", f"- v3 可用行：`{result['dataset']['eligible_v3_rows']}`", f"- 行级覆盖：`{coverage['row_status_counts']}`", f"- 指标缺失：`{coverage['indicator_missing_counts']}`", "", "## Walk-forward", "", "|窗口|训练行|验证行|测试行|自主轨道|", "|---|---:|---:|---:|---|",
    ]
    for item in window_summaries:
        lines.append(f"|{item['window']}|{item['train_rows']}|{item['validation_rows']}|{item['test_rows']}|{'可用' if item['autonomous_metrics_available'] else '不可用'}|")
    lines += ["", "## 严格自主状态证明", "", "- 起始仓位：`ZERO`。", "- 动态账户字段全部由模拟状态覆盖。", "- `teacher_state_fields_consumed = 0`。", "- 同一交易所/标准资产同一时刻只保留一个合并目标。", "", "## 指标增强行为结果", "", "|窗口|v2 F1|v3 F1|v2 MAE|v3 MAE|v3自主 F1|v3自主 MAE|", "|---|---:|---:|---:|---:|---:|---:|"]
    for window in ("WF1", "WF2", "WF3"):
        find = lambda model, track: next((row for row in behavior if row.get("window") == window and row.get("model") == model and row.get("track") == track and row.get("split") == "TEST"), {})
        v2 = find("v2", "CONDITIONAL_BEHAVIOR")
        v3 = find("v3", "CONDITIONAL_BEHAVIOR")
        auto = find("v3", "STRICT_AUTONOMOUS")
        fmt = lambda value: "—" if value is None else f"{float(value):.6f}"
        lines.append(f"|{window}|{fmt(v2.get('action_macro_f1'))}|{fmt(v3.get('action_macro_f1'))}|{fmt(v2.get('target_exposure_mae'))}|{fmt(v3.get('target_exposure_mae'))}|{fmt(auto.get('action_macro_f1'))}|{fmt(auto.get('target_exposure_mae'))}|")
    lines += ["", "## 自主成本回放", "", "|窗口|v3 基础净收益|v3 PF|压力净收益|不交易|等权持有|", "|---|---:|---:|---:|---:|---:|"]
    for window in ("WF1", "WF2", "WF3"):
        base = next((row for row in performance if row.get("window") == window and row.get("model") == "v3" and row.get("cost_profile") == "BASE"), {})
        stress = next((row for row in performance if row.get("window") == window and row.get("model") == "v3" and row.get("cost_profile") == "STRESS"), {})
        no_trade = next((row for row in performance if row.get("window") == window and row.get("model") == "NO_TRADE"), {})
        hold = next((row for row in performance if row.get("window") == window and row.get("model") == "EQUAL_WEIGHT_LONG"), {})
        fmt = lambda value: "—" if value is None else f"{float(value):.6f}"
        lines.append(f"|{window}|{fmt(base.get('net_return'))}|{fmt(base.get('profit_factor'))}|{fmt(stress.get('net_return'))}|{fmt(no_trade.get('net_return'))}|{fmt(hold.get('net_return'))}|")
    lines += ["", "## 门槛", ""]
    for item in gates["details"]:
        lines.append(f"- `{item['gate']}`：**{item['status']}**")
    lines += ["", "## 解释边界", "", "该报告检验的是跨交易所行为近似和自主回放，不是原交易员私有意图恢复，也不是账户真实收益预测。Hyperliquid 数据作为用户确认的同一老师来源纳入研究，但仍保留独立 venue/source/revision 字段。", "", "## 产物", "", "- `cross_venue_indicator_autonomous_audit.json`", "- `cross_venue_indicator_model_manifest.json`", "- `cross_venue_indicator_by_window.csv`", "- `cross_venue_indicator_by_symbol.csv`", "- `cross_venue_indicator_cost_sensitivity.csv"]
    (REPORTS / "cross_venue_indicator_autonomous_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-v2", type=Path, default=DATASET_V2)
    parser.add_argument("--dataset-v3", type=Path, default=DATASET_V3)
    parser.add_argument("--source-dir", type=Path)
    args = parser.parse_args()
    try:
        result = build(args.dataset_v2.resolve(), args.dataset_v3.resolve(), args.source_dir.resolve() if args.source_dir else None)
    except (FileNotFoundError, OSError, ValueError, KeyError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "CROSS_VENUE_AUDIT_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": result["status"], "all_gates_pass": result["gate_evaluation"]["all_gates_pass"], "report": "quant/reports/cross_venue_indicator_autonomous_audit.md"}, ensure_ascii=False))
    return 0 if result["gate_evaluation"]["all_gates_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
