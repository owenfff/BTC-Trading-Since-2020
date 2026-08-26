#!/usr/bin/env python3
"""Audit strategy behaviour and costed out-of-time replay.

This module is intentionally offline.  It consumes the frozen cross-asset
dataset and the public hourly market-context artifact, fits models on the
training side of each calendar window, and evaluates only the later test
side.  The replay is a *normalised exposure-return proxy*: instrument terms
are audited and used for eligibility, but the result is not wallet PnL.

No exchange client, API credential, order submission, or live process is used.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import subprocess
import sys
from bisect import bisect_right
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_bot.strategy.base import StrategySignal  # noqa: E402
from quant_bot.strategy.feature_contract import FEATURE_COLUMNS, parse_float  # noqa: E402
from quant_bot.strategy.supervised_models import CrossAssetNumpyLogisticStrategy  # noqa: E402


UTC = timezone.utc
FROZEN_CUTOFF = datetime(2026, 7, 18, 21, 17, 31, 514000, tzinfo=UTC)
FEE_RATE = 0.0005142955428165985
V2_VERSION = "behavioral-distillation-v2-cross-asset-logistic"
V3_VERSION = "behavioral-distillation-v3-cross-asset-indicators"

DATASET_V2 = ROOT / "quant" / "outputs" / "cross_asset_model_dataset.csv"
DATASET_V3 = ROOT / "quant" / "outputs" / "cross_asset_model_dataset_v3.csv"
MARKET = ROOT / "quant" / "outputs" / "cross_asset_market_context.csv"
UNIVERSE = ROOT / "quant" / "reports" / "cross_asset_universe.csv"
MANIFEST = ROOT / "manifest.json"
REPORTS = ROOT / "quant" / "reports"


@dataclass(frozen=True)
class AuditWindow:
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
    AuditWindow(
        "WF1",
        datetime(2023, 1, 1, tzinfo=UTC),
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 1, tzinfo=UTC),
    ),
    AuditWindow(
        "WF2",
        datetime(2024, 1, 1, tzinfo=UTC),
        datetime(2025, 1, 1, tzinfo=UTC),
        datetime(2026, 1, 1, tzinfo=UTC),
    ),
    AuditWindow("WF3", datetime(2025, 1, 1, tzinfo=UTC), datetime(2026, 1, 1, tzinfo=UTC), FROZEN_CUTOFF),
)

# These are the only historical aliases deliberately merged in this audit.
# Other historical symbols remain isolated because no defensible OKX mapping
# was found in the frozen artifacts.
HISTORICAL_ALIAS_TO_CANONICAL = {
    "ADAUSD": "ADA-USDT-SWAP",
    "ADAUSDT": "ADA-USDT-SWAP",
    "BNBUSD": "BNB-USDT-SWAP",
    "BNBUSDT": "BNB-USDT-SWAP",
    "DOGEUSD": "DOGE-USDT-SWAP",
    "DOGEUSDT": "DOGE-USDT-SWAP",
    "XBTM21": "BTC-USDT-SWAP",
    "XBTUSD": "BTC-USDT-SWAP",
}


def parse_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _number(value: Any, default: float | None = None) -> float | None:
    parsed = parse_float(value, default)
    if parsed is None or not math.isfinite(parsed):
        return default
    return float(parsed)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _read_dataset(path: Path) -> list[dict[str, Any]]:
    return [
        row
        for row in _read_csv(path)
        if str(row.get("model_eligible", "")).lower() == "true"
        and (parse_utc(row.get("decision_time")) or datetime.max.replace(tzinfo=UTC)) <= FROZEN_CUTOFF
    ]


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def canonical_symbol(symbol: str, mapping: Mapping[str, str] | None = None) -> str:
    aliases = mapping or HISTORICAL_ALIAS_TO_CANONICAL
    return str(aliases.get(str(symbol), f"HISTORICAL:{symbol}"))


def merge_duplicate_signals(
    signals: Iterable[Mapping[str, Any]],
    mapping: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Merge same-time historical aliases into one confidence-weighted target.

    The function is exchange-neutral and intentionally accepts plain mappings
    so it can be tested without a transport or a model.
    """

    grouped: defaultdict[tuple[str, datetime], list[Mapping[str, Any]]] = defaultdict(list)
    for item in signals:
        source = str(item.get("historical_symbol") or item.get("symbol") or "")
        decision_time = parse_utc(item.get("decision_time") or item.get("signal_time"))
        if not source or decision_time is None:
            continue
        grouped[(canonical_symbol(source, mapping), decision_time)].append(item)

    merged: list[dict[str, Any]] = []
    for (venue_symbol, decision_time), items in sorted(grouped.items(), key=lambda pair: pair[0][1]):
        weighted_target = 0.0
        total_weight = 0.0
        for item in items:
            target = _number(item.get("target_exposure"), 0.0) or 0.0
            confidence = max(0.000001, min(1.0, _number(item.get("confidence"), 0.0) or 0.0))
            weighted_target += target * confidence
            total_weight += confidence
        strongest = max(items, key=lambda item: _number(item.get("confidence"), 0.0) or 0.0)
        merged.append(
            {
                "venue_symbol": venue_symbol,
                "decision_time": decision_time,
                "target_exposure": round(weighted_target / total_weight, 12) if total_weight else 0.0,
                "action": str(strongest.get("action") or "NO_TRADE"),
                "confidence": max((_number(item.get("confidence"), 0.0) or 0.0) for item in items),
                "historical_symbols": tuple(sorted({str(item.get("historical_symbol") or item.get("symbol")) for item in items})),
                "source_signals": tuple(
                    {
                        "historical_symbol": str(item.get("historical_symbol") or item.get("symbol")),
                        "target_exposure": _number(item.get("target_exposure"), 0.0) or 0.0,
                        "action": str(item.get("action") or "NO_TRADE"),
                        "confidence": _number(item.get("confidence"), 0.0) or 0.0,
                    }
                    for item in items
                ),
            }
        )
    return merged


