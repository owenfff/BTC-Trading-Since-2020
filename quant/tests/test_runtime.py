from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from quant_bot.data.replay import ReconnectController, deduplicate_bars
from quant_bot.domain.market_data import MarketBar
from quant_bot.paper import PaperTradingEngine
from quant_bot.runtime import SignalDeduplicator
from quant_bot.strategy.base import make_signal


def test_bar_dedup_and_reconnect_controller() -> None:
    t = datetime(2020, 1, 1, tzinfo=timezone.utc)
    bars = [MarketBar("XBTUSD", t, "1", "1", "1", "1"), MarketBar("XBTUSD", t, "1", "1", "1", "1")]
    assert len(deduplicate_bars(bars)) == 1
    controller = ReconnectController()
    controller.on_disconnect(); controller.on_connect()
    assert controller.connected and controller.reconnect_count == 1


def test_duplicate_signal_and_partial_paper_fill() -> None:
    signal = make_signal(datetime(2020, 1, 1, tzinfo=timezone.utc), target_exposure=Decimal("0.2"), action="OPEN_LONG", confidence=0.5)
    dedup = SignalDeduplicator()
    assert dedup.accept(signal) is True
    assert dedup.accept(signal) is False
    engine = PaperTradingEngine(fill_ratio=Decimal("0.5"))
    engine.apply_signal(signal, reference_price=Decimal("100"))
    assert engine.state.partial_orders == 1
    assert engine.state.position == Decimal("0.1")
