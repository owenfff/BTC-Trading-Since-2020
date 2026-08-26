from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

import numpy as np

from .base import StrategyInput, StrategySignal, make_signal
from .feature_contract import FEATURE_COLUMNS, parse_float


NUMERIC_FEATURES = tuple(
    key
    for key in FEATURE_COLUMNS
    if key.startswith("feature_")
    and key not in {
        "feature_symbol",
        "feature_instrument_class",
        "feature_payout_model",
        "feature_quote_currency",
        "feature_settlement_currency",
        "feature_market_bar_interval",
        "feature_latest_bar_time",
        "feature_funding_source_time",
        "feature_market_regime",
        "feature_latest_action",
        "feature_order_execution_style",
        "feature_ordering_confidence",
        "feature_accounting_confidence",
        "feature_history_last_decision_time",
    }
)
CATEGORICAL_FEATURES = (
    "feature_symbol",
    "feature_instrument_class",
    "feature_payout_model",
    "feature_quote_currency",
    "feature_settlement_currency",
    "feature_market_bar_interval",
    "feature_market_regime",
    "feature_latest_action",
    "feature_order_execution_style",
    "feature_ordering_confidence",
    "feature_accounting_confidence",
)


@dataclass
class FeatureEncoder:
    """Train-only numeric/categorical encoder for the frozen M4 contract."""

    means: dict[str, float] | None = None
    scales: dict[str, float] | None = None
    categories: dict[str, tuple[str, ...]] | None = None
    numeric_features: tuple[str, ...] | None = None
    categorical_features: tuple[str, ...] | None = None

    def fit(self, rows: Iterable[Mapping[str, Any]]) -> "FeatureEncoder":
        rows = list(rows)
        self.means = {}
        self.scales = {}
        self.categories = {}
        self.numeric_features = NUMERIC_FEATURES
        self.categorical_features = CATEGORICAL_FEATURES
        for key in self.numeric_features:
            values = [parse_float(row.get(key)) for row in rows]
            clean = np.array([value for value in values if value is not None and np.isfinite(value)], dtype=float)
            mean = float(clean.mean()) if clean.size else 0.0
            scale = float(clean.std()) if clean.size else 1.0
            self.means[key] = mean
            self.scales[key] = scale if scale > 1e-12 else 1.0
        for key in self.categorical_features:
            values = sorted({str(row.get(key) or "__MISSING__") for row in rows})
            self.categories[key] = tuple(values)
        return self

    def transform(self, features: Mapping[str, Any]) -> np.ndarray:
        if self.means is None or self.scales is None or self.categories is None:
            raise RuntimeError("FeatureEncoder must be fit on TRAIN rows before transform")
        values: list[float] = []
        numeric_features = self.numeric_features or NUMERIC_FEATURES
        categorical_features = self.categorical_features or CATEGORICAL_FEATURES
        for key in numeric_features:
            value = parse_float(features.get(key), self.means[key])
            value = self.means[key] if value is None or not np.isfinite(value) else value
            values.append((value - self.means[key]) / self.scales[key])
        for key in categorical_features:
            value = str(features.get(key) or "__MISSING__")
            values.extend(1.0 if value == category else 0.0 for category in self.categories[key])
        return np.asarray(values, dtype=float)

    def to_dict(self) -> dict[str, Any]:
        if self.means is None or self.scales is None or self.categories is None:
            raise RuntimeError("cannot serialize an unfitted FeatureEncoder")
        return {
            "means": self.means,
            "scales": self.scales,
            "categories": {key: list(values) for key, values in self.categories.items()},
            "numeric_features": list(self.numeric_features or NUMERIC_FEATURES),
            "categorical_features": list(self.categorical_features or CATEGORICAL_FEATURES),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "FeatureEncoder":
        encoder = cls(
            means={str(key): float(value) for key, value in dict(payload.get("means", {})).items()},
            scales={str(key): float(value) for key, value in dict(payload.get("scales", {})).items()},
            categories={str(key): tuple(str(item) for item in values) for key, values in dict(payload.get("categories", {})).items()},
            numeric_features=tuple(str(item) for item in payload.get("numeric_features", payload.get("means", {}).keys())),
            categorical_features=tuple(str(item) for item in payload.get("categorical_features", payload.get("categories", {}).keys())),
        )
        missing = [key for key in (encoder.numeric_features or ()) if key not in encoder.means or key not in encoder.scales]
        missing.extend(key for key in (encoder.categorical_features or ()) if key not in encoder.categories)
        if missing:
            raise ValueError(f"deployment encoder is missing feature definitions: {missing[:5]}")
        return encoder


def _train_rows(rows: Iterable[Mapping[str, Any]]) -> list[Mapping[str, Any]]:
    return [row for row in rows if row.get("dataset_split") in {None, "TRAIN"} and row.get("label_status") == "AVAILABLE" and row.get("label_next_action")]


def _label_data(rows: list[Mapping[str, Any]]) -> tuple[list[str], np.ndarray]:
    actions = sorted({str(row["label_next_action"]) for row in rows})
    index = {action: position for position, action in enumerate(actions)}
    labels = np.asarray([index[str(row["label_next_action"])] for row in rows], dtype=int)
    return actions, labels


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - logits.max(axis=1, keepdims=True)
    values = np.exp(shifted)
    return values / values.sum(axis=1, keepdims=True)


class NumpyLogisticStrategy:
    """Deterministic multiclass logistic imitation model plus target regression."""

    version = "behavioral-distillation-v1-logistic-numpy"

    def __init__(self, epochs: int = 60, learning_rate: float = 0.18, l2: float = 1e-3, target_l2: float = 0.0, class_weighting: str | None = None, enforce_action_target_consistency: bool = False, min_action_confidence: float | None = None) -> None:
        if target_l2 < 0:
            raise ValueError("target_l2 must be non-negative")
        if class_weighting not in {None, "balanced", "sqrt_balanced"}:
            raise ValueError("class_weighting must be None, 'balanced', or 'sqrt_balanced'")
        if min_action_confidence is not None and not 0.0 <= min_action_confidence <= 1.0:
            raise ValueError("min_action_confidence must be in [0, 1]")
        self.epochs = epochs
        self.learning_rate = learning_rate
        self.l2 = l2
        # ``0`` preserves the historical artifact contract.  New candidate
        # models can opt into ridge-stabilised target regression; this is
        # important because the standardized feature matrix still contains
        # near-collinear instrument and indicator columns.
        self.target_l2 = target_l2
        self.class_weighting = class_weighting
        self.enforce_action_target_consistency = enforce_action_target_consistency
        self.min_action_confidence = min_action_confidence
        self.encoder = FeatureEncoder()
        self.actions: list[str] = []
        self.weights: np.ndarray | None = None
        self.bias: np.ndarray | None = None
        self.target_coef: np.ndarray | None = None
        self.probability_temperature = 1.0
        self.probability_bias: np.ndarray | None = None
        self.calibration_row_count = 0
        self.fit_row_count = 0

    def fit(self, rows: Iterable[Mapping[str, Any]]) -> "NumpyLogisticStrategy":
        train = _train_rows(rows)
        if not train:
            raise ValueError("NumpyLogisticStrategy requires TRAIN labels")
        # Fitting a model starts a new artifact; do not accidentally carry a
        # calibrator from an earlier fit into a different chronological split.
        self.probability_temperature = 1.0
        self.probability_bias = None
        self.calibration_row_count = 0
        self.encoder.fit(train)
        # Preallocate instead of building a Python list of one NumPy array per
        # row.  Temporal market-clock datasets can contain hundreds of
        # thousands of rows; the old construction retained both the list and
        # the stacked copy during fit.
        first_vector = self.encoder.transform(train[0])
        matrix = np.empty((len(train), first_vector.shape[0]), dtype=float)
        matrix[0] = first_vector
        for index, row in enumerate(train[1:], start=1):
            matrix[index] = self.encoder.transform(row)
        self.actions, labels = _label_data(train)
        class_count = len(self.actions)
        self.weights = np.zeros((matrix.shape[1], class_count), dtype=float)
        self.bias = np.zeros(class_count, dtype=float)
        targets = np.asarray([float(row["label_next_target_exposure"]) for row in train], dtype=float)
        sample_weights = np.ones(len(train), dtype=float)
        if self.class_weighting == "balanced":
            counts = np.bincount(labels, minlength=class_count).astype(float)
            sample_weights = np.asarray([len(train) / (class_count * counts[label]) if counts[label] else 1.0 for label in labels], dtype=float)
        elif self.class_weighting == "sqrt_balanced":
            counts = np.bincount(labels, minlength=class_count).astype(float)
            sample_weights = np.asarray([np.sqrt(len(train) / (class_count * counts[label])) if counts[label] else 1.0 for label in labels], dtype=float)
        weight_sum = float(sample_weights.sum())
        if self.target_l2:
            # Equivalent to X'X + λI for X=[1, matrix], but without materializing
            # a second (rows x features) array for the intercept column.
            feature_count = matrix.shape[1]
            gram = np.eye(feature_count + 1, dtype=float) * self.target_l2
            gram[0, 0] = 0.0
            gram[0, 0] += weight_sum
            column_sum = (matrix * sample_weights[:, None]).sum(axis=0)
            gram[0, 1:] = column_sum
            gram[1:, 0] = column_sum
            gram[1:, 1:] += matrix.T @ (matrix * sample_weights[:, None])
            rhs = np.empty(feature_count + 1, dtype=float)
            rhs[0] = float(sample_weights @ targets)
            rhs[1:] = matrix.T @ (sample_weights * targets)
            try:
                self.target_coef = np.linalg.solve(gram, rhs)
            except np.linalg.LinAlgError:
                self.target_coef = np.linalg.pinv(gram) @ rhs
        else:
            augmented = np.column_stack([np.ones(matrix.shape[0]), matrix])
            self.target_coef = np.linalg.pinv(augmented) @ targets
        one_hot = np.eye(class_count)[labels]
        for _ in range(self.epochs):
            probabilities = _softmax(matrix @ self.weights + self.bias)
            error = (probabilities - one_hot) * sample_weights[:, None]
            self.weights -= self.learning_rate * ((matrix.T @ error) / weight_sum + self.l2 * self.weights)
            self.bias -= self.learning_rate * error.sum(axis=0) / weight_sum
        self.fit_row_count = len(train)
        return self

    def _base_logits(self, vector: np.ndarray) -> np.ndarray:
        if self.weights is None or self.bias is None:
            raise RuntimeError("NumpyLogisticStrategy must be fit before predicting")
        return vector.reshape(1, -1) @ self.weights + self.bias

    def predict_proba(self, strategy_input: StrategyInput) -> np.ndarray:
        """Return the action probabilities after the frozen calibrator.

        The optional calibrator is fitted only by research callers on a
        chronological training holdout.  Legacy artifacts have temperature
        ``1`` and no bias, so their predictions remain byte-compatible apart
        from normal NumPy evaluation.
        """

        vector = self.encoder.transform(strategy_input.features)
        logits = self._base_logits(vector)
        bias = self.probability_bias
        if bias is not None:
            logits = logits + bias.reshape(1, -1)
        temperature = max(0.25, min(10.0, float(self.probability_temperature)))
        return _softmax(logits / temperature)[0]

    def calibrate_probabilities(self, rows: Iterable[Mapping[str, Any]], *, epochs: int = 240, learning_rate: float = 0.08) -> dict[str, float | int]:
        """Fit a deterministic temperature-plus-class-bias calibrator.

        ``rows`` must be a training-only chronological holdout.  The base
        model weights are never changed.  A small class-bias vector handles
        prior shift while temperature handles confidence sharpness; both are
        regularised and bounded so calibration cannot become an unrestricted
        second classifier.
        """

        if self.weights is None or self.bias is None or not self.actions:
            raise RuntimeError("NumpyLogisticStrategy must be fit before calibration")
        source_rows = list(rows)
        candidates = [row for row in source_rows if row.get("label_status") == "AVAILABLE" and str(row.get("label_next_action") or "") in self.actions]
        if not candidates:
            raise ValueError("probability calibration requires known labeled rows")
        first_vector = self.encoder.transform(candidates[0])
        matrix = np.empty((len(candidates), first_vector.shape[0]), dtype=float)
        matrix[0] = first_vector
        for index, row in enumerate(candidates[1:], start=1):
            matrix[index] = self.encoder.transform(row)
        logits = matrix @ self.weights + self.bias
        label_index = {action: index for index, action in enumerate(self.actions)}
        labels = np.asarray([label_index[str(row["label_next_action"])] for row in candidates], dtype=int)
        one_hot = np.eye(len(self.actions), dtype=float)[labels]

        def loss(probabilities: np.ndarray) -> float:
            return float(-np.mean(np.log(np.clip(probabilities[np.arange(len(labels)), labels], 1e-12, 1.0))))

        base_probabilities = _softmax(logits)
        before = loss(base_probabilities)
        class_bias = np.zeros(len(self.actions), dtype=float)
        log_temperature = 0.0
        current_loss = before
        step = max(1e-4, float(learning_rate))
        for _ in range(max(1, int(epochs))):
            temperature = float(np.exp(np.clip(log_temperature, np.log(0.25), np.log(10.0))))
            calibrated_logits = (logits + class_bias) / temperature
            probabilities = _softmax(calibrated_logits)
            error = probabilities - one_hot
            # d((logits+bias)/T)/d bias is 1/T.  Use a backtracking step so
            # an unusually sharp training slice cannot make calibration worse
            # than the uncalibrated model.
            grad_bias = error.mean(axis=0) / temperature + 1e-3 * class_bias
            grad_log_temperature = float(np.mean(-np.sum(error * (logits + class_bias), axis=1) / temperature))
            trial_bias = np.clip(class_bias - step * grad_bias, -4.0, 4.0)
            trial_log_temperature = float(np.clip(log_temperature - step * grad_log_temperature, np.log(0.25), np.log(10.0)))
            trial_temperature = float(np.exp(trial_log_temperature))
            trial_probabilities = _softmax((logits + trial_bias) / trial_temperature)
            trial_loss = loss(trial_probabilities)
            if trial_loss + 1e-12 < current_loss:
                class_bias = trial_bias
                log_temperature = trial_log_temperature
                current_loss = trial_loss
                step = min(step * 1.02, 0.5)
            else:
                step *= 0.5
                if step < 1e-8:
                    break
        self.probability_temperature = float(np.exp(log_temperature))
        self.probability_bias = class_bias
        self.calibration_row_count = len(candidates)
        after = current_loss
        return {
            "calibration_rows": len(candidates),
            "unseen_label_rows": sum(str(row.get("label_next_action") or "") not in self.actions for row in source_rows),
            "nll_before": before,
            "nll_after": after,
            "temperature": self.probability_temperature,
            "bias_l1": float(np.abs(class_bias).sum()),
        }

    def predict(self, strategy_input: StrategyInput) -> StrategySignal:
        if self.weights is None or self.bias is None or self.target_coef is None:
            raise RuntimeError("NumpyLogisticStrategy must be fit before predict")
        vector = self.encoder.transform(strategy_input.features)
        probabilities = self.predict_proba(strategy_input)
        class_index = int(np.argmax(probabilities))
        action = self.actions[class_index]
        if self.min_action_confidence is not None and float(probabilities[class_index]) < self.min_action_confidence and "NO_TRADE" in self.actions:
            action = "NO_TRADE"
        augmented = np.concatenate(([1.0], vector))
        target = float(np.clip(augmented @ self.target_coef, -1.0, 1.0))
        if self.enforce_action_target_consistency and action in {"NO_TRADE", "HOLD_LONG", "HOLD_SHORT"}:
            # A hold/no-trade action must not secretly generate a new target
            # position from the independent regression head.
            target = float(np.clip(strategy_input.current_strategy_position, -1.0, 1.0))
        tags = ["TRAIN_NUMPY_LOGISTIC"]
        if str(strategy_input.features.get("feature_mark_index_missing")) in {"True", "true", "1"}:
            tags.append("MARK_INDEX_MISSING")
        return make_signal(strategy_input.decision_time, target_exposure=target, action=action, confidence=float(probabilities[class_index]), risk_tags=tuple(tags), strategy_version=self.version)


class CrossAssetNumpyLogisticStrategy(NumpyLogisticStrategy):
    """Shared deterministic imitation model for the m13 cross-asset contract."""

    # The class default remains compatible with the frozen v2 artifact. The
    # v3 evaluator and deployment builder stamp their explicit version after
    # fitting, so callers cannot accidentally relabel v2 as v3.
    version = "behavioral-distillation-v2-cross-asset-logistic"

    def to_dict(self) -> dict[str, Any]:
        if self.weights is None or self.bias is None or self.target_coef is None:
            raise RuntimeError("cannot serialize an unfitted strategy")
        return {
            "model_type": "CrossAssetNumpyLogisticStrategy",
            "version": self.version,
            "epochs": self.epochs,
            "learning_rate": self.learning_rate,
            "l2": self.l2,
            "target_l2": self.target_l2,
            "class_weighting": self.class_weighting,
            "enforce_action_target_consistency": self.enforce_action_target_consistency,
            "min_action_confidence": self.min_action_confidence,
            "probability_temperature": self.probability_temperature,
            "probability_bias": self.probability_bias.tolist() if self.probability_bias is not None else None,
            "calibration_row_count": self.calibration_row_count,
            "fit_row_count": self.fit_row_count,
            "actions": list(self.actions),
            "weights": self.weights.tolist(),
            "bias": self.bias.tolist(),
            "target_coef": self.target_coef.tolist(),
            "encoder": self.encoder.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "CrossAssetNumpyLogisticStrategy":
        if payload.get("model_type") != "CrossAssetNumpyLogisticStrategy":
            raise ValueError("unsupported deployment model type")
        model = cls(
            epochs=int(payload.get("epochs", 60)),
            learning_rate=float(payload.get("learning_rate", 0.18)),
            l2=float(payload.get("l2", 1e-3)),
            target_l2=float(payload.get("target_l2", 0.0)),
            class_weighting=payload.get("class_weighting"),
            enforce_action_target_consistency=bool(payload.get("enforce_action_target_consistency", False)),
            min_action_confidence=(float(payload["min_action_confidence"]) if payload.get("min_action_confidence") is not None else None),
        )
        model.version = str(payload.get("version", cls.version))
        model.actions = [str(item) for item in payload.get("actions", [])]
        model.weights = np.asarray(payload.get("weights", []), dtype=float)
        model.bias = np.asarray(payload.get("bias", []), dtype=float)
        model.target_coef = np.asarray(payload.get("target_coef", []), dtype=float)
        model.probability_temperature = float(payload.get("probability_temperature", 1.0))
        if not 0.25 <= model.probability_temperature <= 10.0:
            raise ValueError("invalid probability calibration temperature")
        calibration_bias = payload.get("probability_bias")
        model.probability_bias = np.asarray(calibration_bias, dtype=float) if calibration_bias is not None else None
        if model.probability_bias is not None and model.probability_bias.shape != (len(model.actions),):
            raise ValueError("probability calibration bias dimensions do not match actions")
        model.calibration_row_count = int(payload.get("calibration_row_count", 0))
        model.encoder = FeatureEncoder.from_dict(payload.get("encoder", {}))
        model.fit_row_count = int(payload.get("fit_row_count", 0))
        if not model.actions or model.weights.ndim != 2 or model.bias.ndim != 1 or model.target_coef.ndim != 1:
            raise ValueError("invalid deployment model arrays")
        if model.weights.shape[1] != len(model.actions) or model.bias.shape[0] != len(model.actions) or model.target_coef.shape[0] != model.weights.shape[0] + 1:
            raise ValueError("deployment model dimensions do not match actions/features")
        return model


class TwoStageCrossAssetStrategy:
    """Separate action timing from action type and target exposure.

    The timing head answers whether the next decision changes exposure.  The
    action head is trained only on non-idle teacher actions, so rare open/close
    direction classes are not forced to compete with thousands of no-trade
    rows in the same classifier.  Both heads remain deterministic NumPy
    models and share the frozen feature contract.
    """

    version = "behavioral-distillation-v3.7-two-stage-action-target"
    IDLE_ACTIONS = frozenset({"NO_TRADE", "HOLD_LONG", "HOLD_SHORT"})

    def __init__(self, *, timing_threshold: float | None = None, target_l2: float = 1.0) -> None:
        self.timing_threshold = timing_threshold
        self.target_l2 = target_l2
        self.timing_model = CrossAssetNumpyLogisticStrategy(
            target_l2=target_l2,
            class_weighting="sqrt_balanced",
            enforce_action_target_consistency=True,
        )
        self.action_model = CrossAssetNumpyLogisticStrategy(target_l2=target_l2)
        self.fit_row_count = 0

    @classmethod
    def _is_idle(cls, row: Mapping[str, Any]) -> bool:
        return str(row.get("label_next_action") or "") in cls.IDLE_ACTIONS

    @classmethod
    def _timing_rows(cls, rows: Iterable[Mapping[str, Any]]) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for original in rows:
            row = dict(original)
            idle = cls._is_idle(row)
            row["label_next_action"] = "NO_TRADE" if idle else "ACTION"
            if idle:
                row["label_next_target_exposure"] = row.get("feature_current_normalized_exposure", "0")
            output.append(row)
        return output

    def fit(self, rows: Iterable[Mapping[str, Any]]) -> "TwoStageCrossAssetStrategy":
        source = [dict(row, dataset_split="TRAIN") for row in rows if row.get("label_status") == "AVAILABLE" and row.get("label_next_action")]
        if not source:
            raise ValueError("TwoStageCrossAssetStrategy requires labeled rows")
        timing_rows = self._timing_rows(source)
        action_rows = [row for row in source if not self._is_idle(row)]
        if not action_rows:
            raise ValueError("TwoStageCrossAssetStrategy requires non-idle action rows")
        self.timing_model.fit(timing_rows)
        self.action_model.fit(action_rows)
        self.timing_model.version = f"{self.version}:timing"
        self.action_model.version = f"{self.version}:action"
        self.fit_row_count = len(source)
        return self

    def action_probability(self, strategy_input: StrategyInput) -> float:
        probabilities = self.timing_model.predict_proba(strategy_input)
        try:
            index = self.timing_model.actions.index("ACTION")
        except ValueError:
            return 0.0
        return float(probabilities[index])

    def calibrate_action_probability(self, rows: Iterable[Mapping[str, Any]]) -> dict[str, float | int]:
        """Calibrate the timing head on a training-only chronological holdout."""

        return self.timing_model.calibrate_probabilities(self._timing_rows(rows))

    def predict(self, strategy_input: StrategyInput) -> StrategySignal:
        action_probability = self.action_probability(strategy_input)
        threshold = 0.5 if self.timing_threshold is None else float(self.timing_threshold)
        current = float(np.clip(strategy_input.current_strategy_position, -1.0, 1.0))
        if action_probability < threshold:
            action = "HOLD_LONG" if current > 0 else "HOLD_SHORT" if current < 0 else "NO_TRADE"
            return make_signal(
                strategy_input.decision_time,
                target_exposure=current,
                action=action,
                confidence=float(max(0.0, min(1.0, 1.0 - action_probability))),
                risk_tags=("TWO_STAGE_TIMING", "ACTION_PROBABILITY_BELOW_THRESHOLD"),
                strategy_version=self.version,
            )
        signal = self.action_model.predict(strategy_input)
        return make_signal(
            strategy_input.decision_time,
            target_exposure=signal.target_exposure,
            action=signal.action,
            confidence=float(max(0.0, min(1.0, action_probability * signal.confidence))),
            risk_tags=tuple(dict.fromkeys(("TWO_STAGE_TIMING", "TWO_STAGE_ACTION_TARGET", *signal.risk_tags))),
            strategy_version=self.version,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_type": "TwoStageCrossAssetStrategy",
            "version": self.version,
            "timing_threshold": self.timing_threshold,
            "target_l2": self.target_l2,
            "fit_row_count": self.fit_row_count,
            "timing_model": self.timing_model.to_dict(),
            "action_model": self.action_model.to_dict(),
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "TwoStageCrossAssetStrategy":
        if payload.get("model_type") != "TwoStageCrossAssetStrategy":
            raise ValueError("unsupported two-stage deployment model type")
        model = cls(timing_threshold=(float(payload["timing_threshold"]) if payload.get("timing_threshold") is not None else None), target_l2=float(payload.get("target_l2", 1.0)))
        model.version = str(payload.get("version", cls.version))
        model.fit_row_count = int(payload.get("fit_row_count", 0))
        model.timing_model = CrossAssetNumpyLogisticStrategy.from_dict(payload.get("timing_model", {}))
        model.action_model = CrossAssetNumpyLogisticStrategy.from_dict(payload.get("action_model", {}))
        return model


@dataclass
class _TreeNode:
    action: str
    target: float
    confidence: float
    feature_index: int | None = None
    threshold: float | None = None
    left: "_TreeNode | None" = None
    right: "_TreeNode | None" = None


class NumpyDecisionTreeStrategy:
    """Small deterministic CART-style action tree with leaf target means."""

    version = "behavioral-distillation-v1-tree-numpy"

    def __init__(self, max_depth: int = 4, min_leaf: int = 128) -> None:
        self.max_depth = max_depth
        self.min_leaf = min_leaf
        self.encoder = FeatureEncoder()
        self.root: _TreeNode | None = None
        self.fit_row_count = 0

    @staticmethod
    def _gini(labels: np.ndarray) -> float:
        if labels.size == 0:
            return 0.0
        _, counts = np.unique(labels, return_counts=True)
        probabilities = counts / labels.size
        return float(1.0 - np.sum(probabilities * probabilities))

    def fit(self, rows: Iterable[Mapping[str, Any]]) -> "NumpyDecisionTreeStrategy":
        train = _train_rows(rows)
        if not train:
            raise ValueError("NumpyDecisionTreeStrategy requires TRAIN labels")
        self.encoder.fit(train)
        matrix = np.vstack([self.encoder.transform(row) for row in train])
        actions, labels = _label_data(train)
        targets = np.asarray([float(row["label_next_target_exposure"]) for row in train], dtype=float)
        self.root = self._grow(matrix, labels, targets, actions, depth=0)
        self.fit_row_count = len(train)
        return self

    def _grow(self, matrix: np.ndarray, labels: np.ndarray, targets: np.ndarray, actions: list[str], depth: int) -> _TreeNode:
        counts = np.bincount(labels, minlength=len(actions))
        majority = int(np.argmax(counts))
        base = _TreeNode(actions[majority], float(targets.mean()), float(counts[majority] / len(labels)))
        if depth >= self.max_depth or len(labels) < 2 * self.min_leaf or self._gini(labels) == 0.0:
            return base
        parent_loss = self._gini(labels)
        best: tuple[float, int, float, np.ndarray] | None = None
        for feature_index in range(matrix.shape[1]):
            values = matrix[:, feature_index]
            candidates = np.unique(np.quantile(values, np.linspace(0.1, 0.9, 9)))
            for threshold in candidates:
                left_mask = values <= threshold
                right_mask = ~left_mask
                if left_mask.sum() < self.min_leaf or right_mask.sum() < self.min_leaf:
                    continue
                loss = (left_mask.sum() * self._gini(labels[left_mask]) + right_mask.sum() * self._gini(labels[right_mask])) / len(labels)
                if best is None or loss < best[0]:
                    best = (float(loss), feature_index, float(threshold), left_mask)
        if best is None or best[0] >= parent_loss - 1e-9:
            return base
        _, feature_index, threshold, left_mask = best
        base.feature_index = feature_index
        base.threshold = threshold
        base.left = self._grow(matrix[left_mask], labels[left_mask], targets[left_mask], actions, depth + 1)
        base.right = self._grow(matrix[~left_mask], labels[~left_mask], targets[~left_mask], actions, depth + 1)
        return base

    def predict(self, strategy_input: StrategyInput) -> StrategySignal:
        if self.root is None:
            raise RuntimeError("NumpyDecisionTreeStrategy must be fit before predict")
        node = self.root
        vector = self.encoder.transform(strategy_input.features)
        while node.feature_index is not None and node.threshold is not None:
            node = node.left if vector[node.feature_index] <= node.threshold else node.right  # type: ignore[assignment]
        tags = ["TRAIN_NUMPY_DECISION_TREE"]
        if str(strategy_input.features.get("feature_mark_index_missing")) in {"True", "true", "1"}:
            tags.append("MARK_INDEX_MISSING")
        return make_signal(strategy_input.decision_time, target_exposure=float(np.clip(node.target, -1.0, 1.0)), action=node.action, confidence=node.confidence, risk_tags=tuple(tags), strategy_version=self.version)
