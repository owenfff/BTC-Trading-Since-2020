from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping


STRATEGY_VERSION = "behavioral-distillation-v1-rules"


def _iso_utc(value: datetime | str) -> str:
    if isinstance(value, str):
        return value.replace("+00:00", "Z")
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


@dataclass(frozen=True)
class StrategyInput:
    """Decision-time input shared by backtest, streaming, and paper callers.

    `features` must contain only fields from ``feature_contract.py``. The core
    intentionally has no exchange client, account credential, or order
    submission dependency.
    """

    decision_time: datetime
    features: Mapping[str, Any]
    current_strategy_position: float = 0.0
    risk_state: Mapping[str, Any] = field(default_factory=dict)
    closed_market_bars: tuple[Mapping[str, Any], ...] = ()


@dataclass(frozen=True)
class StrategySignal:
    strategy_version: str
    signal_timestamp: str
    target_exposure: float
    target_position_notional: float | None
    action: str
    confidence: float
    valid_until: str
    max_slippage: float | None
    execution_preference: str
    risk_tags: tuple[str, ...]

    def as_dict(self) -> dict[str, Any]:
        return {
            "strategy_version": self.strategy_version,
            "signal_timestamp": self.signal_timestamp,
            "target_exposure": self.target_exposure,
            "target_position_notional": self.target_position_notional,
            "action": self.action,
            "confidence": self.confidence,
            "valid_until": self.valid_until,
            "max_slippage": self.max_slippage,
            "execution_preference": self.execution_preference,
            "risk_tags": list(self.risk_tags),
        }

    def validate(self) -> None:
        if not self.strategy_version or not self.signal_timestamp or not self.valid_until:
            raise ValueError("strategy_version and signal timestamps are required")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be in [0, 1]")
        if not self.action:
            raise ValueError("action is required")


def make_signal(
    decision_time: datetime,
    *,
    target_exposure: float,
    action: str,
    confidence: float,
    risk_tags: tuple[str, ...] = (),
    strategy_version: str = STRATEGY_VERSION,
    valid_for: timedelta = timedelta(minutes=5),
    target_position_notional: float | None = None,
    max_slippage: float | None = None,
    execution_preference: str = "PASSIVE_UNLESS_RISK_REDUCTION",
) -> StrategySignal:
    signal = StrategySignal(
        strategy_version=strategy_version,
        signal_timestamp=_iso_utc(decision_time),
        target_exposure=float(target_exposure),
        target_position_notional=target_position_notional,
        action=action,
        confidence=max(0.0, min(1.0, float(confidence))),
        valid_until=_iso_utc(decision_time + valid_for),
        max_slippage=max_slippage,
        execution_preference=execution_preference,
        risk_tags=tuple(dict.fromkeys(risk_tags)),
    )
    signal.validate()
    return signal
