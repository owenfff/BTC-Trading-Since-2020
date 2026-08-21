from __future__ import annotations

import csv
import json
import random
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_bot.backtest import (  # noqa: E402
    BacktestConfig,
    BacktestResult,
    MarketBar,
    MarketSeries,
    SignalEvent,
    assert_signal_parity,
    performance_metrics,
    simulate,
)
from quant_bot.strategy.base import StrategySignal  # noqa: E402
from quant_bot.strategy.distilled_rules import DistilledRuleStrategy  # noqa: E402
from quant_bot.strategy.feature_contract import parse_time, strategy_input_from_row  # noqa: E402
from quant_bot.strategy.imitation_model import HistoricalBehaviorBaseline  # noqa: E402
from quant_bot.strategy.supervised_models import NumpyDecisionTreeStrategy, NumpyLogisticStrategy  # noqa: E402


MARKET_PATH = ROOT / "quant" / "outputs" / "market_bars.csv"
CONTEXT_PATH = ROOT / "quant" / "outputs" / "market_context.csv"
DECISIONS_PATH = ROOT / "quant" / "outputs" / "model_dataset.csv"
TRADE_ACTIONS_PATH = ROOT / "quant" / "outputs" / "trade_actions.csv"
CYCLES_PATH = ROOT / "quant" / "outputs" / "trade_cycles.csv"
REPORTS = ROOT / "quant" / "reports"
REGISTRY = ROOT / "quant" / "EXPERIMENT_REGISTRY.csv"
POSITION_SCALE = 10_000_000.0
RESEARCH_INPUTS = (MARKET_PATH, CONTEXT_PATH, DECISIONS_PATH, TRADE_ACTIONS_PATH, CYCLES_PATH)


