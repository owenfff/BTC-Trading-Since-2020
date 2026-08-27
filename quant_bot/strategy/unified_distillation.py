from __future__ import annotations

"""One shared, venue-neutral behavioral policy with deterministic heads.

The model deliberately learns intent from normalized features.  Exchange and
instrument units remain outside this module and are handled by the venue
adapter/order planner.
"""

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import numpy as np

from .base import StrategyInput, StrategySignal, make_signal
from .explanations import strategy_reason_zh
from .feature_contract import UNIFIED_FEATURE_CONTRACT_VERSION, parse_float
from .signal_contract import action_family
from .supervised_models import CATEGORICAL_FEATURES, FeatureEncoder, NUMERIC_FEATURES, _softmax


UNIFIED_MODEL_VERSION = "behavioral-distillation-v4.6-unified-distillation"
UNIFIED_CATEGORICAL_FEATURES = tuple(key for key in CATEGORICAL_FEATURES if key != "feature_symbol")

IDLE_ACTIONS = frozenset({"NO_TRADE", "HOLD_LONG", "HOLD_SHORT", ""})
FAMILY_ACTIONS = ("ADD", "CLOSE", "FLIP", "OPEN", "REDUCE")
DIRECTION_ACTIONS = ("LONG", "SHORT")


def _finite(value: Any, default: float = 0.0) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if np.isfinite(result) else default


def _family(action: Any) -> str:
    text = str(action or "").upper()
    return "NO_TRADE" if text in IDLE_ACTIONS or not text else action_family(text)


def _direction(action: Any, current: float = 0.0, target: float = 0.0) -> str:
    text = str(action or "").upper()
    if text.endswith("LONG"):
        return "LONG"
    if text.endswith("SHORT"):
        return "SHORT"
    if target > 0 or (target == 0 and current > 0):
        return "LONG"
    return "SHORT"


def transition_action(current: float, target: float, *, epsilon: float = 1e-6) -> str:
    """Derive an executable action from the shared target exposure."""

    current = float(current)
    target = float(target)
    if abs(target - current) <= epsilon:
        return "HOLD_LONG" if current > epsilon else "HOLD_SHORT" if current < -epsilon else "NO_TRADE"
    if abs(current) <= epsilon:
        return "OPEN_LONG" if target > 0 else "OPEN_SHORT"
    if abs(target) <= epsilon:
        return "CLOSE_LONG" if current > 0 else "CLOSE_SHORT"
    if (current > 0) != (target > 0):
        return "FLIP_LONG_TO_SHORT" if target < 0 else "FLIP_SHORT_TO_LONG"
    if abs(target) > abs(current):
        return "ADD_LONG" if target > 0 else "ADD_SHORT"
    return "REDUCE_LONG" if target > 0 else "REDUCE_SHORT"


@dataclass
class _LinearHead:
    actions: list[str]
    weights: np.ndarray | None = None
    bias: np.ndarray | None = None

    def fit(self, matrix: np.ndarray, labels: list[str], sample_weights: np.ndarray, *, epochs: int = 80, learning_rate: float = 0.12, l2: float = 1e-3) -> "_LinearHead":
        self.actions = list(dict.fromkeys(labels))
        if not self.actions:
            raise ValueError("linear head requires labels")
        index = {name: position for position, name in enumerate(self.actions)}
        encoded = np.asarray([index[name] for name in labels], dtype=int)
        self.weights = np.zeros((matrix.shape[1], len(self.actions)), dtype=float)
        self.bias = np.zeros(len(self.actions), dtype=float)
        weights = np.asarray(sample_weights, dtype=float)
        weights = np.maximum(weights, 1e-9)
        normalizer = max(float(weights.sum()), 1e-9)
        one_hot = np.eye(len(self.actions), dtype=float)[encoded]
        for _ in range(max(1, int(epochs))):
            probabilities = _softmax(matrix @ self.weights + self.bias)
            error = (probabilities - one_hot) * weights[:, None]
            self.weights -= learning_rate * ((matrix.T @ error) / normalizer + l2 * self.weights)
            self.bias -= learning_rate * error.sum(axis=0) / normalizer
        return self

    def predict_proba(self, vector: np.ndarray) -> np.ndarray:
        if self.weights is None or self.bias is None:
            raise RuntimeError("linear head is not fitted")
        return _softmax(vector.reshape(1, -1) @ self.weights + self.bias)[0]

    def to_dict(self) -> dict[str, Any]:
        if self.weights is None or self.bias is None:
            raise RuntimeError("cannot serialize an unfitted linear head")
        return {"actions": list(self.actions), "weights": self.weights.tolist(), "bias": self.bias.tolist()}

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "_LinearHead":
        head = cls(
            actions=[str(item) for item in payload.get("actions", [])],
            weights=np.asarray(payload.get("weights", []), dtype=float),
            bias=np.asarray(payload.get("bias", []), dtype=float),
        )
        if not head.actions or head.weights.ndim != 2 or head.bias.ndim != 1:
            raise ValueError("invalid unified model head")
        if head.weights.shape[1] != len(head.actions) or head.bias.shape[0] != len(head.actions):
            raise ValueError("unified model head dimensions do not match actions")
        return head


