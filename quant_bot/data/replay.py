from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Iterable

from quant_bot.domain.market_data import MarketBar


def deduplicate_bars(bars: Iterable[MarketBar]) -> list[MarketBar]:
    result: dict[tuple[str, datetime], MarketBar] = {}
    for bar in bars:
        result[(bar.symbol, bar.timestamp)] = bar
    return [result[key] for key in sorted(result)]


@dataclass
class ReconnectController:
    connected: bool = False
    reconnect_count: int = 0

    def on_disconnect(self) -> None:
        self.connected = False

    def on_connect(self) -> None:
        self.connected = True
        self.reconnect_count += 1
