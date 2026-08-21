from __future__ import annotations

from typing import Any

from .base import StrategyInput, StrategySignal, make_signal


def _number(features: dict[str, Any] | Any, key: str, default: float = 0.0) -> float:
    value = features.get(key)
    try:
        return float(value) if value not in (None, "") else default
    except (TypeError, ValueError):
        return default


def _has_value(features: dict[str, Any] | Any, key: str) -> bool:
    return features.get(key) not in (None, "")


class DistilledRuleStrategy:
    """Small, deterministic, auditable strategy approximation.

    This is a behavioral baseline, not a claim of recovered intent or a
    profitable trading rule. It uses only M4 features and emits the shared
    Strategy Core signal contract.
    """

    version = "behavioral-distillation-v1-rules"
    max_abs_exposure = 0.25
    min_signal_exposure = 0.01

    def predict(self, strategy_input: StrategyInput) -> StrategySignal:
        f = strategy_input.features
        current = _number(f, "feature_current_normalized_exposure")
        regime = str(f.get("feature_market_regime") or "UNKNOWN")
        slope = _number(f, "feature_trend_slope_24bar")
        return_24 = _number(f, "feature_return_24bar")
        return_6 = _number(f, "feature_return_6bar")
        volatility = _number(f, "feature_realized_volatility_72bar")
        complete = all(_has_value(f, key) for key in ("feature_return_6bar", "feature_return_24bar", "feature_trend_slope_24bar"))
        tags: list[str] = []
        if not complete:
            tags.append("INSUFFICIENT_MARKET_HISTORY")
        if regime == "UNKNOWN":
            tags.append("UNKNOWN_MARKET_REGIME")
        if str(f.get("feature_mark_index_missing")) in {"True", "true", "1"}:
            tags.append("MARK_INDEX_MISSING")
        if str(f.get("feature_accounting_confidence") or "") in {"LOW", "UNKNOWN"}:
            tags.append("LOW_ACCOUNTING_CONFIDENCE")

        bullish = regime in {"UPTREND", "TREND_UP"} or (slope > 0 and return_24 > 0)
        bearish = regime in {"DOWNTREND", "TREND_DOWN"} or (slope < 0 and return_24 < 0)
        confidence = 0.40
        if complete:
            confidence += 0.15
        if regime in {"UPTREND", "DOWNTREND", "RANGE", "TREND_UP", "TREND_DOWN", "RANGE_OR_MIXED"}:
            confidence += 0.10
        confidence = min(0.80, confidence + min(abs(return_6) * 2.0, 0.15))
        if volatility > 0.05:
            tags.append("HIGH_VOLATILITY")
            confidence -= 0.10

        if not complete or regime == "UNKNOWN":
            action = "HOLD_LONG" if current > 0 else "HOLD_SHORT" if current < 0 else "NO_TRADE"
            return make_signal(strategy_input.decision_time, target_exposure=current, action=action, confidence=0.25, risk_tags=tuple(tags))

        if abs(current) < self.min_signal_exposure:
            if bullish and not bearish:
                target = self.max_abs_exposure * min(1.0, max(0.25, abs(return_24) * 8.0))
                return make_signal(strategy_input.decision_time, target_exposure=target, action="OPEN_LONG", confidence=confidence, risk_tags=tuple(tags))
            if bearish and not bullish:
                target = -self.max_abs_exposure * min(1.0, max(0.25, abs(return_24) * 8.0))
                return make_signal(strategy_input.decision_time, target_exposure=target, action="OPEN_SHORT", confidence=confidence, risk_tags=tuple(tags))
            return make_signal(strategy_input.decision_time, target_exposure=0.0, action="NO_TRADE", confidence=confidence * 0.8, risk_tags=tuple(tags))

        if current > 0:
            if bearish:
                action = "CLOSE_LONG" if abs(current) <= 0.05 else "REDUCE_LONG"
                target = 0.0 if action == "CLOSE_LONG" else current * 0.5
                return make_signal(strategy_input.decision_time, target_exposure=target, action=action, confidence=confidence, risk_tags=tuple(tags))
            if bullish and current < self.max_abs_exposure * 0.8:
                target = min(self.max_abs_exposure, current + self.max_abs_exposure * 0.25)
                return make_signal(strategy_input.decision_time, target_exposure=target, action="ADD_LONG", confidence=confidence, risk_tags=tuple(tags))
            return make_signal(strategy_input.decision_time, target_exposure=current, action="HOLD_LONG", confidence=confidence * 0.9, risk_tags=tuple(tags))

        if bullish:
            action = "CLOSE_SHORT" if abs(current) <= 0.05 else "REDUCE_SHORT"
            target = 0.0 if action == "CLOSE_SHORT" else current * 0.5
            return make_signal(strategy_input.decision_time, target_exposure=target, action=action, confidence=confidence, risk_tags=tuple(tags))
        if bearish and abs(current) < self.max_abs_exposure * 0.8:
            target = max(-self.max_abs_exposure, current - self.max_abs_exposure * 0.25)
            return make_signal(strategy_input.decision_time, target_exposure=target, action="ADD_SHORT", confidence=confidence, risk_tags=tuple(tags))
        return make_signal(strategy_input.decision_time, target_exposure=current, action="HOLD_SHORT", confidence=confidence * 0.9, risk_tags=tuple(tags))
