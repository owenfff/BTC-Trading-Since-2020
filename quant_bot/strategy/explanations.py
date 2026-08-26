from __future__ import annotations

import math
from typing import Any, Mapping


_BASIS_FIELDS: tuple[tuple[str, str, int], ...] = (
    ("RSI14", "feature_rsi_14", 2),
    ("MACD_HIST", "feature_macd_histogram", 8),
    ("BB_PERCENT_B", "feature_bollinger_percent_b_20", 3),
    ("MOMENTUM_24H", "feature_return_24bar", 4),
    ("MA_DISTANCE_24H", "feature_ma_distance_24bar", 4),
    ("VOLATILITY_72H", "feature_realized_volatility_72bar", 4),
    ("VOLUME_PERCENTILE_72", "feature_volume_percentile_72bar", 3),
    ("FUNDING_RATE", "feature_funding_rate", 8),
    ("MARK_INDEX_BASIS", "feature_mark_index_basis", 8),
)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def strategy_basis_from_features(features: Mapping[str, Any]) -> tuple[str, ...]:
    """Return compact, auditable model-input values for the order panel.

    These are input facts used by the behavioral model, not claims about the
    historical trader's original indicator workflow. Missing values remain
    visible instead of being converted to zero.
    """

    values: list[str] = []
    missing_required = False
    for label, key, decimals in _BASIS_FIELDS:
        value = _number(features.get(key))
        if value is None:
            if key in {"feature_rsi_14", "feature_macd_histogram", "feature_bollinger_percent_b_20", "feature_return_24bar"}:
                missing_required = True
            continue
        values.append(f"{label}={value:.{decimals}f}")
    if missing_required or not values:
        values.append("INDICATORS_INCOMPLETE")
    return tuple(values)


__all__ = ["strategy_basis_from_features"]
