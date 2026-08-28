"""Strict zero-start replay for public OKX market-context features.

This module deliberately keeps the teacher account data out of the replay
state.  The frozen strategy artifact is evaluated on closed OKX bars, with a
simulated position, costs, funding and next-bar-open execution.  It is a
research artifact only; it has no exchange client and cannot submit orders.
"""

from __future__ import annotations

import csv
import math
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from quant_bot.strategy.base import StrategySignal
from quant_bot.strategy.feature_contract import strategy_input_from_row


UTC = timezone.utc
IDLE_ACTIONS = {"NO_TRADE", "HOLD_LONG", "HOLD_SHORT"}


def parse_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        result = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            result = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def finite_float(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def derive_action(current: float, target: float, *, epsilon: float = 1e-9) -> str:
    """Derive the executable action from exposure transition, not a loose head."""

    current = max(-1.0, min(1.0, float(current)))
    target = max(-1.0, min(1.0, float(target)))
    if abs(target - current) <= epsilon:
        if abs(current) <= epsilon:
            return "NO_TRADE"
        return "HOLD_LONG" if current > 0 else "HOLD_SHORT"
    if abs(current) <= epsilon:
        return "OPEN_LONG" if target > 0 else "OPEN_SHORT"
    if abs(target) <= epsilon:
        return "CLOSE_LONG" if current > 0 else "CLOSE_SHORT"
    if (current > 0) != (target > 0):
        return "FLIP_LONG_TO_SHORT" if current > 0 else "FLIP_SHORT_TO_LONG"
    if abs(target) > abs(current):
        return "ADD_LONG" if target > 0 else "ADD_SHORT"
    return "REDUCE_LONG" if target > 0 else "REDUCE_SHORT"


def load_feature_rows(path: Path) -> list[dict[str, Any]]:
    """Load only confirmed closed rows and preserve missing context values."""

    rows: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise ValueError("OKX feature CSV is empty")
        required = {"timestamp", "bar_open_time_utc", "close", "decision_time_utc", "confirm", "closed"}
        missing = sorted(required - set(reader.fieldnames))
        if missing:
            raise ValueError(f"OKX feature CSV is missing columns: {missing}")
        for source in reader:
            confirm = str(source.get("confirm") or "").strip().lower()
            closed = str(source.get("closed") or "").strip().lower()
            if confirm not in {"1", "true"} or closed != "true":
                continue
            decision = parse_time(source.get("decision_time_utc"))
            close = finite_float(source.get("close"))
            bar_open = parse_time(source.get("bar_open_time_utc"))
            bar_close = parse_time(source.get("timestamp"))
            if decision is None or bar_open is None or bar_close is None or close is None or close <= 0:
                continue
            row = dict(source)
            row["_decision_time"] = decision
            row["_bar_open_time"] = bar_open
            row["_bar_close_time"] = bar_close
            row["_close"] = close
            rows.append(row)
    rows.sort(key=lambda row: (row["_decision_time"], row["_bar_open_time"]))
    return rows


@dataclass
class AutonomousBehaviorState:
    """Only simulated execution history used by the model at replay time."""

    position: float = 0.0
    latest_action: str = ""
    action_history: list[str] = field(default_factory=list)
    add_count: int = 0
    reduce_count: int = 0
    flip_count: int = 0
    cycle_start: datetime | None = None
    last_execution_time: datetime | None = None

    def apply_execution(self, target: float, action: str, when: datetime) -> None:
        before = self.position
        if abs(target - before) <= 1e-12:
            return
        self.position = target
        self.latest_action = str(action)
        self.action_history = (self.action_history + [self.latest_action])[-3:]
        if "ADD" in self.latest_action:
            self.add_count += 1
        elif "REDUCE" in self.latest_action or "CLOSE" in self.latest_action:
            self.reduce_count += 1
        elif "FLIP" in self.latest_action:
            self.flip_count += 1
        if target == 0:
            self.cycle_start = None
        elif before == 0 or (before > 0) != (target > 0):
            self.cycle_start = when
        self.last_execution_time = when


def model_row(source: Mapping[str, Any], state: AutonomousBehaviorState) -> dict[str, Any]:
    """Map the OKX market-context row into the frozen strategy contract.

    OKX's USDT swap is linear.  Contract sizing is intentionally represented
    by a normalized scale of one here; exchange-specific multiplier and lot
    conversion remain the adapter's responsibility and are not fabricated in
    this research replay.
    """

    output = dict(source)
    decision = source["_decision_time"]
    output.update(
        {
            "decision_time": decision.isoformat().replace("+00:00", "Z"),
            "feature_symbol": str(source.get("inst_id") or "BTC-USDT-SWAP"),
            "feature_instrument_class": "DERIVATIVE",
            "feature_payout_model": "LINEAR",
            "feature_quote_currency": "USDT",
            "feature_settlement_currency": "USDT",
            "feature_market_bar_interval": str(source.get("bar") or "1H").lower(),
            "feature_contract_lot_size": source.get("feature_contract_lot_size"),
            "feature_multiplier_major": source.get("feature_multiplier_major"),
            "feature_latest_bar_time": source.get("feature_latest_bar_time") or source.get("timestamp"),
            "feature_latest_action": state.latest_action or "NO_TRADE",
            "feature_action_lag_1": state.action_history[-1] if state.action_history else "",
            "feature_action_lag_2": state.action_history[-2] if len(state.action_history) >= 2 else "",
            "feature_action_lag_3": state.action_history[-3] if len(state.action_history) >= 3 else "",
            "feature_current_net_position_contracts": state.position,
            "feature_current_normalized_exposure": state.position,
            "feature_position_scale_contracts": 1.0,
            "feature_cycle_duration_seconds": (
                (decision - state.cycle_start).total_seconds()
                if state.cycle_start is not None and state.position
                else None
            ),
            "feature_recent_add_count_24h": state.add_count,
            "feature_recent_reduce_count_24h": state.reduce_count,
            "feature_recent_flip_count_24h": state.flip_count,
            "feature_recent_realised_outcome": 0.0,
            "feature_realised_drawdown": 0.0,
            "feature_fee_accumulation_raw": 0.0,
            "feature_funding_accumulation_raw": 0.0,
            "feature_order_execution_style": "__MISSING__",
            "feature_ordering_confidence": "HIGH",
            "feature_accounting_confidence": "HIGH",
            "feature_history_last_decision_time": (
                state.last_execution_time.isoformat().replace("+00:00", "Z")
                if state.last_execution_time
                else ""
            ),
            "feature_funding_rate_missing": str(source.get("feature_funding_missing") or "true").lower(),
            "feature_mark_index_basis_missing": str(source.get("feature_mark_index_missing") or "true").lower(),
        }
    )
    return output


@dataclass
class ReplayEngine:
    fee_rate: float = 0.0005
    slippage_rate: float = 0.0001
    position: float = 0.0
    equity: float = 1.0
    fees: float = 0.0
    funding: float = 0.0
    slippage: float = 0.0
    gross_pnl: float = 0.0
    turnover: float = 0.0
    mark_price: float | None = None
    funding_sources_seen: set[str] = field(default_factory=set)
    pnl_steps: list[float] = field(default_factory=list)
    equity_curve: list[tuple[datetime, float]] = field(default_factory=list)
    orders: list[dict[str, Any]] = field(default_factory=list)

    def mark_to(self, price: float, when: datetime) -> None:
        if price <= 0:
            return
        change = 0.0
        if self.mark_price is not None and self.position:
            change = self.position * (price / self.mark_price - 1.0)
            self.equity += change
            self.gross_pnl += change
        self.mark_price = price
        self.pnl_steps.append(change)
        self.equity_curve.append((when, self.equity))

    def apply_funding(self, row: Mapping[str, Any], when: datetime) -> None:
        rate = finite_float(row.get("funding_rate"))
        source = str(row.get("funding_source_time") or row.get("funding_source_timestamp_utc") or "").strip()
        if rate is None or not source or source in self.funding_sources_seen:
            return
        self.funding_sources_seen.add(source)
        payment = self.position * rate
        self.funding += payment
        self.equity -= payment
        self.pnl_steps.append(-payment)
        self.equity_curve.append((when, self.equity))

    def execute(self, target: float, price: float, when: datetime, signal: StrategySignal, requested_target: float, *, execution_action: str | None = None) -> float:
        self.mark_to(price, when)
        delta = target - self.position
        if abs(delta) <= 1e-12:
            return 0.0
        fee = abs(delta) * self.fee_rate
        slip = abs(delta) * self.slippage_rate
        self.fees += fee
        self.slippage += slip
        self.turnover += abs(delta)
        self.equity -= fee + slip
        self.pnl_steps.extend((-fee, -slip))
        self.position = target
        self.orders.append(
            {
                "time": when.isoformat().replace("+00:00", "Z"),
                "action": execution_action or signal.action,
                "requested_target_exposure": requested_target,
                "filled_target_exposure": target,
                "delta_exposure": delta,
                "price": price,
                "confidence": float(signal.confidence),
            }
        )
        self.equity_curve.append((when, self.equity))
        return delta


def _metrics(engine: ReplayEngine) -> dict[str, Any]:
    curve = [value for _, value in engine.equity_curve]
    peak = 1.0
    max_drawdown = 0.0
    for value in curve:
        peak = max(peak, value)
        if peak:
            max_drawdown = max(max_drawdown, (peak - value) / peak)
    returns = [curve[index] / curve[index - 1] - 1.0 for index in range(1, len(curve)) if curve[index - 1]]
    mean_return = sum(returns) / len(returns) if returns else 0.0
    variance = sum((value - mean_return) ** 2 for value in returns) / max(1, len(returns) - 1) if returns else 0.0
    downside = [min(0.0, value) ** 2 for value in returns]
    annualizer = math.sqrt(24.0 * 365.0)
    gross_profit = sum(value for value in engine.pnl_steps if value > 0)
    gross_loss = abs(sum(value for value in engine.pnl_steps if value < 0))
    return {
        "final_equity": engine.equity,
        "net_return": engine.equity - 1.0,
        "gross_pnl": engine.gross_pnl,
        "fees": engine.fees,
        "funding_payment_net": engine.funding,
        "slippage_cost": engine.slippage,
        "max_drawdown": max_drawdown,
        "sharpe_annualized": mean_return / math.sqrt(variance) * annualizer if variance > 0 else None,
        "sortino_annualized": mean_return / math.sqrt(sum(downside) / max(1, len(downside))) * annualizer if any(downside) else None,
        "profit_factor": gross_profit / gross_loss if gross_loss > 0 else None,
        "trade_count": len(engine.orders),
        "turnover_exposure": engine.turnover,
        "positive_pnl_steps": sum(value > 0 for value in engine.pnl_steps),
        "negative_pnl_steps": sum(value < 0 for value in engine.pnl_steps),
    }


def _safe_target(signal: StrategySignal, current: float) -> float:
    if signal.action in IDLE_ACTIONS:
        return current
    return max(-1.0, min(1.0, float(signal.target_exposure)))


def run_strict_replay(
    rows: list[dict[str, Any]],
    model: Any,
    *,
    warmup_bars: int = 72,
    fill_ratio: float = 1.0,
    fee_rate: float = 0.0005,
    slippage_rate: float = 0.0001,
) -> dict[str, Any]:
    if not rows:
        raise ValueError("strict replay requires at least one closed market row")
    if not 0.0 < fill_ratio <= 1.0:
        raise ValueError("fill_ratio must be in (0, 1]")
    normalized_rows: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        decision = parse_time(row.get("_decision_time") or row.get("decision_time_utc") or row.get("decision_time"))
        bar_open = parse_time(row.get("_bar_open_time") or row.get("bar_open_time_utc"))
        bar_close = parse_time(row.get("_bar_close_time") or row.get("timestamp"))
        close = finite_float(row.get("_close") or row.get("close"))
        if decision is None or bar_open is None or bar_close is None or close is None or close <= 0:
            raise ValueError("strict replay row has invalid decision/bar/close time or price")
        row["_decision_time"] = decision
        row["_bar_open_time"] = bar_open
        row["_bar_close_time"] = bar_close
        row["_close"] = close
        normalized_rows.append(row)
    rows = normalized_rows
    state = AutonomousBehaviorState()
    engine = ReplayEngine(fee_rate=fee_rate, slippage_rate=slippage_rate)
    actions: Counter[str] = Counter()
    details: list[dict[str, Any]] = []
    pending: dict[str, Any] | None = None
    causal_violations = 0
    raw_action_mismatches = 0
    target_saturated_rows = 0
    indicator_missing: Counter[str] = Counter()

    for index, source in enumerate(rows):
        decision = source["_decision_time"]
        open_price = finite_float(source.get("open")) or source["_close"]
        close_price = source["_close"]
        if pending is not None:
            filled = pending["current"] + (pending["requested_target"] - pending["current"]) * fill_ratio
            delta = engine.execute(
                filled,
                open_price,
                source["_bar_open_time"],
                pending["signal"],
                pending["requested_target"],
                execution_action=pending["execution_action"],
            )
            state.apply_execution(filled, pending["execution_action"], source["_bar_open_time"])
            pending = None
        else:
            engine.mark_to(open_price, source["_bar_open_time"])
        engine.mark_to(close_price, decision)
        engine.apply_funding(source, decision)

        latest_bar = parse_time(source.get("feature_latest_bar_time") or source.get("timestamp"))
        funding_time = parse_time(source.get("feature_funding_source_time"))
        if latest_bar is None or latest_bar >= decision:
            causal_violations += 1
        if funding_time is not None and funding_time > decision:
            causal_violations += 1
        for key in ("feature_rsi_14", "feature_macd_histogram", "feature_bollinger_percent_b_20", "feature_volume_percentile_72bar", "feature_atr_14bar"):
            if finite_float(source.get(key)) is None:
                indicator_missing[key] += 1

        signal: StrategySignal | None = None
        requested_target = state.position
        if index >= warmup_bars:
            adapted = model_row(source, state)
            signal = model.predict(strategy_input_from_row(adapted))
            requested_target = _safe_target(signal, state.position)
            execution_action = derive_action(state.position, requested_target)
            actions[execution_action] += 1
            raw_action_mismatches += int(str(signal.action) != execution_action)
            target_saturated_rows += int(abs(requested_target) >= 1.0 - 1e-9)
            if index + 1 < len(rows) and abs(requested_target - state.position) > 1e-12:
                pending = {
                    "signal": signal,
                    "requested_target": requested_target,
                    "current": state.position,
                    "execution_action": execution_action,
                }
        details.append(
            {
                "decision_time": decision.isoformat().replace("+00:00", "Z"),
                "bar_open_time": source["_bar_open_time"].isoformat().replace("+00:00", "Z"),
                "bar_close_time": source["_bar_close_time"].isoformat().replace("+00:00", "Z"),
                "close": close_price,
                "current_exposure": state.position,
                "raw_model_action": signal.action if signal else "WARMUP",
                "predicted_action": execution_action if signal else "WARMUP",
                "predicted_target_exposure": requested_target,
                "confidence": float(signal.confidence) if signal else None,
                "equity_after_decision": engine.equity,
                "context_status": source.get("feature_context_status") or source.get("context_status") or "UNKNOWN",
                "funding_missing": source.get("feature_funding_missing"),
                "mark_index_missing": source.get("feature_mark_index_missing"),
            }
        )

    return {
        "engine": engine,
        "details": details,
        "action_counts": dict(sorted(actions.items())),
        "raw_action_mismatch_count": raw_action_mismatches,
        "target_saturated_rows": target_saturated_rows,
        "warmup_bars": warmup_bars,
        "warmup_rows": min(warmup_bars, len(rows)),
        "signal_rows": max(0, len(rows) - warmup_bars),
        "causal_timestamp_violation_count": causal_violations,
        "indicator_missing_counts": dict(indicator_missing),
        "metrics": _metrics(engine),
        "state_source": "SIMULATED_ZERO_START",
        "teacher_dynamic_state_consumed": False,
    }


def run_buy_and_hold(rows: list[dict[str, Any]], *, warmup_bars: int = 72, fee_rate: float = 0.0005, slippage_rate: float = 0.0001) -> dict[str, Any]:
    engine = ReplayEngine(fee_rate=fee_rate, slippage_rate=slippage_rate)
    start = min(warmup_bars, len(rows) - 1)
    for index, row in enumerate(rows):
        open_price = finite_float(row.get("open")) or row["_close"]
        if index == start:
            engine.execute(1.0, open_price, row["_bar_open_time"], _hold_signal(row["_decision_time"]), 1.0)
        else:
            engine.mark_to(open_price, row["_bar_open_time"])
        engine.mark_to(row["_close"], row["_decision_time"])
        engine.apply_funding(row, row["_decision_time"])
    return _metrics(engine)


def _hold_signal(when: datetime) -> StrategySignal:
    from quant_bot.strategy.base import make_signal

    return make_signal(when, target_exposure=1.0, action="OPEN_LONG", confidence=1.0, strategy_version="BUY_AND_HOLD_BASELINE")


__all__ = [
    "AutonomousBehaviorState",
    "ReplayEngine",
    "derive_action",
    "finite_float",
    "load_feature_rows",
    "model_row",
    "parse_time",
    "run_buy_and_hold",
    "run_strict_replay",
]
