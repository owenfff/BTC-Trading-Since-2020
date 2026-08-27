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


def strategy_reason_zh(action: str, current_exposure: Any, target_exposure: Any, features: Mapping[str, Any]) -> str:
    """Create a cautious Chinese explanation from observed model inputs.

    The text describes model inputs and target alignment only.  It never claims
    that the original trader used these indicators.
    """

    current = _number(current_exposure) or 0.0
    target = _number(target_exposure) or 0.0
    phrases: list[str] = []
    rsi = _number(features.get("feature_rsi_14"))
    macd = _number(features.get("feature_macd_histogram"))
    bb = _number(features.get("feature_bollinger_percent_b_20"))
    momentum = _number(features.get("feature_return_24bar"))
    if rsi is not None:
        phrases.append("RSI14处于超卖区" if rsi <= 30 else "RSI14处于超买区" if rsi >= 70 else f"RSI14={rsi:.1f}")
    if macd is not None:
        phrases.append("MACD柱显示多头动能" if macd > 0 else "MACD柱显示空头动能" if macd < 0 else "MACD柱接近零轴")
    if bb is not None:
        phrases.append("价格接近布林带下轨" if bb <= 0.2 else "价格接近布林带上轨" if bb >= 0.8 else f"布林带位置={bb:.2f}")
    if momentum is not None:
        phrases.append("24小时动量为正" if momentum > 0 else "24小时动量为负" if momentum < 0 else "24小时动量接近零")
    if not phrases:
        return "指标覆盖不足，仅依据可用历史行为特征"
    difference = target - current
    if abs(difference) <= 1e-6:
        alignment = "当前仓位已接近模型目标，维持观察"
    elif action.startswith("OPEN"):
        alignment = "当前无仓位，模型目标要求建立仓位"
    elif action.startswith("ADD"):
        alignment = "当前仓位低于模型目标，执行加仓"
    elif action.startswith("REDUCE") or action.startswith("CLOSE"):
        alignment = "当前仓位高于模型目标，执行减仓或平仓"
    elif action.startswith("FLIP"):
        alignment = "模型目标方向与当前仓位相反，执行反手减仓优先"
    else:
        alignment = "模型未给出有效调仓目标"
    return "、".join(phrases[:4]) + "；" + alignment


__all__ = ["strategy_basis_from_features", "strategy_reason_zh"]