@dataclass(frozen=True)
class MarketBar:
    timestamp: datetime
    open: float
    close: float
    funding_rate: float | None = None
    funding_time: datetime | None = None


def load_market_context(path: Path = MARKET) -> dict[str, list[MarketBar]]:
    """Load public bars while preserving missing funding as ``None``."""

    grouped: defaultdict[str, list[MarketBar]] = defaultdict(list)
    for row in _read_csv(path):
        timestamp = parse_utc(row.get("timestamp"))
        open_price = _number(row.get("open"))
        close_price = _number(row.get("close"))
        if timestamp is None or open_price is None or close_price is None or open_price <= 0 or close_price <= 0:
            continue
        source_time = parse_utc(row.get("funding_source_timestamp_utc"))
        rate = _number(row.get("funding_rate"))
        # A funding value is an observed event only when its source timestamp
        # is present and not after the bar timestamp. Missing is never 0.0.
        # The context builder carries the latest known funding observation
        # forward for causal features.  A replay charge, however, must happen
        # once at the observed funding event, not on every bar that carries
        # the as-of value.
        if source_time is None or rate is None or source_time != timestamp:
            rate = None
            source_time = None
        grouped[str(row.get("symbol") or "")].append(MarketBar(timestamp, open_price, close_price, rate, source_time))
    for values in grouped.values():
        values.sort(key=lambda bar: bar.timestamp)
    return dict(grouped)


def _canonical_bars(
    source_bars: Mapping[str, list[MarketBar]],
    mapping: Mapping[str, str] | None = None,
) -> dict[str, list[MarketBar]]:
    buckets: defaultdict[str, defaultdict[datetime, list[MarketBar]]] = defaultdict(lambda: defaultdict(list))
    for source, bars in source_bars.items():
        for bar in bars:
            buckets[canonical_symbol(source, mapping)][bar.timestamp].append(bar)
    output: dict[str, list[MarketBar]] = {}
    for venue_symbol, by_time in buckets.items():
        bars: list[MarketBar] = []
        for timestamp, values in sorted(by_time.items()):
            rates = [bar.funding_rate for bar in values if bar.funding_rate is not None]
            funding_time = max((bar.funding_time for bar in values if bar.funding_time is not None), default=None)
            bars.append(
                MarketBar(
                    timestamp,
                    sum(bar.open for bar in values) / len(values),
                    sum(bar.close for bar in values) / len(values),
                    sum(rates) / len(rates) if rates else None,
                    funding_time,
                )
            )
        output[venue_symbol] = bars
    return output


def load_tick_sizes(path: Path = ROOT / "api-v1-instrument.all.csv") -> dict[str, float]:
    output: dict[str, float] = {}
    for row in _read_csv(path):
        symbol = str(row.get("symbol") or "")
        tick = _number(row.get("tickSize"))
        if symbol and tick is not None and tick > 0:
            output.setdefault(symbol, tick)
    return output


def _canonical_tick_sizes(ticks: Mapping[str, float], mapping: Mapping[str, str] | None = None) -> dict[str, float]:
    grouped: defaultdict[str, list[float]] = defaultdict(list)
    for symbol, tick in ticks.items():
        grouped[canonical_symbol(symbol, mapping)].append(tick)
    return {symbol: sum(values) / len(values) for symbol, values in grouped.items() if values}


