from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Mapping


@dataclass(frozen=True)
class ReconciliationResult:
    ok: bool
    mismatches: tuple[str, ...]


def reconcile_positions(local: Mapping[str, Decimal], remote: Mapping[str, Decimal], tolerance: Decimal = Decimal("0")) -> ReconciliationResult:
    mismatches: list[str] = []
    for symbol in sorted(set(local) | set(remote)):
        left = Decimal(str(local.get(symbol, 0)))
        right = Decimal(str(remote.get(symbol, 0)))
        if abs(left - right) > tolerance:
            mismatches.append(f"POSITION:{symbol}:{left}!={right}")
    return ReconciliationResult(not mismatches, tuple(mismatches))
