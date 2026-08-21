"""Market features whose observation timestamps are strictly before a decision."""

from __future__ import annotations

import csv
import math
from bisect import bisect_left
from datetime import datetime, timezone
from pathlib import Path
from statistics import pstdev
from typing import Any, Iterable


UTC = timezone.utc
BAR_SECONDS = 5 * 60
RETURN_LAGS = (1, 3, 6, 12, 24, 72)


def parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso_utc(value: datetime | None) -> str:
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z") if value else ""


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_market_context(path: Path, *, symbol: str = "XBTUSD") -> list[dict[str, Any]]:
    """Load only the compact fields needed for as-of features."""
    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        for source in csv.DictReader(handle):
            if str(source.get("symbol", "")).upper() != symbol.upper():
                continue
            timestamp = parse_utc(source.get("timestamp"))
            if timestamp is None:
                continue
            rows.append({
                "timestamp": timestamp,
                "timestamp_utc": iso_utc(timestamp),
                "open": _number(source.get("open")),
                "high": _number(source.get("high")),
                "low": _number(source.get("low")),
                "close": _number(source.get("close")),
                "volume": _number(source.get("volume")),
                "turnover": _number(source.get("turnover")),
                "mark_price": _number(source.get("mark_price")),
                "index_price": _number(source.get("index_price")),
                "funding_rate": _number(source.get("funding_rate")),
                "funding_source_time": parse_utc(source.get("funding_source_timestamp_utc")),
            })
    rows.sort(key=lambda row: row["timestamp"])
    return rows


def _complete_window(rows: list[dict[str, Any]], start: int, end: int) -> bool:
    if start < 0 or end >= len(rows) or start > end:
        return False
    for index in range(start + 1, end + 1):
        if (rows[index]["timestamp"] - rows[index - 1]["timestamp"]).total_seconds() != BAR_SECONDS:
            return False
    return all(rows[index].get("close") is not None for index in range(start, end + 1))


def _log_returns(rows: list[dict[str, Any]], index: int, count: int) -> list[float] | None:
    start = index - count + 1
    if start < 1 or not _complete_window(rows, start - 1, index):
        return None
    values: list[float] = []
    for cursor in range(start, index + 1):
        previous = rows[cursor - 1].get("close")
        current = rows[cursor].get("close")
        if previous is None or current is None or previous <= 0 or current <= 0:
            return None
        values.append(math.log(current / previous))
    return values


def _safe_mean(values: Iterable[float]) -> float | None:
    values = list(values)
    return sum(values) / len(values) if values else None


def _asof_index(rows: list[dict[str, Any]], decision_time: datetime, timestamps: list[datetime] | None = None) -> int:
    return bisect_left(timestamps if timestamps is not None else [row["timestamp"] for row in rows], decision_time) - 1