def replay_next_bar(
    bars: Iterable[MarketBar],
    events: Iterable[Mapping[str, Any]],
    *,
    start_time: datetime,
    end_time: datetime,
    fee_rate: float = FEE_RATE,
    tick_size: float = 0.1,
    slippage_ticks: float = 1.0,
    max_abs_exposure: float = 1.0,
) -> dict[str, Any]:
    """Replay a target exposure at the next bar open with explicit costs.

    Funding is charged only for observed funding events.  The cost convention
    is ``position * funding_rate``: a positive rate costs a long and credits a
    short.  Prices and returns are deliberately normalised, not account PnL.
    """

    ordered = sorted((bar for bar in bars if start_time <= bar.timestamp < end_time), key=lambda bar: bar.timestamp)
    if not ordered:
        return {
            "status": "NO_MARKET_DATA",
            "net_return": None,
            "gross_profit": 0.0,
            "gross_loss": 0.0,
            "fees": 0.0,
            "funding": 0.0,
            "slippage": 0.0,
            "turnover": 0.0,
            "signal_count": 0,
            "executed_adjustments": 0,
            "average_return_per_adjustment": None,
            "profit_factor": None,
            "funding_events_observed": 0,
            "funding_events_missing": 0,
            "bar_count": 0,
        }
    times = [bar.timestamp for bar in ordered]
    scheduled: dict[int, Mapping[str, Any]] = {}
    event_count = 0
    for event in sorted(events, key=lambda item: parse_utc(item.get("decision_time") or item.get("signal_time")) or datetime.min.replace(tzinfo=UTC)):
        signal_time = parse_utc(event.get("decision_time") or event.get("signal_time"))
        if signal_time is None:
            continue
        index = bisect_right(times, signal_time)
        if index < len(ordered):
            scheduled[index] = event
            event_count += 1
    equity = 1.0
    position = 0.0
    previous_close = ordered[0].open
    fees = funding = slippage = turnover = 0.0
    executed = 0
    returns: list[float] = []
    funding_observed = funding_missing = 0
    for index, bar in enumerate(ordered):
        equity_before = equity
        if previous_close > 0:
            equity += equity * position * (bar.open / previous_close - 1.0)
        if bar.funding_rate is not None and bar.funding_time is not None:
            funding_observed += 1
            funding_cost = equity * position * bar.funding_rate
            funding += funding_cost
            equity -= funding_cost
        else:
            funding_missing += 1
        event = scheduled.get(index)
        if event is not None:
            target = max(-max_abs_exposure, min(max_abs_exposure, _number(event.get("target_exposure"), 0.0) or 0.0))
            delta = target - position
            if abs(delta) > 1e-12:
                position = target
                turnover += abs(delta)
                fee_cost = abs(delta) * fee_rate
                slip_cost = abs(delta) * slippage_ticks * max(tick_size, 0.0) / max(abs(bar.open), 1e-12)
                fees += fee_cost
                slippage += slip_cost
                equity -= fee_cost + slip_cost
                executed += 1
        if bar.open > 0:
            equity += equity * position * (bar.close / bar.open - 1.0)
        returns.append(equity / equity_before - 1.0 if equity_before else 0.0)
        previous_close = bar.close
    gains = sum(value for value in returns if value > 0)
    losses = abs(sum(value for value in returns if value < 0))
    return {
        "status": "PASS",
        "net_return": equity - 1.0,
        "gross_profit": gains,
        "gross_loss": losses,
        "fees": fees,
        "funding": funding,
        "slippage": slippage,
        "turnover": turnover,
        "signal_count": event_count,
        "executed_adjustments": executed,
        "average_return_per_adjustment": (equity - 1.0) / executed if executed else None,
        "profit_factor": gains / losses if losses else None,
        "funding_events_observed": funding_observed,
        "funding_events_missing": funding_missing,
        "bar_count": len(ordered),
    }


def replay_portfolio(
    events: Iterable[Mapping[str, Any]],
    bars_by_symbol: Mapping[str, list[MarketBar]],
    tick_sizes: Mapping[str, float],
    *,
    start_time: datetime,
    end_time: datetime,
    fee_multiplier: float = 1.0,
    slippage_ticks: float = 1.0,
) -> dict[str, Any]:
    grouped: defaultdict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for event in events:
        grouped[str(event.get("venue_symbol") or "")].append(event)
    active = [symbol for symbol in sorted(grouped) if bars_by_symbol.get(symbol)]
    per_symbol: dict[str, dict[str, Any]] = {}
    for symbol in active:
        per_symbol[symbol] = replay_next_bar(
            bars_by_symbol[symbol],
            grouped[symbol],
            start_time=start_time,
            end_time=end_time,
            fee_rate=FEE_RATE * fee_multiplier,
            tick_size=tick_sizes.get(symbol, 0.1),
            slippage_ticks=slippage_ticks,
        )
    if not per_symbol:
        return {"status": "NO_TEST_DATA", "active_symbols": 0, "per_symbol": {}, "net_return": None}
    numeric_keys = ("net_return", "fees", "funding", "slippage", "turnover", "average_return_per_adjustment")
    result: dict[str, Any] = {
        "status": "PASS",
        "active_symbols": len(per_symbol),
        "per_symbol": per_symbol,
        "signal_count": sum(int(item["signal_count"]) for item in per_symbol.values()),
        "executed_adjustments": sum(int(item["executed_adjustments"]) for item in per_symbol.values()),
        "funding_events_observed": sum(int(item["funding_events_observed"]) for item in per_symbol.values()),
        "funding_events_missing": sum(int(item["funding_events_missing"]) for item in per_symbol.values()),
        "gross_profit": sum(float(item["gross_profit"]) for item in per_symbol.values()),
        "gross_loss": sum(float(item["gross_loss"]) for item in per_symbol.values()),
    }
    for key in numeric_keys:
        values = [float(item[key]) for item in per_symbol.values() if item.get(key) is not None]
        result[key] = sum(values) / len(values) if values else None
    result["profit_factor"] = result["gross_profit"] / result["gross_loss"] if result["gross_loss"] else None
    return result


