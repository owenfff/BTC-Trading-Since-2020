#!/usr/bin/env python3
"""Build a causal market-clock dataset from event-driven behavior rows.

The historical exports contain rows when the trader changed a position.  A
runtime strategy, however, evaluates a clock even when it does not trade.
This builder expands each venue/instrument into one row per available closed
hourly bar.  Labels describe the position change by the next hourly decision,
so a period with no observed change is an explicit ``NO_TRADE`` observation.

The output is intentionally a large ignored CSV.  The tracked manifest is the
small, reviewable artifact; no raw source file is modified.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import subprocess
import sys
from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from cross_asset.hyperliquid import bars_for_features, load_candle_archive, load_funding  # noqa: E402
from features.market_features import build_market_features  # noqa: E402


UTC = timezone.utc
FROZEN_CUTOFF = datetime(2026, 7, 18, 21, 17, 31, 514000, tzinfo=UTC)
BAR_SECONDS = 3600
INPUT_DATASET = ROOT / "quant" / "outputs" / "cross_venue_model_dataset_v3.csv"
MARKET_CONTEXT = ROOT / "quant" / "outputs" / "cross_asset_market_context.csv"
HL_ROOT = ROOT / "quant" / "data" / "external" / "hyperliquid" / "paul"
DEFAULT_OUTPUT = ROOT / "quant" / "outputs" / "cross_venue_temporal_dataset_v3.csv"
DEFAULT_MANIFEST = ROOT / "quant" / "reports" / "cross_venue_temporal_dataset_v3_manifest.json"


def parse_time(value: Any) -> datetime | None:
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


def iso_time(value: datetime | None) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z") if value else ""


def number(value: Any, default: float | None = None) -> float | None:
    if value in (None, ""):
        return default
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def state_key(row: Mapping[str, Any]) -> str:
    venue = str(row.get("source_venue") or "BITMEX")
    canonical = str(row.get("canonical_asset") or row.get("feature_symbol") or row.get("symbol") or "UNKNOWN")
    return f"{venue}:{canonical}"


def market_key(venue: str, symbol: str) -> str:
    if venue == "BITMEX" and symbol in {"XBTUSD", "XBTM21", "XBTU21"}:
        return "BITMEX:BTC-PERP"
    return f"{venue}:{symbol}"


def _market_number(value: Any) -> float | None:
    return number(value)


def load_bitmex_market(path: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            symbol = str(raw.get("symbol") or "")
            timestamp = parse_time(raw.get("timestamp"))
            if not symbol or timestamp is None or timestamp > FROZEN_CUTOFF:
                continue
            grouped[market_key("BITMEX", symbol)].append({
                "timestamp": timestamp,
                "timestamp_utc": iso_time(timestamp),
                "open": _market_number(raw.get("open")),
                "high": _market_number(raw.get("high")),
                "low": _market_number(raw.get("low")),
                "close": _market_number(raw.get("close")),
                "volume": _market_number(raw.get("volume")),
                "turnover": _market_number(raw.get("turnover")),
                "mark_price": _market_number(raw.get("mark_price")),
                "index_price": _market_number(raw.get("index_price")),
                "funding_rate": _market_number(raw.get("funding_rate")),
                "funding_source_time": parse_time(raw.get("funding_source_timestamp_utc")),
            })
    for rows in grouped.values():
        rows.sort(key=lambda row: row["timestamp"])
    return dict(grouped)


def load_hyperliquid_market(root: Path) -> dict[str, list[dict[str, Any]]]:
    if not root.exists():
        return {}
    revisions = sorted(path for path in root.iterdir() if path.is_dir())
    if not revisions:
        return {}
    source = revisions[-1]
    bars = [bar for bar in load_candle_archive(source / "candles_1h.json") if bar.close_time <= FROZEN_CUTOFF + timedelta(hours=1)]
    funding = load_funding(source / "userFunding.json", cutoff=FROZEN_CUTOFF)
    return {"HYPERLIQUID:BTC-PERP": bars_for_features(bars, funding)}


def load_events(path: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            when = parse_time(raw.get("decision_time"))
            if when is None or when > FROZEN_CUTOFF:
                continue
            row = dict(raw)
            row["_time"] = when
            row["_before"] = number(raw.get("raw_current_position_contracts"), number(raw.get("observed_position_before_contracts"), 0.0)) or 0.0
            row["_after"] = number(raw.get("raw_target_position_contracts"), number(raw.get("observed_target_position_contracts"), 0.0)) or 0.0
            grouped[state_key(row)].append(row)
    for rows in grouped.values():
        rows.sort(key=lambda row: (row["_time"], str(row.get("decision_episode_id"))))
    return dict(grouped)


def _action(before: float, after: float) -> str:
    epsilon = 1e-12
    if abs(after - before) <= epsilon:
        return "NO_TRADE"
    if abs(before) <= epsilon and after > 0:
        return "OPEN_LONG"
    if abs(before) <= epsilon and after < 0:
        return "OPEN_SHORT"
    if before > 0 and after < 0:
        return "FLIP_SHORT"
    if before < 0 and after > 0:
        return "FLIP_LONG"
    if before > 0 and after == 0:
        return "CLOSE_LONG"
    if before < 0 and after == 0:
        return "CLOSE_SHORT"
    if before > 0 and after > before:
        return "ADD_LONG"
    if before < 0 and after < before:
        return "ADD_SHORT"
    if before > 0:
        return "REDUCE_LONG"
    return "REDUCE_SHORT"


def _action_kind(action: str) -> str:
    if "FLIP" in action:
        return "FLIP"
    if "ADD" in action:
        return "ADD"
    if "REDUCE" in action or "CLOSE" in action:
        return "REDUCE"
    return "OTHER"


def _event_index(event_times: list[datetime], when: datetime) -> int:
    return bisect_left(event_times, when) - 1


def _dynamic_state(events: list[dict[str, Any]], index: int, when: datetime, current: float, scale: float) -> dict[str, Any]:
    # The event list is already chronological.  Do not slice or rescan it for
    # each market bar: the latest event row contains the same past-only
    # account snapshot used by the event dataset, and the runtime strictly
    # overrides these dynamic fields during autonomous replay.
    last = events[index] if index >= 0 else None
    last_action = str(last.get("observed_action") or "") if last else ""
    cycle_start: datetime | None = None
    if current != 0:
        cycle_start = parse_time(last.get("feature_history_last_decision_time")) if last else None
        if cycle_start is None and last:
            cycle_start = last["_time"]
    recent_add = number(last.get("feature_recent_add_count_24h"), 0.0) if last else 0.0
    recent_reduce = number(last.get("feature_recent_reduce_count_24h"), 0.0) if last else 0.0
    recent_flip = number(last.get("feature_recent_flip_count_24h"), 0.0) if last else 0.0
    return {
        "feature_current_net_position_contracts": current,
        "feature_current_normalized_exposure": current / scale if scale else 0.0,
        "feature_position_scale_contracts": scale,
        "feature_cycle_duration_seconds": (when - cycle_start).total_seconds() if cycle_start else None,
        "feature_latest_action": last_action,
        "feature_recent_add_count_24h": recent_add,
        "feature_recent_reduce_count_24h": recent_reduce,
        "feature_recent_flip_count_24h": recent_flip,
        "feature_recent_realised_outcome": number(last.get("feature_recent_realised_outcome")) if last else None,
        "feature_realised_drawdown": number(last.get("feature_realised_drawdown"), 0.0) if last else 0.0,
        "feature_fee_accumulation_raw": number(last.get("feature_fee_accumulation_raw"), 0.0) if last else 0.0,
        "feature_funding_accumulation_raw": number(last.get("feature_funding_accumulation_raw"), 0.0) if last else 0.0,
        "feature_order_execution_style": str(last.get("feature_order_execution_style") or "") if last else "",
        "feature_ordering_confidence": str(last.get("feature_ordering_confidence") or "") if last else "",
        "feature_accounting_confidence": str(last.get("feature_accounting_confidence") or "") if last else "",
        "feature_history_last_decision_time": iso_time(last["_time"]) if last else "",
    }


def _stable_id(key: str, when: datetime) -> str:
    digest = hashlib.sha256(f"{key}|{iso_time(when)}".encode("utf-8")).hexdigest()[:24]
    return f"TEMP-{digest}"


def _scale(events: list[dict[str, Any]]) -> float:
    maximum = max((abs(number(row.get("_after"), 0.0) or 0.0) for row in events), default=0.0)
    return max(1.0, maximum)


def _complete_window(timestamps: list[datetime], start: int, end: int) -> bool:
    if start < 0 or end >= len(timestamps) or start > end:
        return False
    return all((timestamps[index] - timestamps[index - 1]).total_seconds() == BAR_SECONDS for index in range(start + 1, end + 1))


def _ema(values: list[float], period: int) -> list[float]:
    if not values or period <= 0:
        return []
    alpha = 2.0 / (period + 1.0)
    output = [values[0]]
    for value in values[1:]:
        output.append(alpha * value + (1.0 - alpha) * output[-1])
    return output


def _rsi(values: list[float], period: int = 14) -> float | None:
    if len(values) < period + 1:
        return None
    changes = [values[index] - values[index - 1] for index in range(1, len(values))]
    gains = [max(change, 0.0) for change in changes]
    losses = [max(-change, 0.0) for change in changes]
    average_gain = sum(gains[:period]) / period
    average_loss = sum(losses[:period]) / period
    for index in range(period, len(changes)):
        average_gain = ((period - 1) * average_gain + gains[index]) / period
        average_loss = ((period - 1) * average_loss + losses[index]) / period
    if average_loss == 0:
        return 100.0 if average_gain > 0 else 50.0
    return 100.0 - 100.0 / (1.0 + average_gain / average_loss)


def precompute_market_features(market: list[dict[str, Any]]) -> dict[datetime, dict[str, Any]]:
    """Compute the shared causal feature contract once per market series.

    ``build_market_features`` is the reference implementation used by the
    runtime.  This is an equivalent batch implementation: the feature for
    decision timestamp ``t[i]`` observes only bar ``i - 1`` and the preceding
    100 bars.  Avoiding repeated list slicing makes the full historical clock
    practical while retaining the same warm-up and gap rules.
    """

    market = sorted(market, key=lambda row: row["timestamp"])
    timestamps = [row["timestamp"] for row in market]
    consecutive_edges = [0] * len(timestamps)
    for index in range(1, len(timestamps)):
        if (timestamps[index] - timestamps[index - 1]).total_seconds() == BAR_SECONDS:
            consecutive_edges[index] = consecutive_edges[index - 1] + 1

    def complete(start: int, end: int) -> bool:
        if start < 0 or end >= len(timestamps) or start > end:
            return False
        return consecutive_edges[end] >= end - start

    output: dict[datetime, dict[str, Any]] = {}
    for index in range(1, len(market)):
        decision_time = timestamps[index]
        observed = market[index - 1]
        latest = observed.get("close")
        features: dict[str, Any] = {
            "feature_latest_bar_time": iso_time(observed["timestamp"]) if latest is not None and latest > 0 else "",
            "feature_market_data_available": latest is not None and latest > 0,
            "feature_mark_index_missing": True,
            "feature_funding_source_time": "",
            "feature_funding_rate": None,
            "feature_mark_index_basis": None,
            "feature_market_regime": "UNKNOWN",
            "feature_time_of_day_fraction": decision_time.hour / 24 + decision_time.minute / 1440 + decision_time.second / 86400,
            "feature_day_of_week": decision_time.weekday(),
            "feature_day_of_week_sin": math.sin(2 * math.pi * decision_time.weekday() / 7),
            "feature_day_of_week_cos": math.cos(2 * math.pi * decision_time.weekday() / 7),
        }
        for lag in (1, 3, 6, 12, 24, 72):
            features[f"feature_return_{lag}bar"] = None
        for name in ("feature_realized_volatility_72bar", "feature_atr_14bar", "feature_volume_change_1bar", "feature_volume_percentile_72bar", "feature_ma_distance_24bar", "feature_trend_slope_24bar", "feature_distance_rolling_high_72bar", "feature_distance_rolling_low_72bar"):
            features[name] = None
        for name in ("feature_rsi_14", "feature_macd_line_12_26", "feature_macd_signal_9", "feature_macd_histogram", "feature_bollinger_zscore_20", "feature_bollinger_percent_b_20"):
            features[name] = None
        if not features["feature_market_data_available"]:
            output[decision_time] = features
            continue
        close = float(latest)
        start100 = max(0, index - 100)
        close_window_values = [number(row.get("close")) for row in market[start100:index]]
        high_window_values = [number(row.get("high")) for row in market[start100:index]]
        low_window_values = [number(row.get("low")) for row in market[start100:index]]
        volume_window_values = [number(row.get("volume")) for row in market[start100:index]]
        if close_window_values and all(value is not None and value > 0 for value in close_window_values):
            closes = [float(value) for value in close_window_values]
            features["feature_rsi_14"] = _rsi(closes, 14)
            if len(closes) >= 26:
                fast = _ema(closes, 12)
                slow = _ema(closes, 26)
                macd = [fast[offset] - slow[offset] for offset in range(len(closes))]
                features["feature_macd_line_12_26"] = macd[-1]
                if len(macd) >= 34:
                    signal = _ema(macd[25:], 9)
                    features["feature_macd_signal_9"] = signal[-1]
                    features["feature_macd_histogram"] = macd[-1] - signal[-1]
            if len(closes) >= 20:
                window = closes[-20:]
                mean = sum(window) / len(window)
                deviation = float(np.std(np.asarray(window, dtype=float), ddof=0))
                if deviation > 0:
                    features["feature_bollinger_zscore_20"] = (window[-1] - mean) / deviation
                    lower = mean - 2.0 * deviation
                    upper = mean + 2.0 * deviation
                    features["feature_bollinger_percent_b_20"] = (window[-1] - lower) / (upper - lower)
        if len(volume_window_values) >= 72 and all(value is not None and value >= 0 for value in volume_window_values[-72:]):
            volume_window = [float(value) for value in volume_window_values[-72:]]
            features["feature_volume_percentile_72bar"] = sum(value <= volume_window[-1] for value in volume_window) / len(volume_window)
        for lag in (1, 3, 6, 12, 24, 72):
            if index - lag >= 1 and complete(index - lag, index - 1):
                previous = number(market[index - lag - 1].get("close"))
                if previous and previous > 0:
                    features[f"feature_return_{lag}bar"] = close / previous - 1.0
        if complete(index - 73, index - 1):
            close_values = [number(market[cursor].get("close")) for cursor in range(index - 72, index)]
            previous_values = [number(market[cursor].get("close")) for cursor in range(index - 73, index - 1)]
            if all(value is not None and value > 0 for value in close_values + previous_values):
                log_returns = [math.log(float(current) / float(previous)) for current, previous in zip(close_values, previous_values)]
                features["feature_realized_volatility_72bar"] = float(np.std(np.asarray(log_returns, dtype=float), ddof=0))
        if complete(index - 15, index - 1):
            ranges: list[float] = []
            for cursor in range(index - 14, index):
                high = number(market[cursor].get("high"))
                low = number(market[cursor].get("low"))
                previous_close = number(market[cursor - 1].get("close"))
                if high is None or low is None or previous_close is None:
                    ranges = []
                    break
                ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
            if ranges:
                features["feature_atr_14bar"] = sum(ranges) / len(ranges)
        if complete(index - 2, index - 1):
            previous_volume = number(market[index - 2].get("volume"))
            current_volume = number(observed.get("volume"))
            if previous_volume and previous_volume > 0 and current_volume is not None:
                features["feature_volume_change_1bar"] = current_volume / previous_volume - 1.0
        if complete(index - 24, index - 1):
            closes = [number(market[cursor].get("close")) for cursor in range(index - 24, index)]
            if all(value is not None and value > 0 for value in closes):
                close_values = [float(value) for value in closes]
                mean_close = sum(close_values) / len(close_values)
                features["feature_ma_distance_24bar"] = close / mean_close - 1.0
                log_closes = [math.log(value) for value in close_values]
                x_mean = (len(log_closes) - 1) / 2
                denominator = sum((cursor - x_mean) ** 2 for cursor in range(len(log_closes)))
                features["feature_trend_slope_24bar"] = sum((cursor - x_mean) * (value - sum(log_closes) / len(log_closes)) for cursor, value in enumerate(log_closes)) / denominator if denominator else None
        if complete(index - 72, index - 1):
            highs = [number(market[cursor].get("high")) for cursor in range(index - 72, index)]
            lows = [number(market[cursor].get("low")) for cursor in range(index - 72, index)]
            if all(value is not None for value in highs) and max(highs) > 0:
                features["feature_distance_rolling_high_72bar"] = close / max(highs) - 1.0
            if all(value is not None for value in lows) and min(lows) > 0:
                features["feature_distance_rolling_low_72bar"] = close / min(lows) - 1.0
        funding_time = parse_time(observed.get("funding_source_time"))
        if funding_time is not None and funding_time <= decision_time:
            features["feature_funding_source_time"] = iso_time(funding_time)
            features["feature_funding_rate"] = observed.get("funding_rate")
        mark = number(observed.get("mark_price"))
        index_price = number(observed.get("index_price"))
        if mark is not None and index_price is not None and index_price > 0:
            features["feature_mark_index_missing"] = False
            features["feature_mark_index_basis"] = mark / index_price - 1.0
        slope = features.get("feature_trend_slope_24bar")
        ma_distance = features.get("feature_ma_distance_24bar")
        if slope is not None and ma_distance is not None:
            if slope > 0.0001 and ma_distance > 0:
                features["feature_market_regime"] = "TREND_UP"
            elif slope < -0.0001 and ma_distance < 0:
                features["feature_market_regime"] = "TREND_DOWN"
            else:
                features["feature_market_regime"] = "RANGE_OR_MIXED"
        output[decision_time] = features
    return output


def build_rows(events_by_key: Mapping[str, list[dict[str, Any]]], market_by_key: Mapping[str, list[dict[str, Any]]], *, row_sink: Callable[[dict[str, Any]], None] | None = None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for key in sorted(events_by_key):
        events = events_by_key[key]
        market = list(market_by_key.get(key, []))
        if len(events) < 1 or len(market) < 2:
            coverage.append({"state_key": key, "event_rows": len(events), "market_bars": len(market), "temporal_rows": 0, "status": "MARKET_DATA_UNAVAILABLE"})
            continue
        market.sort(key=lambda item: item["timestamp"])
        # BTC-PERP combines several historical BitMEX symbols (for example
        # XBTUSD and XBTM21) into one behavior key.  Their archived market
        # rows can overlap at the same timestamp; keep the first deterministic
        # observation so a bar can never observe itself as its predecessor.
        deduplicated: dict[datetime, dict[str, Any]] = {}
        for item in market:
            deduplicated.setdefault(item["timestamp"], item)
        market = list(deduplicated.values())
        first_event = events[0]["_time"]
        last_event = events[-1]["_time"]
        precomputed = precompute_market_features(market)
        candidates = [bar for bar in market if bar["timestamp"] in precomputed and first_event <= bar["timestamp"] <= last_event and bar["timestamp"] <= FROZEN_CUTOFF]
        if len(candidates) < 2:
            coverage.append({"state_key": key, "event_rows": len(events), "market_bars": len(market), "temporal_rows": 0, "status": "INSUFFICIENT_OVERLAP"})
            continue
        timestamps = [bar["timestamp"] for bar in market]
        scale = _scale(events)
        event_times = [row["_time"] for row in events]
        produced = 0
        eligible = 0
        no_trade = 0
        for cursor, bar in enumerate(candidates[:-1]):
            decision_time = bar["timestamp"]
            next_time = candidates[cursor + 1]["timestamp"]
            event_index = _event_index(event_times, decision_time)
            next_index = _event_index(event_times, next_time)
            current = events[event_index]["_after"] if event_index >= 0 else 0.0
            next_target = events[next_index]["_after"] if next_index >= 0 else 0.0
            action = _action(current, next_target)
            base = events[event_index] if event_index >= 0 else events[0]
            features = precomputed[decision_time]
            status = "PASS" if all(features.get(name) is not None for name in ("feature_rsi_14", "feature_macd_histogram", "feature_bollinger_percent_b_20", "feature_volume_percentile_72bar")) and features.get("feature_market_data_available") else ("WARMUP_INSUFFICIENT" if features.get("feature_latest_bar_time") else "MISSING_MARKET_DATA")
            if action == "NO_TRADE":
                no_trade += 1
            row = dict(base)
            row.pop("_time", None)
            row.pop("_before", None)
            row.pop("_after", None)
            row.update({
                "decision_episode_id": _stable_id(key, decision_time),
                "decision_time": iso_time(decision_time),
                "decision_type": "BAR_CLOCK",
                "observed_action": "NO_TRADE" if action == "NO_TRADE" else str(base.get("observed_action") or "NO_TRADE"),
                "observed_position_before_contracts": current,
                "observed_target_position_contracts": current,
                "observed_position_delta_contracts": 0.0,
                "synthetic_negative_sample": False,
                "observed_overall_confidence": "HIGH" if event_index >= 0 else "LOW",
                "market_coverage_status": status,
                "position_scale_fit_available": True,
                "model_eligible": status == "PASS",
                "feature_latest_bar_time": features.get("feature_latest_bar_time", ""),
                "feature_market_data_available": features.get("feature_market_data_available", False),
                "feature_mark_index_missing": features.get("feature_mark_index_missing", True),
                "feature_funding_source_time": features.get("feature_funding_source_time", ""),
                "feature_funding_rate_missing": features.get("feature_funding_rate") is None,
                "feature_mark_index_basis_missing": features.get("feature_mark_index_basis") is None,
                "row_market_coverage_status": status,
                "raw_current_position_contracts": current,
                "raw_target_position_contracts": current,
                "raw_next_target_position_contracts": next_target,
                "label_next_decision_time": iso_time(next_time),
                "label_next_target_position_contracts": next_target,
                "label_next_target_exposure": next_target / scale,
                "label_next_action": action,
                "label_next_position_delta_bucket": "ZERO" if action == "NO_TRADE" else "NONZERO",
                "label_time_to_next_action_seconds": (next_time - decision_time).total_seconds(),
                "label_status": "AVAILABLE",
                "dataset_split": "",
                "source_order_id": "",
                "source_fill_id": "",
                "source_fill_price": "",
                "source_fee": "",
                "source_fee_currency": "",
                "temporal_row_type": "NO_TRADE" if action == "NO_TRADE" else "NEXT_BAR_TRANSITION",
                "temporal_source_event_count_before": max(0, event_index + 1),
                **features,
                **_dynamic_state(events, event_index, decision_time, current, scale),
            })
            if row_sink is None:
                rows.append(row)
            else:
                row_sink(row)
            produced += 1
            eligible += status == "PASS"
        coverage.append({"state_key": key, "event_rows": len(events), "market_bars": len(market), "temporal_rows": produced, "eligible_rows": eligible, "no_trade_rows": no_trade, "first_decision_time": iso_time(candidates[0]["timestamp"]), "last_decision_time": iso_time(candidates[-2]["timestamp"]), "status": "PASS" if produced else "INSUFFICIENT_OVERLAP"})
    rows.sort(key=lambda row: (str(row.get("decision_time")), str(row.get("source_venue")), str(row.get("canonical_asset")), str(row.get("decision_episode_id"))))
    return rows, {"coverage": coverage}


def write_csv(path: Path, rows: Iterable[Mapping[str, Any]]) -> None:
    rows = list(rows)
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(*, input_path: Path = INPUT_DATASET, market_path: Path = MARKET_CONTEXT, output_path: Path = DEFAULT_OUTPUT, manifest_path: Path = DEFAULT_MANIFEST) -> dict[str, Any]:
    if not input_path.exists():
        raise FileNotFoundError(input_path)
    if not market_path.exists():
        raise FileNotFoundError(market_path)
    events = load_events(input_path)
    market = load_bitmex_market(market_path)
    market.update(load_hyperliquid_market(HL_ROOT))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    stream_count = 0
    stream_writer: csv.DictWriter[str] | None = None
    stream_handle = output_path.open("w", encoding="utf-8", newline="")

    def sink(row: dict[str, Any]) -> None:
        nonlocal stream_count, stream_writer
        if stream_writer is None:
            fieldnames = list(row.keys())
            stream_writer = csv.DictWriter(stream_handle, fieldnames=fieldnames, extrasaction="ignore")
            stream_writer.writeheader()
        stream_writer.writerow(row)
        stream_count += 1

    try:
        _, coverage_doc = build_rows(events, market, row_sink=sink)
    finally:
        stream_handle.close()
    statuses = Counter(str(item.get("status")) for item in coverage_doc["coverage"])
    eligible_count = sum(int(item.get("eligible_rows") or 0) for item in coverage_doc["coverage"])
    no_trade_count = sum(int(item.get("no_trade_rows") or 0) for item in coverage_doc["coverage"])
    report = {
        "report_version": "M15-TEMPORAL-DATASET-1.0",
        "status": "PASS" if stream_count else "BLOCKED",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "clock_contract": "one row per available closed 1h market bar; label is the next hourly state transition",
        "input_dataset": str(input_path.relative_to(ROOT)),
        "input_dataset_sha256": sha256(input_path),
        "market_context": str(market_path.relative_to(ROOT)),
        "market_context_sha256": sha256(market_path),
        "hyperliquid_revision": sorted(path.name for path in HL_ROOT.iterdir() if path.is_dir())[-1] if HL_ROOT.exists() and any(path.is_dir() for path in HL_ROOT.iterdir()) else "MISSING",
        "frozen_cutoff": iso_time(FROZEN_CUTOFF),
        "source_event_groups": len(events),
        "market_groups": len(market),
        "temporal_rows": stream_count,
        "model_eligible_rows": eligible_count,
        "no_trade_rows": no_trade_count,
        "no_trade_rate": no_trade_count / stream_count if stream_count else None,
        "coverage_status_counts": dict(statuses),
        "coverage": coverage_doc["coverage"],
        "causal_rules": [
            "market features use build_market_features with bar_end < decision_time",
            "state uses only events strictly earlier than decision_time",
            "labels use only the next strictly later market-clock timestamp",
            "raw source files are read-only and are never rewritten",
        ],
        "output_order": "deterministic state-key order, then chronological market-clock order within each state key",
        "output": str(output_path.relative_to(ROOT)),
        "large_output": True,
        "analysis_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
    }
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT_DATASET)
    parser.add_argument("--market", type=Path, default=MARKET_CONTEXT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    args = parser.parse_args()
    try:
        result = build(input_path=args.input.resolve(), market_path=args.market.resolve(), output_path=args.output.resolve(), manifest_path=args.manifest.resolve())
    except (FileNotFoundError, OSError, ValueError, subprocess.CalledProcessError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "TEMPORAL_DATASET_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": result["status"], "temporal_rows": result["temporal_rows"], "eligible_rows": result["model_eligible_rows"], "no_trade_rate": result["no_trade_rate"], "manifest": str(args.manifest)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
