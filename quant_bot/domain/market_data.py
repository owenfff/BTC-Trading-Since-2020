from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
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


@dataclass(frozen=True)
class MarketQuote:
    symbol: str
    bid: Any
    ask: Any
    observed_at: datetime
    source: str = "unknown"

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", canonical_symbol(self.symbol))
        object.__setattr__(self, "observed_at", utc_datetime(self.observed_at))
        bid = decimal(self.bid)
        ask = decimal(self.ask)
        if bid <= 0 or ask <= 0 or ask < bid:
            raise ValueError("market quote must be positive and two-sided")
        object.__setattr__(self, "bid", bid)
        object.__setattr__(self, "ask", ask)


@dataclass(frozen=True)
class MarketContext:
    symbol: str
    quote: MarketQuote
    closed_bar_time: datetime | None
    funding_rate: Any | None
    funding_source_time: datetime | None
    mark_price: Any | None
    index_price: Any | None
    observed_at: datetime
    coverage: dict[str, str]

    def __post_init__(self) -> None:
        object.__setattr__(self, "symbol", canonical_symbol(self.symbol))
        object.__setattr__(self, "observed_at", utc_datetime(self.observed_at))
        if self.closed_bar_time is not None:
            object.__setattr__(self, "closed_bar_time", utc_datetime(self.closed_bar_time))
        if self.funding_source_time is not None:
            object.__setattr__(self, "funding_source_time", utc_datetime(self.funding_source_time))
        for name in ("funding_rate", "mark_price", "index_price"):
            value = getattr(self, name)
            if value is not None:
                object.__setattr__(self, name, decimal(value))
        object.__setattr__(self, "coverage", dict(self.coverage or {}))

    def quote_age_seconds(self, now: datetime | None = None) -> float:
        current = utc_datetime(now or datetime.now(timezone.utc))
        return max(0.0, (current - self.quote.observed_at).total_seconds())

    def closed_bar_age_seconds(self, now: datetime | None = None) -> float | None:
        if self.closed_bar_time is None:
            return None
        current = utc_datetime(now or datetime.now(timezone.utc))
        return max(0.0, (current - self.closed_bar_time).total_seconds())