def action_family(action: Any) -> str:
    text = str(action or "")
    for family in ("FLIP", "OPEN", "CLOSE", "ADD", "REDUCE"):
        if text.startswith(family):
            return family
    return "OTHER"


def _macro_f1(labels: list[str], predictions: list[str]) -> float | None:
    if not labels:
        return None
    classes = sorted(set(labels) | set(predictions))
    scores: list[float] = []
    for label in classes:
        true_positive = sum(actual == label and predicted == label for actual, predicted in zip(labels, predictions))
        false_positive = sum(actual != label and predicted == label for actual, predicted in zip(labels, predictions))
        false_negative = sum(actual == label and predicted != label for actual, predicted in zip(labels, predictions))
        denominator = 2 * true_positive + false_positive + false_negative
        scores.append(2 * true_positive / denominator if denominator else 0.0)
    return sum(scores) / len(scores) if scores else None


def _correlation(left: list[float], right: list[float]) -> float | None:
    if len(left) < 2 or len(left) != len(right):
        return None
    left_mean = sum(left) / len(left)
    right_mean = sum(right) / len(right)
    numerator = sum((a - left_mean) * (b - right_mean) for a, b in zip(left, right))
    left_scale = math.sqrt(sum((a - left_mean) ** 2 for a in left))
    right_scale = math.sqrt(sum((b - right_mean) ** 2 for b in right))
    return numerator / (left_scale * right_scale) if left_scale and right_scale else None


def behaviour_metrics(rows: Iterable[Mapping[str, Any]], predictions: Iterable[tuple[Mapping[str, Any], StrategySignal]]) -> dict[str, Any]:
    source_rows = list(rows)
    by_id = {str(row.get("decision_episode_id")): (row, signal) for row, signal in predictions}
    labeled: list[tuple[Mapping[str, Any], StrategySignal]] = []
    for row in source_rows:
        item = by_id.get(str(row.get("decision_episode_id")))
        if item and row.get("label_status") == "AVAILABLE" and row.get("label_next_action"):
            labeled.append(item)
    labels = [str(row["label_next_action"]) for row, _ in labeled]
    predicted = [str(signal.action) for _, signal in labeled]
    actual_targets = [_number(row.get("label_next_target_exposure")) for row, _ in labeled]
    predicted_targets = [float(signal.target_exposure) for _, signal in labeled]
    pairs = [(a, p) for a, p in zip(actual_targets, predicted_targets) if a is not None]
    family_recalls: dict[str, float | None] = {}
    for family in ("OPEN", "CLOSE", "ADD", "REDUCE", "FLIP"):
        family_actual = [index for index, action in enumerate(labels) if action_family(action) == family]
        family_recalls[f"{family.lower()}_recall"] = (
            sum(action_family(predicted[index]) == family for index in family_actual) / len(family_actual)
            if family_actual
            else None
        )
    return {
        "rows_seen": len(source_rows),
        "labeled_rows": len(labeled),
        "action_accuracy": sum(actual == pred for actual, pred in zip(labels, predicted)) / len(labels) if labels else None,
        "action_macro_f1": _macro_f1(labels, predicted),
        "target_exposure_mae": sum(abs(actual - predicted) for actual, predicted in pairs) / len(pairs) if pairs else None,
        "target_exposure_correlation": _correlation([a for a, _ in pairs], [p for _, p in pairs]),
        **family_recalls,
    }


def _fit_model(rows: list[dict[str, Any]], version: str) -> CrossAssetNumpyLogisticStrategy:
    # The model class deliberately honours a TRAIN marker.  The calendar
    # audit owns the marker so fixed windows cannot inherit the old global
    # split from the dataset artifact.
    train_rows = [dict(row, dataset_split="TRAIN") for row in rows]
    model = CrossAssetNumpyLogisticStrategy().fit(train_rows)
    model.version = version
    return model


def _predict(model: CrossAssetNumpyLogisticStrategy, rows: list[dict[str, Any]]) -> list[tuple[dict[str, Any], StrategySignal]]:
    from quant_bot.strategy.feature_contract import strategy_input_from_row

    return [(row, model.predict(strategy_input_from_row(row))) for row in rows]


def _event_rows(predictions: Iterable[tuple[Mapping[str, Any], StrategySignal]]) -> list[dict[str, Any]]:
    raw = [
        {
            "historical_symbol": str(row.get("symbol") or ""),
            "decision_time": parse_utc(row.get("decision_time")),
            "target_exposure": signal.target_exposure,
            "action": signal.action,
            "confidence": signal.confidence,
        }
        for row, signal in predictions
    ]
    return merge_duplicate_signals(raw)


def _window_rows(rows: list[dict[str, Any]], start: datetime | None, end: datetime) -> list[dict[str, Any]]:
    return [row for row in rows if (parse_utc(row.get("decision_time")) or datetime.max.replace(tzinfo=UTC)) < end and (start is None or (parse_utc(row.get("decision_time")) or datetime.min.replace(tzinfo=UTC)) >= start)]


