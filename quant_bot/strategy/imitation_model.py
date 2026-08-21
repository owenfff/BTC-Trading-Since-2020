from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any, Iterable

from .base import StrategyInput, StrategySignal, make_signal
from .distilled_rules import _number


def _exposure_bucket(value: float) -> str:
    if value > 0.01:
        return "LONG"
    if value < -0.01:
        return "SHORT"
    return "FLAT"


class HistoricalBehaviorBaseline:
    """Training-only historical frequency baseline.

    It is deliberately simple: action and target exposure means are learned
    from the chronological TRAIN rows only, grouped by prior market regime and
    current exposure sign. It is not an opaque ML model and never sees TEST
    labels during fitting.
    """

    version = "behavioral-distillation-v1-frequency-baseline"

    def __init__(self) -> None:
        self._actions: dict[tuple[str, str], Counter[str]] = defaultdict(Counter)
        self._targets: dict[tuple[str, str], list[float]] = defaultdict(list)
        self._fallback_actions: Counter[str] = Counter()
        self._fallback_targets: list[float] = []
        self.fit_row_count = 0

    @staticmethod
    def _key(row: dict[str, Any]) -> tuple[str, str]:
        regime = str(row.get("feature_market_regime") or "UNKNOWN")
        exposure = _number(row, "feature_current_normalized_exposure")
        return regime, _exposure_bucket(exposure)

    def fit(self, rows: Iterable[dict[str, Any]]) -> "HistoricalBehaviorBaseline":
        for row in rows:
            if row.get("dataset_split") not in {None, "TRAIN"}:
                continue
            action = str(row.get("label_next_action") or "")
            target = row.get("label_next_target_exposure")
            if not action:
                continue
            try:
                target_value = float(target)
            except (TypeError, ValueError):
                continue
            key = self._key(row)
            self._actions[key][action] += 1
            self._targets[key].append(target_value)
            self._fallback_actions[action] += 1
            self._fallback_targets.append(target_value)
            self.fit_row_count += 1
        if not self.fit_row_count:
            raise ValueError("HistoricalBehaviorBaseline requires non-empty TRAIN labels")
        return self

    def predict(self, strategy_input: StrategyInput) -> StrategySignal:
        features = dict(strategy_input.features)
        current = _number(features, "feature_current_normalized_exposure")
        row = {**features, "feature_current_normalized_exposure": current}
        key = self._key(row)
        action_counts = self._actions.get(key) or self._actions.get((key[0], "FLAT")) or self._fallback_actions
        action, count = action_counts.most_common(1)[0]
        targets = self._targets.get(key) or self._targets.get((key[0], "FLAT")) or self._fallback_targets
        target = sum(targets) / len(targets)
        confidence = min(0.95, count / max(1, sum(action_counts.values())))
        tags = ["TRAIN_FREQUENCY_BASELINE"]
        if str(features.get("feature_mark_index_missing")) in {"True", "true", "1"}:
            tags.append("MARK_INDEX_MISSING")
        return make_signal(
            strategy_input.decision_time,
            target_exposure=target,
            action=action,
            confidence=confidence,
            risk_tags=tuple(tags),
            strategy_version=self.version,
        )
