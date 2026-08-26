from __future__ import annotations

from datetime import datetime, timedelta, timezone

from quant.scripts.audit_strategy_effectiveness import (
    MarketBar,
    _audit_leakage,
    evaluate_gates,
    merge_duplicate_signals,
    replay_next_bar,
)


UTC = timezone.utc


def _bars(*closes: float, opens: list[float] | None = None, funding: list[float | None] | None = None) -> list[MarketBar]:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    opens = opens or [100.0] * len(closes)
    funding = funding or [None] * len(closes)
    return [MarketBar(start + timedelta(hours=index), opens[index], close, funding[index], start + timedelta(hours=index) if funding[index] is not None else None) for index, close in enumerate(closes)]


def _event(when: datetime, target: float = 1.0, confidence: float = 1.0) -> dict[str, object]:
    return {"decision_time": when, "target_exposure": target, "action": "OPEN_LONG", "confidence": confidence}


def test_duplicate_aliases_merge_to_one_confidence_weighted_target() -> None:
    merged = merge_duplicate_signals([
        {"historical_symbol": "ADAUSD", "decision_time": "2024-01-01T00:00:00Z", "target_exposure": 0.4, "action": "OPEN_LONG", "confidence": 0.8},
        {"historical_symbol": "ADAUSDT", "decision_time": "2024-01-01T00:00:00Z", "target_exposure": 0.2, "action": "OPEN_LONG", "confidence": 0.2},
    ])
    assert len(merged) == 1
    assert merged[0]["venue_symbol"] == "ADA-USDT-SWAP"
    assert merged[0]["target_exposure"] == 0.36
    assert merged[0]["historical_symbols"] == ("ADAUSD", "ADAUSDT")


def test_decision_executes_at_strictly_next_bar_open() -> None:
    bars = _bars(200.0, 600.0, opens=[100.0, 300.0, 600.0])
    result = replay_next_bar(bars, [_event(bars[0].timestamp)], start_time=bars[0].timestamp, end_time=bars[-1].timestamp + timedelta(hours=1), fee_rate=0.0, slippage_ticks=0.0)
    # The first bar closes from 100 to 200 before the signal can execute.
    # The target is active from the second bar's open (300) to its close (600).
    assert result["net_return"] == 1.0


def test_funding_sign_and_missing_values_are_explicit() -> None:
    bars = _bars(100.0, 100.0, 100.0, funding=[None, 0.01, None])
    result = replay_next_bar(bars, [_event(bars[0].timestamp - timedelta(microseconds=1))], start_time=bars[0].timestamp, end_time=bars[-1].timestamp + timedelta(hours=1), fee_rate=0.0, slippage_ticks=0.0)
    assert result["funding"] == 0.01
    assert result["funding_events_observed"] == 1
    assert result["funding_events_missing"] == 2


def test_stress_cost_is_not_better_than_base_cost() -> None:
    bars = _bars(100.0, 110.0)
    event = _event(bars[0].timestamp - timedelta(microseconds=1))
    base = replay_next_bar(bars, [event], start_time=bars[0].timestamp, end_time=bars[-1].timestamp + timedelta(hours=1), fee_rate=0.001, tick_size=1.0, slippage_ticks=1.0)
    stress = replay_next_bar(bars, [event], start_time=bars[0].timestamp, end_time=bars[-1].timestamp + timedelta(hours=1), fee_rate=0.0015, tick_size=1.0, slippage_ticks=2.0)
    assert stress["net_return"] < base["net_return"]


def test_future_feature_and_zero_leakage_contract_are_detected() -> None:
    row = {
        "decision_time": "2024-01-01T00:00:00Z",
        "feature_latest_bar_time": "2024-01-01T01:00:00Z",
        "feature_funding_source_time": "",
        "feature_history_last_decision_time": "",
    }
    audit = _audit_leakage([row])
    assert audit["future_bar_observation_count"] == 1
    assert audit["status"] == "FAIL"


def test_unavailable_walk_forward_window_blocks_all_gates() -> None:
    gates = evaluate_gates([], [], leakage_status="PASS")
    assert gates["all_gates_pass"] is False
    assert gates["behavior_gates_pass"] is False
    assert gates["net_gates_pass"] is False