def _audit_leakage(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    checks = {
        "future_bar_observation_count": 0,
        "future_funding_observation_count": 0,
        "future_history_observation_count": 0,
        "forbidden_input_column_count": 0,
        "invalid_decision_time_count": 0,
    }
    for row in rows:
        decision = parse_utc(row.get("decision_time"))
        if decision is None:
            checks["invalid_decision_time_count"] += 1
            continue
        latest_bar = parse_utc(row.get("feature_latest_bar_time"))
        funding_time = parse_utc(row.get("feature_funding_source_time"))
        history_time = parse_utc(row.get("feature_history_last_decision_time"))
        if latest_bar is not None and latest_bar > decision:
            checks["future_bar_observation_count"] += 1
        if funding_time is not None and funding_time > decision:
            checks["future_funding_observation_count"] += 1
        if history_time is not None and history_time > decision:
            checks["future_history_observation_count"] += 1
        checks["forbidden_input_column_count"] += sum(key.startswith(("label_", "observed_")) for key in FEATURE_COLUMNS)
    checks["status"] = "PASS" if not any(checks.values()) else "FAIL"
    return checks


def _protected_hash_audit() -> dict[str, Any]:
    if not MANIFEST.exists():
        return {"status": "WARNING", "manifest_present": False, "checked": 0, "mismatches": []}
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    mismatches: list[str] = []
    checked = 0
    for item in manifest.get("files", []):
        relative = Path(str(item.get("file") or ""))
        path = ROOT / relative
        expected = str(item.get("sha256") or "")
        # The root manifest also covers documentation.  This audit protects
        # the raw CSV/JSON inputs only; README changes are unrelated to the
        # data replay and must not turn a valid raw-input audit red.
        if relative.suffix.lower() not in {".csv", ".json"}:
            continue
        if not path.exists() or not expected:
            mismatches.append(str(relative))
            continue
        checked += 1
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected:
            mismatches.append(str(relative))
    return {
        "status": "PASS" if not mismatches else "FAIL",
        "manifest_present": True,
        "checked": checked,
        "mismatches": mismatches,
        "raw_inputs_not_modified_by_audit": True,
    }


def evaluate_gates(
    behaviour_results: Iterable[Mapping[str, Any]],
    performance_results: Iterable[Mapping[str, Any]],
    *,
    leakage_status: str = "PASS",
) -> dict[str, Any]:
    behavior = list(behaviour_results)
    performance = list(performance_results)
    details: list[dict[str, Any]] = []
    behavior_pass = leakage_status == "PASS"
    for window in ("WF1", "WF2", "WF3"):
        v2 = next((row for row in behavior if row.get("window") == window and row.get("model") == "v2" and row.get("split") == "TEST"), None)
        v3 = next((row for row in behavior if row.get("window") == window and row.get("model") == "v3" and row.get("split") == "TEST"), None)
        available = bool(v2 and v3 and v2.get("labeled_rows", 0) and v3.get("labeled_rows", 0))
        pass_window = bool(
            available
            and v3.get("action_macro_f1") is not None
            and v2.get("action_macro_f1") is not None
            and v3["action_macro_f1"] >= v2["action_macro_f1"] - 0.02
            and v3.get("target_exposure_mae") is not None
            and v2.get("target_exposure_mae") is not None
            and v3["target_exposure_mae"] <= v2["target_exposure_mae"] + 0.01
            and (v3.get("flip_recall") or 0.0) > 0.0
        )
        behavior_pass = behavior_pass and pass_window
        details.append({"gate": f"behavior_{window}", "status": "PASS" if pass_window else "FAIL", "available": available})

    base = [row for row in performance if row.get("model") == "v3" and row.get("cost_profile") == "BASE"]
    stress = [row for row in performance if row.get("model") == "v3" and row.get("cost_profile") == "STRESS"]
    base_by_window = {str(row["window"]): row for row in base}
    hold_by_window = {str(row["window"]): row for row in performance if row.get("model") == "EQUAL_WEIGHT_LONG" and row.get("cost_profile") == "BASE"}
    stress_positive = sum(1 for row in stress if row.get("net_return") is not None and row["net_return"] > 0)
    all_base_available = all(window in base_by_window and base_by_window[window].get("net_return") is not None for window in ("WF1", "WF2", "WF3"))
    positive_base = all_base_available and all(base_by_window[window]["net_return"] > 0 for window in ("WF1", "WF2", "WF3"))
    adjustment_ok = all(base_by_window[window].get("average_return_per_adjustment") is not None and base_by_window[window]["average_return_per_adjustment"] > 0 for window in base_by_window) if base_by_window else False
    pf_ok = all(base_by_window[window].get("profit_factor") is not None and base_by_window[window]["profit_factor"] > 1.0 for window in base_by_window) if base_by_window else False
    benchmark_comparisons = [
        (window, base_by_window[window], hold_by_window[window])
        for window in base_by_window
        if base_by_window[window].get("net_return") is not None and hold_by_window.get(window, {}).get("net_return") is not None
    ]
    benchmark_ok = bool(benchmark_comparisons) and all(strategy["net_return"] > hold["net_return"] for _, strategy, hold in benchmark_comparisons)
    net_pass = positive_base and adjustment_ok and pf_ok and stress_positive >= 2 and benchmark_ok
    details.extend([
        {"gate": "base_positive_all_three_windows", "status": "PASS" if positive_base else "FAIL", "available": all_base_available},
        {"gate": "average_return_per_adjustment_positive", "status": "PASS" if adjustment_ok else "FAIL"},
        {"gate": "profit_factor_gt_one", "status": "PASS" if pf_ok else "FAIL"},
        {"gate": "stress_positive_at_least_two_of_three", "status": "PASS" if stress_positive >= 2 else "FAIL", "positive_windows": stress_positive},
        {"gate": "beat_equal_weight_buy_and_hold_when_available", "status": "PASS" if benchmark_ok else "FAIL", "compared_windows": len(benchmark_comparisons)},
    ])
    return {
        "leakage_zero": leakage_status == "PASS",
        "behavior_gates_pass": behavior_pass,
        "net_gates_pass": net_pass,
        "all_gates_pass": behavior_pass and net_pass,
        "details": details,
    }


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fieldnames.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames or ["status"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _universe_summary() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    rows = _read_csv(UNIVERSE)
    return rows, {str(row.get("symbol")): row for row in rows}


def build() -> dict[str, Any]:
    source_v2 = _read_dataset(DATASET_V2)
    source_v3 = _read_dataset(DATASET_V3)
    universe_rows, universe_by_symbol = _universe_summary()
    source_bars = load_market_context()
    bars_by_symbol = _canonical_bars(source_bars)
    ticks = _canonical_tick_sizes(load_tick_sizes())
    leakage = _audit_leakage(source_v3)
    protected = _protected_hash_audit()

    behavior_rows: list[dict[str, Any]] = []
    performance_rows: list[dict[str, Any]] = []
    symbol_rows: list[dict[str, Any]] = []
    sensitivity_rows: list[dict[str, Any]] = []
    window_summaries: list[dict[str, Any]] = []

    for window in WINDOWS:
        train_v2 = _window_rows(source_v2, None, window.train_end)
        train_v3 = _window_rows(source_v3, None, window.train_end)
        validation_v2 = _window_rows(source_v2, window.validation_start, window.validation_end)
        validation_v3 = _window_rows(source_v3, window.validation_start, window.validation_end)
        test_v2 = _window_rows(source_v2, window.test_start, window.test_end)
        test_v3 = _window_rows(source_v3, window.test_start, window.test_end)
        model_predictions: dict[str, list[tuple[dict[str, Any], StrategySignal]]] = {}
        if train_v2 and train_v3:
            models = {
                "v2": _fit_model(train_v2, V2_VERSION),
                "v3": _fit_model(train_v3, V3_VERSION),
            }
            for name, model in models.items():
                val_rows = validation_v2 if name == "v2" else validation_v3
                out_rows = test_v2 if name == "v2" else test_v3
                for split, split_rows in (("VALIDATION", val_rows), ("TEST", out_rows)):
                    predictions = _predict(model, split_rows)
                    metrics = behaviour_metrics(split_rows, predictions)
                    behavior_rows.append({"window": window.name, "split": split, "model": name, "start": (window.validation_start if split == "VALIDATION" else window.test_start).isoformat(), "end": (window.validation_end if split == "VALIDATION" else window.test_end).isoformat(), **metrics})
                    for symbol in sorted({str(row.get("symbol")) for row in split_rows}):
                        symbol_source_rows = [row for row in split_rows if str(row.get("symbol")) == symbol]
                        symbol_predictions = [(row, signal) for row, signal in predictions if str(row.get("symbol")) == symbol]
                        symbol_rows.append({"window": window.name, "split": split, "model": name, "symbol": symbol, "canonical_instrument": canonical_symbol(symbol), **behaviour_metrics(symbol_source_rows, symbol_predictions)})
                prediction_rows = test_v3 if name == "v3" else test_v2
                if prediction_rows:
                    model_predictions[name] = _predict(model, prediction_rows)

        events_by_model = {name: _event_rows(values) for name, values in model_predictions.items()}
        active_events = list(events_by_model.get("v3", [])) + list(events_by_model.get("v2", []))
        active_symbols = sorted({str(event["venue_symbol"]) for event in active_events if str(event.get("venue_symbol")) in bars_by_symbol})
        if active_symbols:
            for model_name, events in events_by_model.items():
                for profile, fee_multiplier, slip in (("BASE", 1.0, 1.0), ("STRESS", 1.5, 2.0)):
                    replay = replay_portfolio(events, bars_by_symbol, ticks, start_time=window.test_start, end_time=window.test_end, fee_multiplier=fee_multiplier, slippage_ticks=slip)
                    performance_rows.append({"window": window.name, "model": model_name, "cost_profile": profile, "test_rows": len(test_v3 if model_name == "v3" else test_v2), "test_start": window.test_start.isoformat(), "test_end": window.test_end.isoformat(), **{key: value for key, value in replay.items() if key != "per_symbol"}})
                    for symbol, item in replay.get("per_symbol", {}).items():
                        sensitivity_rows.append({"window": window.name, "model": model_name, "cost_profile": profile, "venue_symbol": symbol, "fee_multiplier": fee_multiplier, "slippage_ticks": slip, **item})
            # Baselines are evaluated on the same active canonical universe.
            hold_events = [{"venue_symbol": symbol, "decision_time": window.test_start - timedelta(microseconds=1), "target_exposure": 1.0, "action": "BUY_HOLD", "confidence": 1.0} for symbol in active_symbols]
            for baseline_name, baseline_events in (("NO_TRADE", []), ("EQUAL_WEIGHT_LONG", hold_events)):
                replay = replay_portfolio(baseline_events, bars_by_symbol, ticks, start_time=window.test_start, end_time=window.test_end)
                performance_rows.append({"window": window.name, "model": baseline_name, "cost_profile": "BASE", "test_rows": len(test_v3), "test_start": window.test_start.isoformat(), "test_end": window.test_end.isoformat(), **{key: value for key, value in replay.items() if key != "per_symbol"}})
        else:
            for model_name in ("v2", "v3"):
                for profile in ("BASE", "STRESS"):
                    performance_rows.append({"window": window.name, "model": model_name, "cost_profile": profile, "test_rows": len(test_v3 if model_name == "v3" else test_v2), "status": "NO_TEST_DATA", "net_return": None, "average_return_per_adjustment": None, "profit_factor": None, "active_symbols": 0})
        window_summaries.append({"window": window.name, "train_rows": len(train_v3), "validation_rows": len(validation_v3), "test_rows": len(test_v3), "eligible_test_symbols": len({str(row.get("symbol")) for row in test_v3}), "status": "TEST_DATA_AVAILABLE" if test_v3 else "NO_TEST_DATA"})

    gates = evaluate_gates(behavior_rows, performance_rows, leakage_status=str(leakage["status"]))
    status = "DEMO_CANDIDATE_LIVE_REVIEW_REQUIRED" if gates["all_gates_pass"] else "DEMO_CONTINUE_LIVE_BLOCKED"
    excluded = sorted({str(row.get("symbol")) for row in universe_rows} - {str(row.get("symbol")) for row in source_v3})
    result: dict[str, Any] = {
        "report_version": "M14-STRATEGY-EFFECTIVENESS-AUDIT-1.0",
        "analysis_commit": _git_head(),
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "status": status,
        "live_trading_allowed": False,
        "demo_may_continue_under_existing_risk_limits": True,
        "dataset": {"historical_rows_all": sum(1 for row in _read_csv(DATASET_V3) if row.get("symbol")), "historical_symbols_all": len(universe_rows), "eligible_rows": len(source_v3), "eligible_symbols": len({str(row.get("symbol")) for row in source_v3}), "excluded_symbols": excluded, "frozen_cutoff": FROZEN_CUTOFF.isoformat()},
        "model_versions": {"v2": V2_VERSION, "v3": V3_VERSION},
        "walk_forward_windows": window_summaries,
        "behaviour_results": behavior_rows,
        "performance_results": performance_rows,
        "leakage_audit": leakage,
        "protected_input_hash_audit": protected,
        "contract_terms_policy": "Eligibility checks multiplier, lot size, payout model and settlement currency from the historical registry. Replay returns remain normalized exposure proxies and must not be read as wallet/account PnL.",
        "funding_policy": "Observed funding events only; positive rate is a long cost and short credit; missing funding remains missing and is counted, never imputed to zero.",
        "execution_policy": "Decision at t executes at the first strictly later hourly bar open; fees and slippage are applied to exposure changes; duplicate aliases are merged once per canonical symbol and decision time.",
        "gate_evaluation": gates,
        "next_action": "Keep current Demo baseline. Obtain public hourly coverage through 2026 and improve behavior around FLIP before any live review.",
        "private_api_used": False,
        "orders_submitted": False,
        "real_funds_used": False,
    }

    REPORTS.mkdir(parents=True, exist_ok=True)
    (REPORTS / "strategy_effectiveness_audit.json").write_text(json.dumps(result, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    _write_csv(REPORTS / "strategy_effectiveness_by_window.csv", behavior_rows)
    _write_csv(REPORTS / "strategy_effectiveness_by_symbol.csv", symbol_rows)
    _write_csv(REPORTS / "strategy_cost_sensitivity.csv", sensitivity_rows + performance_rows)

    base_v3 = {(row.get("window"), row.get("cost_profile")): row for row in performance_rows if row.get("model") == "v3"}
    lines = [
        "# Strategy Effectiveness Audit",
        "",
        f"- 审计状态：**{status}**",
        f"- 策略标记：`{result['strategy_fidelity']}`",
        f"- 历史品种：`{len(universe_rows)}`；可建模品种：`{result['dataset']['eligible_symbols']}`；可建模行：`{result['dataset']['eligible_rows']}`",
        f"- 泄漏审计：**{leakage['status']}**；受保护原始输入哈希：**{protected['status']}**",
        "- 本次没有连接私有 API、没有提交订单、没有使用真实资金；Demo 不会因为本报告自动切换模型或自动下单。",
        "",
        "## 先看结论",
        "",
        "该审计同时检查行为复现和净成本后表现。回放收益是逐品种等权的标准化暴露收益代理，不是钱包、账户或真实交易收益。任何一个时间外窗口无数据、泄漏、翻转召回为零或净收益门槛失败，都会阻断 Live。",
        "",
        "## Walk-forward 窗口",
        "",
        "|窗口|训练截止|验证区间|测试区间|测试行|状态|",
        "|---|---|---|---|---:|---|",
    ]
    for window, summary in zip(WINDOWS, window_summaries):
        lines.append(f"|{window.name}|<{window.train_end.date()}|{window.validation_start.date()}–{window.validation_end.date()}|{window.test_start.date()}–{window.test_end.date()}|{summary['test_rows']}|{summary['status']}|")
    lines += ["", "## 行为门槛（测试集）", "", "|窗口|v2 Macro-F1|v3 Macro-F1|v2 MAE|v3 MAE|v3 Flip 召回|", "|---|---:|---:|---:|---:|---:|"]
    for window in ("WF1", "WF2", "WF3"):
        v2 = next((row for row in behavior_rows if row["window"] == window and row["model"] == "v2" and row["split"] == "TEST"), {})
        v3 = next((row for row in behavior_rows if row["window"] == window and row["model"] == "v3" and row["split"] == "TEST"), {})
        fmt = lambda value: "—" if value is None else f"{float(value):.6f}"
        lines.append(f"|{window}|{fmt(v2.get('action_macro_f1'))}|{fmt(v3.get('action_macro_f1'))}|{fmt(v2.get('target_exposure_mae'))}|{fmt(v3.get('target_exposure_mae'))}|{fmt(v3.get('flip_recall'))}|")
    lines += ["", "## 净成本回放", "", "|窗口|v3 基础成本净收益|v3 基础 PF|v3 压力成本净收益|活动标准合约数|", "|---|---:|---:|---:|---:|"]
    for window in ("WF1", "WF2", "WF3"):
        base = base_v3.get((window, "BASE"), {})
        stress = base_v3.get((window, "STRESS"), {})
        fmt = lambda value: "—" if value is None else f"{float(value):.6f}"
        lines.append(f"|{window}|{fmt(base.get('net_return'))}|{fmt(base.get('profit_factor'))}|{fmt(stress.get('net_return'))}|{base.get('active_symbols', 0)}|")
    lines += ["", "## 基线比较", "", "|窗口|v3 基础成本|不交易|等权买入并持有|", "|---|---:|---:|---:|"]
    for window in ("WF1", "WF2", "WF3"):
        strategy = base_v3.get((window, "BASE"), {})
        no_trade = next((row for row in performance_rows if row.get("window") == window and row.get("model") == "NO_TRADE" and row.get("cost_profile") == "BASE"), {})
        hold = next((row for row in performance_rows if row.get("window") == window and row.get("model") == "EQUAL_WEIGHT_LONG" and row.get("cost_profile") == "BASE"), {})
        fmt = lambda value: "—" if value is None else f"{float(value):.6f}"
        lines.append(f"|{window}|{fmt(strategy.get('net_return'))}|{fmt(no_trade.get('net_return'))}|{fmt(hold.get('net_return'))}|")
    lines += ["", "## 门槛结果", ""]
    for detail in gates["details"]:
        suffix = f"（可用={detail['available']}）" if "available" in detail else ""
        lines.append(f"- `{detail['gate']}`：**{detail['status']}**{suffix}")
    lines += [
        "",
        "## 数据与单位边界",
        "",
        "历史规格注册表用于确认 payout model、settlement currency、multiplier 和 lot size；标准化回放不会把 XBT、USD、USDT 直接相加，也不会把不同结算币种当成同一钱包余额。资金费只使用带来源时间的观测值。",
        "",
        "## 阻塞原因与建议",
        "",
        f"- 需要公开行情覆盖到冻结截止日；当前可建模数据的测试区间为 `{window_summaries[0]['test_rows']}` 行，WF2/WF3 是否可用见上表。",
        "- v3 必须在每个测试窗口保持翻转动作召回率大于 0；当前结果会如实记录为失败或不可用，不用默认值掩盖。",
        "- 在所有三段时间外测试和至少两段压力成本测试通过前，不晋级 Live；即使通过，也仍需 30 天 Demo 连续观察和人工复核。",
        "",
        "## 产物",
        "",
        "- `strategy_effectiveness_audit.json`：机器可读总报告。",
        "- `strategy_effectiveness_by_window.csv`：v2/v3 逐窗口行为指标。",
        "- `strategy_effectiveness_by_symbol.csv`：逐窗口、逐历史品种行为指标。",
        "- `strategy_cost_sensitivity.csv`：基础/压力成本以及逐标准合约回放摘要。",
    ]
    (REPORTS / "strategy_effectiveness_audit.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return result


if __name__ == "__main__":
    result = build()
    print(json.dumps({"status": result["status"], "report": str(REPORTS / "strategy_effectiveness_audit.md"), "all_gates_pass": result["gate_evaluation"]["all_gates_pass"]}, ensure_ascii=False))
    raise SystemExit(0 if result["gate_evaluation"]["all_gates_pass"] else 2)
