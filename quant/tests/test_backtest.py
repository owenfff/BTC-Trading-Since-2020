from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quant_bot.backtest import BacktestConfig, MarketBar, MarketSeries, SignalEvent, assert_signal_parity, simulate


def series() -> MarketSeries:
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    return MarketSeries([
        MarketBar(start + timedelta(minutes=5 * index), 100.0 + index, 101.0 + index, 0.001 if index == 1 else None)
        for index in range(4)
    ])


def test_execution_is_next_bar_open_and_costs_are_recorded() -> None:
    bars = series()
    event_time = bars.times[0]
    result = simulate(bars, [SignalEvent(event_time, 0.25, "OPEN_LONG")], BacktestConfig(fee_rate=0.01, tick_size=0.1, slippage_ticks=2), start_time=bars.times[0], end_time=bars.times[-1], strategy="test")
    assert result.executed_events == 1
    assert result.fees > 0
    assert result.slippage > 0
    assert result.funding > 0


def test_limits_and_side_are_applied() -> None:
    bars = series()
    result = simulate(bars, [SignalEvent(bars.times[0] - timedelta(microseconds=1), 1.0, "OPEN_LONG")], BacktestConfig(fee_rate=0.0, max_abs_exposure=0.2, min_exposure_step=0.1, side="SHORT_ONLY"), start_time=bars.times[0], end_time=bars.times[-1], strategy="test")
    assert max(abs(value) for value in result.positions) == 0.0


def test_parity_helper_rejects_different_signals() -> None:
    try:
        assert_signal_parity([{"action": "OPEN_LONG"}], [{"action": "OPEN_SHORT"}])
    except AssertionError:
        return
    raise AssertionError("parity helper accepted different signals")
