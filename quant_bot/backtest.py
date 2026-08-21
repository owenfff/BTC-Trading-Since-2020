from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import sqrt
from typing import Iterable, Mapping, Sequence


@dataclass(frozen=True)
class MarketBar:
    timestamp: datetime
    open: float
    close: float
    funding_rate: float | None = None


@dataclass
class MarketSeries:
    bars: list[MarketBar]
    times: list[datetime] = field(init=False)

    def __post_init__(self) -> None:
        self.bars.sort(key=lambda bar: bar.timestamp)
        self.times = [bar.timestamp for bar in self.bars]

    def first_index_after(self, timestamp: datetime, delay_bars: int = 0) -> int:
        return bisect_right(self.times, timestamp) + delay_bars


@dataclass(frozen=True)
class SignalEvent:
    signal_time: datetime
    target_exposure: float
    action: str
    confidence: float = 0.0
    source: str = "unknown"


@dataclass(frozen=True)
class BacktestConfig:
    fee_rate: float
    tick_size: float = 0.1
    slippage_ticks: float = 0.0
    signal_delay_bars: int = 0
    max_abs_exposure: float = 0.25
    min_exposure_step: float = 0.00001
    side: str = "BOTH"
    next_bar_execution: bool = True


@dataclass
class BacktestResult:
    strategy: str
    start_time: datetime
    end_time: datetime
    equity: list[float]
    returns: list[float]
    positions: list[float]
    timestamps: list[datetime]
    turnover: float
    fees: float
    funding: float
    slippage: float
    executed_events: int
    signal_events: int
    metrics: dict[str, float | int | None] = field(default_factory=dict)


def _clip_target(target: float, config: BacktestConfig) -> float:
    if config.side == "LONG_ONLY":
        target = max(0.0, target)
    elif config.side == "SHORT_ONLY":
        target = min(0.0, target)
    target = max(-config.max_abs_exposure, min(config.max_abs_exposure, target))
    step = config.min_exposure_step
    if step > 0:
        target = round(target / step) * step
    return target


def _event_map(series: MarketSeries, events: Iterable[SignalEvent], config: BacktestConfig) -> dict[int, SignalEvent]:
    scheduled: dict[int, SignalEvent] = {}
    for event in sorted(events, key=lambda item: item.signal_time):
        index = series.first_index_after(event.signal_time, config.signal_delay_bars)
        if not config.next_bar_execution:
            index = bisect_right(series.times, event.signal_time) - 1
        if index < 0 or index >= len(series.bars):
            continue
        scheduled[index] = event
    return scheduled


def simulate(
    series: MarketSeries,
    events: Iterable[SignalEvent],
    config: BacktestConfig,
    *,
    start_time: datetime,
    end_time: datetime,
    strategy: str,
) -> BacktestResult:
    start_index = bisect_right(series.times, start_time - _epsilon())
    end_index = bisect_right(series.times, end_time)
    bars = series.bars[start_index:end_index]
    if not bars:
        return BacktestResult(strategy, start_time, end_time, [], [], [], [], 0.0, 0.0, 0.0, 0.0, 0, 0, {})
    event_list = list(events)
    scheduled = _event_map(series, event_list, config)
    equity = [1.0]
    returns: list[float] = []
    positions: list[float] = []
    timestamps: list[datetime] = []
    position = 0.0
    turnover = fees = funding = slippage = 0.0
    executed_events = 0
    previous_close = bars[0].close
    for absolute_index, bar in enumerate(bars, start=start_index):
        event = scheduled.get(absolute_index)
        if event is not None:
            target = _clip_target(float(event.target_exposure), config)
            delta = target - position
            if abs(delta) > 0:
                position = target
                turnover += abs(delta)
                fee_cost = abs(delta) * config.fee_rate
                slip_cost = abs(delta) * config.slippage_ticks * config.tick_size / max(abs(bar.open), 1e-12)
                fees += fee_cost
                slippage += slip_cost
                executed_events += 1
            else:
                fee_cost = slip_cost = 0.0
        else:
            fee_cost = slip_cost = 0.0
        bar_return = (bar.close / previous_close - 1.0) if previous_close else 0.0
        market_pnl = equity[-1] * position * bar_return
        funding_cost = equity[-1] * position * (bar.funding_rate or 0.0)
        funding += funding_cost
        next_equity = equity[-1] + market_pnl - fee_cost - slip_cost - funding_cost
        returns.append(next_equity / equity[-1] - 1.0 if equity[-1] else 0.0)
        equity.append(next_equity)
        positions.append(position)
        timestamps.append(bar.timestamp)
        previous_close = bar.close
    result = BacktestResult(strategy, bars[0].timestamp, bars[-1].timestamp, equity[1:], returns, positions, timestamps, turnover, fees, funding, slippage, executed_events, len(event_list), {})
    result.metrics = performance_metrics(result)
    return result


