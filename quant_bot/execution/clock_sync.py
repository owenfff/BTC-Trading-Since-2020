from __future__ import annotations

from decimal import Decimal


def clock_is_safe(drift_seconds: Decimal, max_drift_seconds: int) -> bool:
    return abs(Decimal(str(drift_seconds))) <= Decimal(str(max_drift_seconds))
