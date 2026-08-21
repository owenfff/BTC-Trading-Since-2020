from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal, ROUND_DOWN
from typing import Any


UTC = timezone.utc


def utc_datetime(value: datetime | str) -> datetime:
    if isinstance(value, str):
        value = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ValueError("domain timestamps must be timezone-aware UTC")
    result = value.astimezone(UTC)
    return result


def decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def floor_step(value: Decimal, step: Decimal) -> Decimal:
    if step <= 0:
        raise ValueError("step must be positive")
    return (value / step).to_integral_value(rounding=ROUND_DOWN) * step


def canonical_symbol(value: str) -> str:
    result = str(value).strip().upper()
    if not result or any(character.isspace() for character in result):
        raise ValueError("canonical symbol must be non-empty and whitespace-free")
    return result
