from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .base import StrategySignal


@dataclass
class StrategyState:
    """Minimal exchange-neutral state holder for deterministic signal parity."""

    current_exposure: float = 0.0
    last_signal_timestamp: str | None = None
    last_action: str | None = None
    last_strategy_version: str | None = None

    def apply_signal(self, signal: StrategySignal) -> None:
        signal.validate()
        self.current_exposure = signal.target_exposure
        self.last_signal_timestamp = signal.signal_timestamp
        self.last_action = signal.action
        self.last_strategy_version = signal.strategy_version

    def as_dict(self) -> dict[str, Any]:
        return {
            "current_exposure": self.current_exposure,
            "last_signal_timestamp": self.last_signal_timestamp,
            "last_action": self.last_action,
            "last_strategy_version": self.last_strategy_version,
        }
