from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .common import canonical_symbol, decimal, utc_datetime


@dataclass(frozen=True)
class MarketBar:
    symbol: str
    timestamp: datetime
    open: Any
    high: Any
    low: Any
    close: Any
    volume: Any | None = None
    funding_rate: Any | None = None
    source: str = "unknown"
    funding_source_time: datetime | None = None
    mark_price: Any | None = None
    index_price: Any | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", canonical_symbol(self.symbol))
        object.__setattr__(self, "timestamp", utc_datetime(self.timestamp))
        for name in ("open", "high", "low", "close"):
            value = decimal(getattr(self, name))
            if value <= 0:
                raise ValueError(f"OHLC must be positive: {name}")
            object.__setattr__(self, name, value)
        if self.volume is not None:
            object.__setattr__(self, "volume", decimal(self.volume))
        if self.funding_rate is not None:
            object.__setattr__(self, "funding_rate", decimal(self.funding_rate))
        if self.mark_price is not None:
            object.__setattr__(self, "mark_price", decimal(self.mark_price))
        if self.index_price is not None:
            object.__setattr__(self, "index_price", decimal(self.index_price))
