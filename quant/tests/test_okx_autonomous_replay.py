from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT, ROOT / "quant" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from quant_bot.strategy.base import make_signal  # noqa: E402
from research.okx_autonomous_replay import derive_action, run_strict_replay  # noqa: E402


UTC = timezone.utc


def _row(index: int, *, open_price: float, close: float) -> dict[str, object]:
    open_time = datetime(2025, 1, 1, tzinfo=UTC) + timedelta(hours=index)
    close_time = open_time + timedelta(hours=1)
    return {
        "open": str(open_price),
        "close": str(close),
        "bar_open_time_utc": open_time.isoformat().replace("+00:00", "Z"),
        "timestamp": close_time.isoformat().replace("+00:00", "Z"),
        "decision_time_utc": (close_time + timedelta(milliseconds=1)).isoformat().replace("+00:00", "Z"),
        "feature_latest_bar_time": close_time.isoformat().replace("+00:00", "Z"),
        "confirm": "1",
        "closed": "true",
        "inst_id": "BTC-USDT-SWAP",
        "bar": "1H",
        "feature_context_status": "MARK_INDEX_MISSING",
        "funding_rate": "",
        "funding_source_time": "",
        "feature_mark_index_missing": "true",
        "feature_funding_missing": "true",
    }


def test_executable_action_is_derived_from_exposure_transition() -> None:
    assert derive_action(0.0, 0.5) == "OPEN_LONG"
    assert derive_action(-0.5, -0.2) == "REDUCE_SHORT"
    assert derive_action(0.4, -0.2) == "FLIP_LONG_TO_SHORT"
    assert derive_action(-0.4, 0.0) == "CLOSE_SHORT"
    assert derive_action(0.0, 0.0) == "NO_TRADE"


class IdleWithHiddenTarget:
    def predict(self, strategy_input):
        return make_signal(
            strategy_input.decision_time,
            target_exposure=0.8,
            action="NO_TRADE",
            confidence=0.9,
            strategy_version="TEST_IDLE",
        )


def test_idle_action_cannot_hide_a_position_change() -> None:
    result = run_strict_replay([_row(index, open_price=100, close=100) for index in range(3)], IdleWithHiddenTarget(), warmup_bars=0)
    assert result["metrics"]["trade_count"] == 0
    assert result["action_counts"] == {"NO_TRADE": 3}


class OpenThenHold:
    def predict(self, strategy_input):
        if strategy_input.current_strategy_position == 0:
            return make_signal(strategy_input.decision_time, target_exposure=1.0, action="OPEN_LONG", confidence=0.9, strategy_version="TEST")
        return make_signal(strategy_input.decision_time, target_exposure=1.0, action="HOLD_LONG", confidence=0.9, strategy_version="TEST")


def test_replay_starts_zero_and_executes_on_next_bar_open_with_costs() -> None:
    rows = [_row(0, open_price=100, close=105), _row(1, open_price=110, close=115), _row(2, open_price=120, close=120)]
    result = run_strict_replay(rows, OpenThenHold(), warmup_bars=0)
    assert result["state_source"] == "SIMULATED_ZERO_START"
    assert result["metrics"]["trade_count"] == 1
    assert result["metrics"]["fees"] > 0
    assert result["metrics"]["slippage_cost"] > 0
    assert result["metrics"]["net_return"] > 0


def test_future_market_context_is_counted_as_causal_violation() -> None:
    rows = [_row(0, open_price=100, close=100)]
    rows[0]["feature_latest_bar_time"] = "2025-01-01T01:00:00.001Z"
    result = run_strict_replay(rows, IdleWithHiddenTarget(), warmup_bars=0)
    assert result["causal_timestamp_violation_count"] == 1
