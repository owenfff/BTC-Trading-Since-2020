from __future__ import annotations

from decimal import Decimal

from quant_bot.execution.clock_sync import clock_is_safe


def clock_guard(drift_seconds: Decimal, max_drift_seconds: int) -> bool:
    return clock_is_safe(drift_seconds, max_drift_seconds)
