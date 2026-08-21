from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from quant_bot.domain.instrument import Instrument


@dataclass(frozen=True)
class Allocation:
    symbol: str
    target_quantity: Decimal
    reason: str


def allocate_target_exposure(instrument: Instrument, target_exposure: Decimal, equity: Decimal, reference_price: Decimal) -> Allocation:
    if equity < 0 or reference_price <= 0:
        raise ValueError("equity must be non-negative and reference price positive")
    notional = abs(equity * target_exposure)
    quantity = instrument.normalize_quantity(notional / reference_price)
    if target_exposure < 0:
        quantity = -quantity
    return Allocation(instrument.canonical_symbol, quantity, "TARGET_EXPOSURE")