def _epsilon() -> object:
    from datetime import timedelta

    return timedelta(microseconds=1)


def performance_metrics(result: BacktestResult) -> dict[str, float | int | None]:
    if not result.equity:
        return {"total_return": None, "cagr": None, "annualized_volatility": None, "sharpe": None, "sortino": None, "max_drawdown": None, "calmar": None, "win_rate": None, "payoff_ratio": None, "profit_factor": None, "turnover": 0.0, "average_exposure": None, "maximum_exposure": None, "fees": 0.0, "funding": 0.0, "slippage": 0.0, "longest_drawdown_recovery_days": None, "return_concentration_top5": None, "executed_events": 0, "signal_events": result.signal_events}
    periods_per_year = 365.25 * 24 * 12
    span_days = max((result.end_time - result.start_time).total_seconds() / 86400.0, 1.0 / 24.0)
    final_equity = result.equity[-1]
    total_return = final_equity - 1.0
    cagr = final_equity ** (365.25 / span_days) - 1.0 if final_equity > 0 else None
    mean_return = sum(result.returns) / len(result.returns) if result.returns else 0.0
    variance = sum((value - mean_return) ** 2 for value in result.returns) / max(len(result.returns) - 1, 1)
    volatility = sqrt(variance * periods_per_year)
    downside = [min(value, 0.0) for value in result.returns]
    downside_variance = sum(value * value for value in downside) / max(len(downside) - 1, 1)
    downside_volatility = sqrt(downside_variance * periods_per_year)
    sharpe = mean_return / sqrt(variance) * sqrt(periods_per_year) if variance > 0 else None
    sortino = mean_return / sqrt(downside_variance) * sqrt(periods_per_year) if downside_variance > 0 else None
    peak = result.equity[0]
    drawdowns: list[float] = []
    longest_recovery = 0
    recovery = 0
    for value in result.equity:
        peak = max(peak, value)
        drawdown = value / peak - 1.0 if peak else 0.0
        drawdowns.append(drawdown)
        if drawdown < 0:
            recovery += 1
            longest_recovery = max(longest_recovery, recovery)
        else:
            recovery = 0
    wins = [value for value in result.returns if value > 0]
    losses = [value for value in result.returns if value < 0]
    positive_sum = sum(wins)
    negative_sum = abs(sum(losses))
    top5 = sorted((abs(value) for value in wins), reverse=True)[:5]
    return {
        "total_return": total_return,
        "cagr": cagr,
        "annualized_volatility": volatility,
        "sharpe": sharpe,
        "sortino": sortino,
        "max_drawdown": min(drawdowns) if drawdowns else None,
        "calmar": cagr / abs(min(drawdowns)) if cagr is not None and drawdowns and min(drawdowns) < 0 else None,
        "win_rate": len(wins) / len(result.returns) if result.returns else None,
        "payoff_ratio": (sum(wins) / len(wins)) / (abs(sum(losses)) / len(losses)) if wins and losses else None,
        "profit_factor": positive_sum / negative_sum if negative_sum else None,
        "turnover": result.turnover,
        "average_exposure": sum(abs(value) for value in result.positions) / len(result.positions) if result.positions else None,
        "maximum_exposure": max((abs(value) for value in result.positions), default=None),
        "fees": result.fees,
        "funding": result.funding,
        "slippage": result.slippage,
        "longest_drawdown_recovery_days": longest_recovery / (24 * 12),
        "return_concentration_top5": sum(top5) / positive_sum if positive_sum else None,
        "executed_events": result.executed_events,
        "signal_events": result.signal_events,
    }


def assert_signal_parity(batch_signals: Sequence[Mapping[str, object]], streaming_signals: Sequence[Mapping[str, object]]) -> None:
    if len(batch_signals) != len(streaming_signals):
        raise AssertionError(f"parity length mismatch: {len(batch_signals)} != {len(streaming_signals)}")
    for index, (batch, streaming) in enumerate(zip(batch_signals, streaming_signals)):
        if dict(batch) != dict(streaming):
            raise AssertionError(f"strategy parity mismatch at index {index}: {batch} != {streaming}")
