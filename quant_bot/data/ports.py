from __future__ import annotations

from datetime import datetime
from typing import Iterable, Protocol

from quant_bot.domain.market_data import MarketBar


class MarketDataProvider(Protocol):
    def closed_bars(self, symbol: str, start: datetime, end: datetime) -> Iterable[MarketBar]: ...


class AccountStateProvider(Protocol):
    def portfolio_snapshot(self) -> object: ...