class UnifiedDistilledStrategy:
    """Single shared intent policy for BitMEX/Hyperliquid-derived behavior."""

    version = UNIFIED_MODEL_VERSION

    def __init__(self, *, epochs: int = 80, learning_rate: float = 0.12, l2: float = 1e-3, target_l2: float = 1.0, action_threshold: float = 0.5) -> None:
        if target_l2 < 0:
            raise ValueError("target_l2 must be non-negative")
        if not 0.0 <= action_threshold <= 1.0:
            raise ValueError("action_threshold must be in [0, 1]")
        self.epochs = epochs
        self.learning_rate = learning_rate
        self.l2 = l2
        self.target_l2 = target_l2
        self.action_threshold = action_threshold
        self.encoder = FeatureEncoder()
        self.timing_head = _LinearHead([])
        self.family_head = _LinearHead([])
        self.direction_head = _LinearHead([])
        self.target_coef: np.ndarray | None = None
        self.fit_row_count = 0
        self.ambiguous_row_count = 0
        self.calibration_row_count = 0

    @staticmethod
    def _vectors(encoder: FeatureEncoder, rows: list[Mapping[str, Any]]) -> np.ndarray:
        if not rows:
            raise ValueError("unified model requires rows")
        first = encoder.transform(rows[0])
        matrix = np.empty((len(rows), first.shape[0]), dtype=float)
        matrix[0] = first
        for index, row in enumerate(rows[1:], start=1):
            matrix[index] = encoder.transform(row)
        return matrix

    @staticmethod
    def _weighted_ridge(matrix: np.ndarray, targets: np.ndarray, weights: np.ndarray, l2: float) -> np.ndarray:
        augmented = np.column_stack([np.ones(matrix.shape[0]), matrix])
        diagonal = np.eye(augmented.shape[1], dtype=float) * max(0.0, l2)
        diagonal[0, 0] = 0.0
        weighted = augmented * weights[:, None]
        gram = augmented.T @ weighted + diagonal
        rhs = augmented.T @ (weights * targets)
        try:
            return np.linalg.solve(gram, rhs)
        except np.linalg.LinAlgError:
            return np.linalg.pinv(gram) @ rhs

    @staticmethod
    def _row_weight(row: Mapping[str, Any]) -> float:
        return max(1e-9, _finite(row.get("_unified_sample_weight"), 1.0))

    def fit(self, rows: Iterable[Mapping[str, Any]]) -> "UnifiedDistilledStrategy":
        source = [dict(row) for row in rows if str(row.get("label_status", "")) == "AVAILABLE" and str(row.get("label_next_action", "")) and str(row.get("_unified_fit_eligible", "true")).lower() == "true"]
        if not source:
            raise ValueError("UnifiedDistilledStrategy requires labelled rows")
        self.encoder.fit(source)
        # Raw venue symbols are source identifiers, not portable predictive
        # features.  Keep instrument/settlement/regime categories but remove
        # the source symbol category so unseen OKX/Binance symbols map safely.
        self.encoder.categorical_features = UNIFIED_CATEGORICAL_FEATURES
        self.encoder.categories.pop("feature_symbol", None)
        matrix = self._vectors(self.encoder, source)
        weights = np.asarray([self._row_weight(row) for row in source], dtype=float)
        timing_labels = ["NO_TRADE" if _family(row.get("label_next_action")) == "NO_TRADE" else "ACTION" for row in source]
        self.timing_head.fit(matrix, timing_labels, weights, epochs=self.epochs, learning_rate=self.learning_rate, l2=self.l2)
        active_indices = [index for index, row in enumerate(source) if _family(row.get("label_next_action")) != "NO_TRADE"]
        if not active_indices:
            raise ValueError("UnifiedDistilledStrategy requires non-idle labelled rows")
        active_matrix = matrix[active_indices]
        active_weights = weights[active_indices]
        active_rows = [source[index] for index in active_indices]
        self.family_head.fit(active_matrix, [_family(row.get("label_next_action")) for row in active_rows], active_weights, epochs=self.epochs, learning_rate=self.learning_rate, l2=self.l2)
        self.direction_head.fit(active_matrix, [_direction(row.get("label_next_action"), _finite(row.get("feature_current_normalized_exposure")), _finite(row.get("label_next_target_exposure"))) for row in active_rows], active_weights, epochs=self.epochs, learning_rate=self.learning_rate, l2=self.l2)
        targets = np.asarray([max(-1.0, min(1.0, _finite(row.get("label_next_target_exposure"), _finite(row.get("feature_current_normalized_exposure"))))) for row in source], dtype=float)
        self.target_coef = self._weighted_ridge(matrix, targets, weights, self.target_l2)
        self.fit_row_count = len(source)
        self.ambiguous_row_count = sum(str(row.get("label_ambiguity", "false")).lower() == "true" for row in source)
        return self

    def _target(self, vector: np.ndarray) -> float:
        if self.target_coef is None:
            raise RuntimeError("UnifiedDistilledStrategy must be fit before predict")
        return float(np.clip(np.concatenate(([1.0], vector)) @ self.target_coef, -1.0, 1.0))

    def calibrate_action_threshold(self, rows: Iterable[Mapping[str, Any]], *, candidates: Iterable[float] = tuple(index / 100 for index in range(10, 91, 5))) -> dict[str, Any]:
        source = [dict(row) for row in rows if str(row.get("label_status", "")) == "AVAILABLE" and str(row.get("label_next_action", ""))]
        if not source:
            raise ValueError("threshold calibration requires labelled rows")
        observed = sum(_family(row.get("label_next_action")) != "NO_TRADE" for row in source) / len(source)
        matrix = self._vectors(self.encoder, source)
        probabilities = np.asarray([self.timing_head.predict_proba(vector)[self.timing_head.actions.index("ACTION")] if "ACTION" in self.timing_head.actions else 0.0 for vector in matrix])
        best = min(((abs(float((probabilities >= threshold).mean()) - observed), float(threshold), float((probabilities >= threshold).mean())) for threshold in candidates), key=lambda item: (item[0], item[1]))
        self.action_threshold = best[1]
        self.calibration_row_count = len(source)
        return {"calibration_rows": len(source), "observed_action_rate": observed, "selected_threshold": best[1], "predicted_action_rate": best[2]}

    def predict(self, strategy_input: StrategyInput) -> StrategySignal:
        vector = self.encoder.transform(strategy_input.features)
        timing = self.timing_head.predict_proba(vector)
        action_probability = timing[self.timing_head.actions.index("ACTION")] if "ACTION" in self.timing_head.actions else 0.0
        current = float(np.clip(strategy_input.current_strategy_position, -1.0, 1.0))
        tags = ["UNIFIED_SHARED_INTENT", "VENUE_NEUTRAL_NORMALIZED_EXPOSURE"]
        if str(strategy_input.features.get("feature_mark_index_missing", "")).lower() in {"true", "1"} or str(strategy_input.features.get("feature_mark_index_basis_missing", "")).lower() in {"true", "1"}:
            tags.append("MARK_INDEX_MISSING")
        if str(strategy_input.features.get("feature_funding_rate_missing", "")).lower() in {"true", "1"}:
            tags.append("FUNDING_MISSING")
        if action_probability < self.action_threshold:
            action = transition_action(current, current)
            tags.append("ACTION_PROBABILITY_BELOW_THRESHOLD")
            return make_signal(strategy_input.decision_time, target_exposure=current, action=action, confidence=float(max(0.0, 1.0 - action_probability)), risk_tags=tuple(tags), strategy_version=self.version, strategy_reason_zh=strategy_reason_zh(action, current, current, strategy_input.features))
        family_probabilities = self.family_head.predict_proba(vector)
        direction_probabilities = self.direction_head.predict_proba(vector)
        predicted_family = self.family_head.actions[int(np.argmax(family_probabilities))]
        predicted_direction = self.direction_head.actions[int(np.argmax(direction_probabilities))]
        target = self._target(vector)
        action = transition_action(current, target)
        actual_family = _family(action)
        if actual_family != predicted_family and actual_family != "NO_TRADE":
            tags.append("FAMILY_TARGET_DISAGREEMENT")
        tags.extend((f"PREDICTED_FAMILY={predicted_family}", f"PREDICTED_DIRECTION={predicted_direction}"))
        confidence = float(np.clip(action_probability * float(family_probabilities.max()) * float(direction_probabilities.max()), 0.0, 1.0))
        return make_signal(strategy_input.decision_time, target_exposure=target, action=action, confidence=confidence, risk_tags=tuple(tags), strategy_version=self.version, strategy_reason_zh=strategy_reason_zh(action, current, target, strategy_input.features))

    def to_dict(self) -> dict[str, Any]:
        if self.target_coef is None:
            raise RuntimeError("cannot serialize an unfitted unified strategy")
        return {
            "model_type": "UnifiedDistilledStrategy",
            "version": self.version,
            "epochs": self.epochs,
            "learning_rate": self.learning_rate,
            "l2": self.l2,
            "target_l2": self.target_l2,
            "action_threshold": self.action_threshold,
            "fit_row_count": self.fit_row_count,
            "ambiguous_row_count": self.ambiguous_row_count,
            "calibration_row_count": self.calibration_row_count,
            "timing_head": self.timing_head.to_dict(),
            "family_head": self.family_head.to_dict(),
            "direction_head": self.direction_head.to_dict(),
            "target_coef": self.target_coef.tolist(),
            "encoder": self.encoder.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "UnifiedDistilledStrategy":
        if payload.get("model_type") != "UnifiedDistilledStrategy":
            raise ValueError("unsupported unified deployment model type")
        model = cls(
            epochs=int(payload.get("epochs", 80)),
            learning_rate=float(payload.get("learning_rate", 0.12)),
            l2=float(payload.get("l2", 1e-3)),
            target_l2=float(payload.get("target_l2", 1.0)),
            action_threshold=float(payload.get("action_threshold", 0.5)),
        )
        model.version = str(payload.get("version", cls.version))
        model.fit_row_count = int(payload.get("fit_row_count", 0))
        model.ambiguous_row_count = int(payload.get("ambiguous_row_count", 0))
        model.calibration_row_count = int(payload.get("calibration_row_count", 0))
        model.timing_head = _LinearHead.from_dict(payload.get("timing_head", {}))
        model.family_head = _LinearHead.from_dict(payload.get("family_head", {}))
        model.direction_head = _LinearHead.from_dict(payload.get("direction_head", {}))
        model.target_coef = np.asarray(payload.get("target_coef", []), dtype=float)
        model.encoder = FeatureEncoder.from_dict(payload.get("encoder", {}))
        if model.target_coef.ndim != 1 or model.target_coef.shape[0] != model.timing_head.weights.shape[0] + 1:
            raise ValueError("unified target regression dimensions do not match encoder")
        return model


__all__ = ["UNIFIED_FEATURE_CONTRACT_VERSION", "UNIFIED_MODEL_VERSION", "UnifiedDistilledStrategy", "transition_action"]