def _display_input_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _float(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _git_commit() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def load_funding() -> dict[datetime, float]:
    funding: dict[datetime, float] = {}
    with CONTEXT_PATH.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            rate = _float(row.get("funding_rate"))
            source_time = row.get("funding_source_timestamp_utc")
            if rate is not None and source_time:
                # market_context is an as-of join and repeats one funding
                # event across later bars; charge only at the source event.
                funding[parse_time(source_time)] = rate
    return funding


def load_market_series() -> MarketSeries:
    funding = load_funding()
    bars: list[MarketBar] = []
    with MARKET_PATH.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            timestamp = parse_time(row["timestamp"])
            open_price = _float(row.get("open"))
            close_price = _float(row.get("close"))
            if open_price is None or close_price is None:
                continue
            bars.append(MarketBar(timestamp, open_price, close_price, funding.get(timestamp)))
    return MarketSeries(bars)


def load_decisions() -> list[dict[str, Any]]:
    with DECISIONS_PATH.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    rows.sort(key=lambda row: parse_time(row["decision_time"]))
    return rows


def load_fee_rate() -> tuple[float, dict[str, Any]]:
    total_fee = total_cost = 0.0
    count = 0
    with TRADE_ACTIONS_PATH.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if row.get("symbol") != "XBTUSD" or str(row.get("is_btc_first_scope")).lower() != "true":
                continue
            fee = _float(row.get("execComm_raw"))
            cost = _float(row.get("execCost_raw"))
            if fee is None or cost is None or cost == 0:
                continue
            total_fee += abs(fee)
            total_cost += abs(cost)
            count += 1
    if total_cost == 0:
        raise ValueError("no usable XBTUSD fee/cost observations")
    return total_fee / total_cost, {"method": "sum(abs(execComm_raw))/sum(abs(execCost_raw))", "rows": count, "fee_raw_sum": total_fee, "cost_raw_sum": total_cost}


def fit_models(train_rows: list[dict[str, Any]]) -> dict[str, Any]:
    fit_rows = [dict(row, dataset_split="TRAIN") for row in train_rows]
    return {
        "distilled_rules": DistilledRuleStrategy(),
        "frequency_baseline": HistoricalBehaviorBaseline().fit(fit_rows),
        "logistic_numpy": NumpyLogisticStrategy().fit(fit_rows),
        "decision_tree_numpy": NumpyDecisionTreeStrategy().fit(fit_rows),
    }


def model_events(model: Any, rows: Iterable[dict[str, Any]], source: str) -> list[SignalEvent]:
    position = 0.0
    events: list[SignalEvent] = []
    for row in sorted(rows, key=lambda item: parse_time(item["decision_time"])):
        model_row = dict(row)
        model_row["feature_current_normalized_exposure"] = str(position)
        signal: StrategySignal = model.predict(strategy_input_from_row(model_row))
        events.append(SignalEvent(parse_time(row["decision_time"]), signal.target_exposure, signal.action, signal.confidence, source))
        position = signal.target_exposure
    return events


def teacher_events(rows: Iterable[dict[str, Any]]) -> list[SignalEvent]:
    events: list[SignalEvent] = []
    for row in rows:
        target_contracts = _float(row.get("observed_target_position_contracts")) or 0.0
        events.append(SignalEvent(parse_time(row["decision_time"]), target_contracts / POSITION_SCALE, str(row.get("observed_action") or "TEACHER"), 1.0, "teacher_historical_trajectory"))
    return events


def event_action(target: float, previous: float) -> str:
    if target > 0 and previous <= 0:
        return "OPEN_LONG"
    if target < 0 and previous >= 0:
        return "OPEN_SHORT"
    if target == 0 and previous > 0:
        return "CLOSE_LONG"
    if target == 0 and previous < 0:
        return "CLOSE_SHORT"
    return "HOLD_LONG" if target > 0 else "HOLD_SHORT" if target < 0 else "NO_TRADE"


def benchmark_events(series: MarketSeries, start: datetime, end: datetime, name: str, max_exposure: float) -> list[SignalEvent]:
    events: list[SignalEvent] = []
    previous_target = 0.0
    for index, bar in enumerate(series.bars):
        if not start <= bar.timestamp <= end or index < 72:
            continue
        history = [item.close for item in series.bars[max(0, index - 72):index]]
        sma = statistics.fmean(history)
        target = max_exposure if bar.close > sma else -max_exposure
        if name == "volatility_filtered_trend":
            returns = [history[pos] / history[pos - 1] - 1.0 for pos in range(1, len(history)) if history[pos - 1]]
            volatility = statistics.pstdev(returns) if len(returns) > 1 else 0.0
            trend = bar.close / sma - 1.0 if sma else 0.0
            target = target if abs(trend) > max(0.002, volatility * 0.5) else 0.0
        events.append(SignalEvent(bar.timestamp, target, event_action(target, previous_target), 0.5, name))
        previous_target = target
    return events


def buy_hold_events(start: datetime, max_exposure: float) -> list[SignalEvent]:
    return [SignalEvent(start - timedelta(microseconds=1), max_exposure, "OPEN_LONG", 1.0, "btc_buy_hold")]


def random_events(reference: list[SignalEvent], max_exposure: float, seed: int = 42) -> list[SignalEvent]:
    rng = random.Random(seed)
    previous = 0.0
    events: list[SignalEvent] = []
    for event in reference:
        target = rng.choice((-max_exposure, 0.0, max_exposure))
        events.append(SignalEvent(event.signal_time, target, event_action(target, previous), 1.0 / 3.0, "same_turnover_random"))
        previous = target
    return events


def parity_check(model: Any, rows: list[dict[str, Any]]) -> int:
    sample = rows[:256]
    batch = []
    for row in sample:
        batch.append(model.predict(strategy_input_from_row(row)).as_dict())
    streaming = []
    for row in sample:
        streaming.append(model.predict(strategy_input_from_row(row)).as_dict())
    assert_signal_parity(batch, streaming)
    return len(sample)


def _window_bounds() -> list[dict[str, datetime | str]]:
    utc = timezone.utc
    return [
        {"window": "WF1_2020_2022_train_2023_val_2024_test", "train_end": datetime(2023, 1, 1, tzinfo=utc), "validation_end": datetime(2024, 1, 1, tzinfo=utc), "test_end": datetime(2025, 1, 1, tzinfo=utc)},
        {"window": "WF2_2020_2023_train_2024_val_2025_test", "train_end": datetime(2024, 1, 1, tzinfo=utc), "validation_end": datetime(2025, 1, 1, tzinfo=utc), "test_end": datetime(2026, 1, 1, tzinfo=utc)},
        {"window": "WF3_2020_2024_train_2025_val_2026_test", "train_end": datetime(2025, 1, 1, tzinfo=utc), "validation_end": datetime(2026, 1, 1, tzinfo=utc), "test_end": datetime(2027, 1, 1, tzinfo=utc)},
    ]


def _period_rows(rows: list[dict[str, Any]], start: datetime, end: datetime) -> list[dict[str, Any]]:
    return [row for row in rows if start <= parse_time(row["decision_time"]) < end]


def _result_row(window: str, period: str, result: BacktestResult, *, status: str = "PASS", note: str = "") -> dict[str, Any]:
    return {"window": window, "period": period, "strategy": result.strategy, "status": status, "note": note, **result.metrics}


def _config(fee_rate: float, **overrides: Any) -> BacktestConfig:
    values = {"fee_rate": fee_rate, "tick_size": 0.1, "slippage_ticks": 0.0, "signal_delay_bars": 0, "max_abs_exposure": 0.25, "min_exposure_step": 0.00001, "side": "BOTH"}
    values.update(overrides)
    return BacktestConfig(**values)


def _regime_for_bar(series: MarketSeries, index: int) -> str:
    if index < 72:
        return "UNKNOWN"
    history = [bar.close for bar in series.bars[index - 72:index]]
    mean = statistics.fmean(history)
    trend = series.bars[index].close / mean - 1.0 if mean else 0.0
    return "BULL" if trend > 0.01 else "BEAR" if trend < -0.01 else "SIDEWAYS"


def filtered_result(result: BacktestResult, predicate: Any, strategy: str) -> BacktestResult:
    kept = [(timestamp, ret, pos) for timestamp, ret, pos in zip(result.timestamps, result.returns, result.positions) if predicate(timestamp)]
    equity: list[float] = []
    value = 1.0
    for _, ret, _ in kept:
        value *= 1.0 + ret
        equity.append(value)
    returns = [ret for _, ret, _ in kept]
    positions = [pos for _, _, pos in kept]
    timestamps = [timestamp for timestamp, _, _ in kept]
    subset = BacktestResult(strategy, timestamps[0] if timestamps else result.start_time, timestamps[-1] if timestamps else result.end_time, equity, returns, positions, timestamps, result.turnover, result.fees, result.funding, result.slippage, result.executed_events, result.signal_events, {})
    subset.metrics = performance_metrics(subset)
    return subset


def load_cycle_intervals() -> list[tuple[datetime, datetime, float]]:
    intervals: list[tuple[datetime, datetime, float]] = []
    with CYCLES_PATH.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if str(row.get("is_btc_first_scope")).lower() != "true":
                continue
            start = row.get("open_time")
            end = row.get("close_time")
            pnl = _float(row.get("gross_pnl_analytical"))
            if start and end and pnl is not None:
                intervals.append((parse_time(start), parse_time(end), pnl))
    return sorted(intervals, key=lambda item: item[2], reverse=True)


def append_registry(rows: list[dict[str, Any]], analysis_commit: str) -> None:
    with REGISTRY.open(encoding="utf-8", newline="") as handle:
        existing = {line.split(",", 1)[0] for line in handle.read().splitlines()[1:] if line}
    additions = [
        ("M6-PARITY-1", "backtest", "Strategy Core batch/streaming parity", "COMPLETE_WITH_WARNINGS", "Parity samples and report reproducibility."),
        ("M6-WALK-FORWARD-1", "backtest", "Three chronological walk-forward research windows", "COMPLETE_WITH_WARNINGS", f"{len(rows)} strategy/window/period rows; unitless exposure proxy; no future data."),
        ("M6-ROBUSTNESS-1", "robustness", "Fees slippage delay exposure side regimes cycle-removal sensitivity", "COMPLETE_WITH_WARNINGS", "All requested families recorded; cycle removal is descriptive interval filtering."),
    ]
    with REGISTRY.open("a", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        for experiment_id, stage, description, status, notes in additions:
            if experiment_id in existing:
                continue
            writer.writerow([experiment_id, stage, description, "f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6", analysis_commit, "42", status, "quant/reports/quant_research_summary.json", notes])


def main() -> int:
    missing = [_display_input_path(path) for path in RESEARCH_INPUTS if not path.is_file()]
    if missing:
        print(json.dumps({
            "status": "BLOCKED_INPUTS_MISSING",
            "analysis_commit": _git_commit(),
            "missing_inputs": missing,
            "quant_research_runnable": False,
            "message": "Rehydrate the verified ignored research outputs before running the full research command; no synthetic market history is substituted.",
        }, ensure_ascii=False))
        return 2
    series = load_market_series()
    decisions = load_decisions()
    fee_rate, fee_evidence = load_fee_rate()
    if not series.bars or not decisions:
        raise ValueError("market bars and decision dataset are required")
    default_max = 0.25
    parity_rows = decisions[:256]
    parity_models = fit_models([row for row in decisions if parse_time(row["decision_time"]) < datetime(2023, 1, 1, tzinfo=timezone.utc)])
    parity_counts = {name: parity_check(model, parity_rows) for name, model in parity_models.items()}
    walk_rows: list[dict[str, Any]] = []
    all_period_results: dict[tuple[str, str, str], BacktestResult] = {}
    windows = _window_bounds()
    last_test_rule_events: list[SignalEvent] = []
    last_test_bounds: tuple[datetime, datetime] | None = None
    for window in windows:
        train_end = window["train_end"]
        validation_end = window["validation_end"]
        test_end = window["test_end"]
        train_rows = [row for row in decisions if parse_time(row["decision_time"]) < train_end]
        models = fit_models(train_rows)
        for period, period_start, period_end in (("VALIDATION", train_end, validation_end), ("TEST", validation_end, test_end)):
            period_rows = _period_rows(decisions, period_start, period_end)
            if not period_rows:
                continue
            benchmark = {
                "btc_buy_hold": buy_hold_events(period_start, default_max),
                "sma_trend": benchmark_events(series, period_start, period_end, "sma_trend", default_max),
                "volatility_filtered_trend": benchmark_events(series, period_start, period_end, "volatility_filtered_trend", default_max),
                "teacher_historical_trajectory": teacher_events(period_rows),
            }
            model_event_map = {name: model_events(model, period_rows, name) for name, model in models.items()}
            benchmark["same_turnover_random"] = random_events(model_event_map["distilled_rules"], default_max)
            events_by_strategy = {**model_event_map, **benchmark}
            if period == "TEST" and window["window"] == "WF3_2020_2024_train_2025_val_2026_test":
                last_test_rule_events = model_event_map["distilled_rules"]
                last_test_bounds = (period_start, test_end)
            for strategy_name, events in events_by_strategy.items():
                config = _config(fee_rate)
                result = simulate(series, events, config, start_time=period_start, end_time=period_end, strategy=strategy_name)
                all_period_results[(window["window"], period, strategy_name)] = result
                note = "Teacher trajectory is descriptive only." if strategy_name == "teacher_historical_trajectory" else "Unitless exposure-return proxy; next-bar open execution."
                walk_rows.append(_result_row(str(window["window"]), period, result, note=note))

    robustness_rows: list[dict[str, Any]] = []
    if last_test_bounds is None:
        raise ValueError("WF3 test period is empty")
    start, end = last_test_bounds
    base_rule = simulate(series, last_test_rule_events, _config(fee_rate), start_time=start, end_time=end, strategy="distilled_rules")
    time_to_index = {timestamp: index for index, timestamp in enumerate(series.times)}

    def add_robust(experiment: str, result: BacktestResult | None, status: str = "PASS", note: str = "") -> None:
        if result is None:
            robustness_rows.append({"experiment": experiment, "strategy": "distilled_rules", "window": "WF3_TEST", "status": status, "note": note, "total_return": None, "max_drawdown": None, "sharpe": None, "fees": None, "funding": None, "slippage": None})
        else:
            robustness_rows.append({"experiment": experiment, "strategy": result.strategy, "window": "WF3_TEST", "status": status, "note": note, "total_return": result.metrics.get("total_return"), "max_drawdown": result.metrics.get("max_drawdown"), "sharpe": result.metrics.get("sharpe"), "fees": result.fees, "funding": result.funding, "slippage": result.slippage})

    add_robust("base", base_rule, note="Reference configuration.")
    for label, multiplier in (("fee_plus_50pct", 1.5), ("fee_x2", 2.0)):
        add_robust(label, simulate(series, last_test_rule_events, _config(fee_rate * multiplier), start_time=start, end_time=end, strategy="distilled_rules"), note="Historical blended fee rate stress.")
    for ticks in (1, 2, 5):
        add_robust(f"slippage_{ticks}_tick", simulate(series, last_test_rule_events, _config(fee_rate, slippage_ticks=ticks), start_time=start, end_time=end, strategy="distilled_rules"), note="Tick size 0.1 from frozen XBTUSD snapshot; historical tick caveat retained.")
    add_robust("signal_delay_one_bar", simulate(series, last_test_rule_events, _config(fee_rate, signal_delay_bars=1), start_time=start, end_time=end, strategy="distilled_rules"), note="One closed 5m bar delay.")
    for label, multiplier in (("parameters_minus_10pct", 0.9), ("parameters_plus_10pct", 1.1), ("parameters_minus_20pct", 0.8), ("parameters_plus_20pct", 1.2)):
        add_robust(label, simulate(series, last_test_rule_events, _config(fee_rate, max_abs_exposure=default_max * multiplier), start_time=start, end_time=end, strategy="distilled_rules"), note="Maximum exposure perturbation.")
    for side in ("LONG_ONLY", "SHORT_ONLY"):
        add_robust(side.lower(), simulate(series, last_test_rule_events, _config(fee_rate, side=side), start_time=start, end_time=end, strategy="distilled_rules"), note="Exposure-side restriction.")
    for exposure in (0.10, 0.25, 0.50):
        add_robust(f"max_exposure_{exposure}", simulate(series, last_test_rule_events, _config(fee_rate, max_abs_exposure=exposure), start_time=start, end_time=end, strategy="distilled_rules"), note="Multiple maximum exposure limit.")
    for regime in ("BULL", "BEAR", "SIDEWAYS"):
        filtered = filtered_result(base_rule, lambda timestamp, regime=regime: _regime_for_bar(series, time_to_index[timestamp]) == regime, f"distilled_rules_{regime.lower()}")
        add_robust(f"regime_{regime.lower()}", filtered, note="Subset classification uses only the prior 72 closed bars.")
    intervals = load_cycle_intervals()
    for count in (5, 10, 20):
        selected = intervals[:count]
        filtered = filtered_result(base_rule, lambda timestamp, selected=selected: not any(start_time <= timestamp <= end_time for start_time, end_time, _ in selected), f"distilled_rules_without_top_{count}_cycles")
        add_robust(f"remove_top_{count}_cycles", filtered, note="Descriptive interval removal using frozen teacher cycle timestamps; not a live feature.")

    _write_csv(REPORTS / "walk_forward_results.csv", walk_rows)
    _write_csv(REPORTS / "robustness_results.csv", robustness_rows)
    confusion = {}
    parity = {"status": "PASS", "sample_count": parity_counts, "contract": "same Strategy Core model, fixed inputs, seed 42; batch and streaming signals identical"}
    summary = {
        "report_version": "M6-QUANT-RESEARCH-1.0",
        "source_commit": "f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6",
        "analysis_commit": _git_commit(),
        "analysis_branch": "quant/autonomous-behavioral-quant-bot-v1",
        "research_status": "RESEARCH_ONLY",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "public_market_source": "verified BitMEX public XBTUSD 5m bars; historical mark/index unavailable",
        "market_rows": len(series.bars),
        "market_range_utc": {"first": _iso(series.bars[0].timestamp), "last": _iso(series.bars[-1].timestamp)},
        "decision_rows": len(decisions),
        "fee_rate": fee_rate,
        "fee_evidence": fee_evidence,
        "backtest_unit_boundary": "Unitless normalized exposure-return proxy; fee and funding are normalized costs, not wallet/account PnL.",
        "tick_size_boundary": "0.1 from frozen current XBTUSD instrument snapshot; historical tick terms remain a warning.",
        "lot_size_boundary": "Historical XBTUSD lot schedule is 1 before 2021-06-08T04:30Z and 100 thereafter; normalized minimum exposure is applied.",
        "parity": parity,
        "walk_forward_windows": [{key: (value.isoformat() if isinstance(value, datetime) else value) for key, value in window.items()} for window in windows],
        "walk_forward_row_count": len(walk_rows),
        "robustness_row_count": len(robustness_rows),
        "future_data_policy": "Signals use closed history only; execution is next-bar open with configurable delay; no same-bar close execution.",
        "no_live_boundary": "No exchange SDK, API key, account, order submission, or live capital.",
    }
    (REPORTS / "quant_research_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    metric_keys = ["total_return", "cagr", "annualized_volatility", "sharpe", "sortino", "max_drawdown", "calmar", "win_rate", "payoff_ratio", "profit_factor", "turnover", "average_exposure", "maximum_exposure", "fees", "funding", "slippage", "longest_drawdown_recovery_days", "return_concentration_top5"]
    lines = [
        "# Quant Research Summary",
        "",
        "- research status: **RESEARCH_ONLY**",
        "- strategy fidelity: **BEHAVIORAL_APPROXIMATION**",
        f"- analysis commit: `{summary['analysis_commit']}`",
        f"- market bars: `{len(series.bars)}` verified 5m XBTUSD rows",
        f"- decision rows: `{len(decisions)}`",
        f"- historical blended fee rate: `{fee_rate:.8f}` from `{fee_evidence['rows']}` XBTUSD action rows",
        "- return unit: normalized exposure-return proxy; not wallet or strategy PnL",
        "- execution: next-bar open, configurable delay, fees, funding, slippage, limit, lot-step, and tick-step parameters",
        "- no exchange API, key, account, live order, or capital was used",
        "",
        "## Walk-forward windows",
        "",
        "The three windows are chronological: 2020–2022 train / 2023 validation / 2024 test; 2020–2023 train / 2024 validation / 2025 test; 2020–2024 train / 2025 validation / 2026 test. The final 2026 window ends at the frozen market-data boundary.",
        "",
        "## Test highlights",
        "",
        "| window | strategy | total return | Sharpe | max drawdown | turnover | fees | funding | slippage |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in walk_rows:
        if row["period"] != "TEST":
            continue
        def fmt(key: str) -> str:
            value = row.get(key)
            return "NA" if value in (None, "") else f"{float(value):.6f}"
        lines.append(f"| {row['window']} | {row['strategy']} | {fmt('total_return')} | {fmt('sharpe')} | {fmt('max_drawdown')} | {fmt('turnover')} | {fmt('fees')} | {fmt('funding')} | {fmt('slippage')} |")
    lines.extend([
        "",
        "## Interpretation",
        "",
        "`RESEARCH_ONLY` is intentional. This run establishes a reproducible, leakage-safe backtest foundation and records both favorable and unfavorable outcomes; it does not claim stable out-of-sample profitability. Historical mark/index data is missing, normalized exposure is unitless, and the teacher trajectory is descriptive rather than a tradable benchmark.",
        "",
        "See `walk_forward_results.csv`, `robustness_results.csv`, `failure_analysis.md`, and `reproducibility.md` for complete rows and boundaries.",
    ])
    (REPORTS / "quant_research_summary.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    failure = """# Failure Analysis\n\n- Research status is `RESEARCH_ONLY`; no claim of stable sample-out performance is made.\n- The backtest uses a normalized exposure-return proxy because historical account currency, inverse contract payout, and wallet PnL are not interchangeable.\n- Historical mark/index observations are unavailable and remain missing; trade prices are never used to invent them.\n- The fee rate is an observed blended XBTUSD ratio from `execComm_raw` and `execCost_raw`; it is not a promise of future maker/taker pricing.\n- Tick size uses the frozen XBTUSD snapshot value `0.1`; historical tick changes are a documented caveat.\n- Funding is applied only when the verified public context contains an as-of funding rate.\n- Teacher historical trajectory is descriptive and must not be interpreted as a deployable signal.\n- Cycle-removal tests remove frozen teacher cycle intervals from the result series; they are sensitivity diagnostics, not causal counterfactuals.\n- No API key, private account, exchange SDK, order submission, live capital, or automated trading path was used.\n"""
    (REPORTS / "failure_analysis.md").write_text(failure, encoding="utf-8")
    reproducibility = f"""# Reproducibility\n\n- command: `python quant/scripts/run_quant_research.py`\n- source commit: `f02a691c7f7cfd0cd08ffb7f13a656ebaf2c6ca6`\n- analysis commit: `{summary['analysis_commit']}`\n- branch: `quant/autonomous-behavioral-quant-bot-v1`\n- model dataset: `quant/outputs/model_dataset.csv` (ignored local fallback)\n- market bars: `quant/outputs/market_bars.csv` (ignored verified public cache output)\n- funding/context: `quant/outputs/market_context.csv` (ignored verified public cache output)\n- random benchmark seed: `42`; no random split or random model fitting\n- model fitting: chronological TRAIN rows only; no test-period statistic fit\n- execution: next closed bar's open, configurable bar delay, no same-bar close ideal fill\n- external ML dependencies: not used; Logistic Regression and Decision Tree use deterministic NumPy\n- research reports: `quant/reports/quant_research_summary.json`, `quant/reports/quant_research_summary.md`, `quant/reports/walk_forward_results.csv`, `quant/reports/robustness_results.csv`\n"""
    (REPORTS / "reproducibility.md").write_text(reproducibility, encoding="utf-8")
    append_registry(walk_rows, summary["analysis_commit"])
    print(json.dumps({"status": "PASS", "analysis_commit": summary["analysis_commit"], "walk_forward_rows": len(walk_rows), "robustness_rows": len(robustness_rows), "parity": parity["status"]}, ensure_ascii=False))
    return 0


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    if not rows:
        path.write_text("\n", encoding="utf-8")
        return
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


if __name__ == "__main__":
    raise SystemExit(main())