def build_market_features(rows: list[dict[str, Any]], decision_time: datetime, *, timestamps: list[datetime] | None = None) -> dict[str, Any]:
    """Build features using only bars with ``bar_end < decision_time``."""
    index = _asof_index(rows, decision_time, timestamps)
    output: dict[str, Any] = {
        "feature_latest_bar_time": "",
        "feature_market_data_available": False,
        "feature_mark_index_missing": True,
        "feature_funding_source_time": "",
    }
    for lag in RETURN_LAGS:
        output[f"feature_return_{lag}bar"] = None
    output.update({
        "feature_realized_volatility_72bar": None,
        "feature_atr_14bar": None,
        "feature_volume_change_1bar": None,
        "feature_volume_percentile_72bar": None,
        "feature_ma_distance_24bar": None,
        "feature_trend_slope_24bar": None,
        "feature_distance_rolling_high_72bar": None,
        "feature_distance_rolling_low_72bar": None,
        "feature_funding_rate": None,
        "feature_mark_index_basis": None,
        "feature_market_regime": "UNKNOWN",
        "feature_time_of_day_fraction": decision_time.hour / 24 + decision_time.minute / 1440 + decision_time.second / 86400,
        "feature_day_of_week": decision_time.weekday(),
        "feature_day_of_week_sin": math.sin(2 * math.pi * decision_time.weekday() / 7),
        "feature_day_of_week_cos": math.cos(2 * math.pi * decision_time.weekday() / 7),
    })
    if index < 0:
        return output

    current = rows[index]
    close = current.get("close")
    if close is None or close <= 0:
        return output
    output["feature_latest_bar_time"] = iso_utc(current["timestamp"])
    output["feature_market_data_available"] = True

    for lag in RETURN_LAGS:
        if index - lag >= 0 and _complete_window(rows, index - lag, index):
            previous = rows[index - lag].get("close")
            if previous and previous > 0:
                output[f"feature_return_{lag}bar"] = close / previous - 1.0

    log_returns = _log_returns(rows, index, 72)
    if log_returns:
        output["feature_realized_volatility_72bar"] = pstdev(log_returns)

    atr_start = index - 13
    if _complete_window(rows, atr_start - 1, index) and atr_start >= 1:
        ranges: list[float] = []
        for cursor in range(atr_start, index + 1):
            high = rows[cursor].get("high")
            low = rows[cursor].get("low")
            previous_close = rows[cursor - 1].get("close")
            if high is None or low is None or previous_close is None:
                ranges = []
                break
            ranges.append(max(high - low, abs(high - previous_close), abs(low - previous_close)))
        output["feature_atr_14bar"] = _safe_mean(ranges)

    previous_volume = rows[index - 1].get("volume") if index > 0 and _complete_window(rows, index - 1, index) else None
    if previous_volume and previous_volume > 0 and current.get("volume") is not None:
        output["feature_volume_change_1bar"] = current["volume"] / previous_volume - 1.0

    volume_start = index - 71
    if volume_start >= 0 and _complete_window(rows, volume_start, index):
        volumes = [row.get("volume") for row in rows[volume_start:index + 1]]
        if all(value is not None for value in volumes):
            output["feature_volume_percentile_72bar"] = sum(value <= current["volume"] for value in volumes) / len(volumes)

    ma_start = index - 23
    if ma_start >= 0 and _complete_window(rows, ma_start, index):
        closes = [rows[cursor].get("close") for cursor in range(ma_start, index + 1)]
        if all(value is not None and value > 0 for value in closes):
            mean_close = sum(closes) / len(closes)
            output["feature_ma_distance_24bar"] = close / mean_close - 1.0
            log_closes = [math.log(value) for value in closes]
            x_mean = (len(log_closes) - 1) / 2
            denominator = sum((cursor - x_mean) ** 2 for cursor in range(len(log_closes)))
            output["feature_trend_slope_24bar"] = sum((cursor - x_mean) * (value - sum(log_closes) / len(log_closes)) for cursor, value in enumerate(log_closes)) / denominator if denominator else None

    rolling_start = index - 71
    if rolling_start >= 0 and _complete_window(rows, rolling_start, index):
        highs = [rows[cursor].get("high") for cursor in range(rolling_start, index + 1)]
        lows = [rows[cursor].get("low") for cursor in range(rolling_start, index + 1)]
        if all(value is not None for value in highs) and max(highs) > 0:
            output["feature_distance_rolling_high_72bar"] = close / max(highs) - 1.0
        if all(value is not None for value in lows) and min(lows) > 0:
            output["feature_distance_rolling_low_72bar"] = close / min(lows) - 1.0

    funding_source_time = current.get("funding_source_time")
    if funding_source_time is not None and funding_source_time <= decision_time:
        output["feature_funding_source_time"] = iso_utc(funding_source_time)
        output["feature_funding_rate"] = current.get("funding_rate")
    mark = current.get("mark_price")
    index_price = current.get("index_price")
    if mark is not None and index_price is not None and index_price > 0:
        output["feature_mark_index_missing"] = False
        output["feature_mark_index_basis"] = mark / index_price - 1.0

    slope = output.get("feature_trend_slope_24bar")
    ma_distance = output.get("feature_ma_distance_24bar")
    if slope is not None and ma_distance is not None:
        if slope > 0.0001 and ma_distance > 0:
            output["feature_market_regime"] = "TREND_UP"
        elif slope < -0.0001 and ma_distance < 0:
            output["feature_market_regime"] = "TREND_DOWN"
        else:
            output["feature_market_regime"] = "RANGE_OR_MIXED"
    return output


__all__ = ["BAR_SECONDS", "RETURN_LAGS", "build_market_features", "load_market_context", "parse_utc"]
