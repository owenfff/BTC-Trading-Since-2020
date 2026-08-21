from __future__ import annotations

STRATEGY_FIDELITY = "BEHAVIORAL_APPROXIMATION"
STRATEGY_CORE_VERSION = "strategy-core-v1"
NO_EXCHANGE_SDK_DEPENDENCY = True

REQUIRED_SIGNAL_FIELDS = (
    "strategy_version",
    "signal_timestamp",
    "target_exposure",
    "target_position_notional",
    "action",
    "confidence",
    "valid_until",
    "max_slippage",
    "execution_preference",
    "risk_tags",
)
