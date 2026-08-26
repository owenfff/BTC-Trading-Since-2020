"""Deterministic, causal technical indicators shared by offline and runtime code."""

from __future__ import annotations

import math
from statistics import pstdev
from typing import Any, Sequence


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _ema(values: Sequence[float], period: int) -> list[float]:
    if not values or period <= 0:
        return []
    alpha = 2.0 / (period + 1.0)
    result = [float(values[0])]
    for value in values[1:]:
        result.append(alpha * float(value) + (1.0 - alpha) * result[-1])
    return result


def _rsi(closes: Sequence[float], period: int = 14) -> float | None:
    if len(closes) < period + 1:
        return None
    changes = [closes[index] - closes[index - 1] for index in range(1, len(closes))]
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


def calculate_technical_indicators(
    closes: Sequence[Any],
    highs: Sequence[Any] | None = None,
    lows: Sequence[Any] | None = None,
    volumes: Sequence[Any] | None = None,
) -> dict[str, float | None]:
    """Calculate indicators using only the supplied, already closed bars.

    Missing or non-finite observations remain ``None``.  The caller is
    responsible for ensuring the supplied rows are as-of the decision time.
    """

    # The live engine retains 100 closed bars.  Limiting the offline window to
    # the same amount keeps training/runtime calculations identical and avoids
    # re-scanning the complete history for every decision row.
    window_size = 100
    close_values = [_finite(value) for value in closes[-window_size:]]
    high_values = [_finite(value) for value in (highs or ())[-window_size:]]
    low_values = [_finite(value) for value in (lows or ())[-window_size:]]
    volume_values = [_finite(value) for value in (volumes or ())[-window_size:]]
    result: dict[str, float | None] = {
        "feature_rsi_14": None,
        "feature_macd_line_12_26": None,
        "feature_macd_signal_9": None,
        "feature_macd_histogram": None,
        "feature_bollinger_zscore_20": None,
        "feature_bollinger_percent_b_20": None,
        "feature_volume_percentile_72bar": None,
    }
    if not close_values or any(value is None or value <= 0 for value in close_values):
        return result
    clean_closes = [float(value) for value in close_values if value is not None]
    result["feature_rsi_14"] = _rsi(clean_closes, 14)

    if len(clean_closes) >= 26:
        fast = _ema(clean_closes, 12)
        slow = _ema(clean_closes, 26)
        macd = [fast[index] - slow[index] for index in range(len(clean_closes))]
        result["feature_macd_line_12_26"] = macd[-1]
        if len(macd) >= 34:
            signal = _ema(macd[25:], 9)
            result["feature_macd_signal_9"] = signal[-1]
            result["feature_macd_histogram"] = macd[-1] - signal[-1]

    if len(clean_closes) >= 20:
        window = clean_closes[-20:]
        mean = sum(window) / len(window)
        deviation = pstdev(window)
        if deviation > 0:
            result["feature_bollinger_zscore_20"] = (window[-1] - mean) / deviation
            lower = mean - 2.0 * deviation
            upper = mean + 2.0 * deviation
            result["feature_bollinger_percent_b_20"] = (window[-1] - lower) / (upper - lower)

    if len(volume_values) >= 72 and all(value is not None and value >= 0 for value in volume_values[-72:]):
        volume_window = [float(value) for value in volume_values[-72:] if value is not None]
        result["feature_volume_percentile_72bar"] = sum(value <= volume_window[-1] for value in volume_window) / len(volume_window)
    return result


__all__ = ["calculate_technical_indicators"]
