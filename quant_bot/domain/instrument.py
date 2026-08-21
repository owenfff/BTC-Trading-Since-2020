from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .common import canonical_symbol, decimal, floor_step


class InstrumentType(StrEnum):
    SPOT = "SPOT"
    LINEAR_PERPETUAL = "LINEAR_PERPETUAL"
    INVERSE_PERPETUAL = "INVERSE_PERPETUAL"


@dataclass(frozen=True)
class Instrument:
    canonical_symbol: str
    instrument_type: InstrumentType
    base_currency: str
    quote_currency: str
    settlement_currency: str
    tick_size: Any
    lot_size: Any
    minimum_quantity: Any
    minimum_notional: Any

    def __post_init__(self) -> None:
        object.__setattr__(self, "canonical_symbol", canonical_symbol(self.canonical_symbol))
        for field_name in ("base_currency", "quote_currency", "settlement_currency"):
            object.__setattr__(self, field_name, canonical_symbol(getattr(self, field_name)))
        for field_name in ("tick_size", "lot_size", "minimum_quantity", "minimum_notional"):
            value = decimal(getattr(self, field_name))
            if value < 0 or (field_name in {"tick_size", "lot_size"} and value == 0):
                raise ValueError(f"invalid instrument {field_name}: {value}")
            object.__setattr__(self, field_name, value)

    def normalize_price(self, value: Any) -> Decimal:
        return floor_step(decimal(value), self.tick_size)

    def normalize_quantity(self, value: Any) -> Decimal:
        quantity = floor_step(abs(decimal(value)), self.lot_size)
        if quantity < self.minimum_quantity:
            return Decimal("0")
        return quantity
