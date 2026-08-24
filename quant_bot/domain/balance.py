from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from .common import canonical_symbol, decimal


@dataclass
class Balance:
    """An exchange-reported asset balance.

    Unified-margin venues can report a negative coin amount when the account
    has a borrow or other asset liability.  ``total`` and ``available`` are
    therefore signed values.  They are not used as the account's trading
    equity; the adapter separately obtains the venue's positive USD-equivalent
    equity.  ``reserved`` is an internal reservation and must remain
    non-negative.
    """

    currency: str
    total: Decimal = Decimal("0")
    available: Decimal = Decimal("0")
    reserved: Decimal = Decimal("0")

    def __post_init__(self) -> None:
        self.currency = canonical_symbol(self.currency)
        self.total = decimal(self.total)
        self.available = decimal(self.available)
        self.reserved = decimal(self.reserved)
        if self.reserved < 0:
            raise ValueError("reserved balance cannot be negative")
