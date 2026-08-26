from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from quant_bot.strategy.base import StrategySignal, make_signal
from research.autonomous_replay import merge_same_time_signals, roll_forward_predictions


UTC = timezone.utc


class RecordingModel:
    def __init__(self) -> None:
        self.inputs = []

    def predict(self, strategy_input):
        self.inputs.append(strategy_input)
        target = 0.25 if strategy_input.current_strategy_position == 0 else 0.0
        return make_signal(strategy_input.decision_time, target_exposure=target, action="OPEN_LONG" if target else "CLOSE_LONG", confidence=0.9, strategy_version="test")


def _row(when: datetime, episode: str, current: float, target: float) -> dict[str, object]:
    return {
        "decision_time": when.isoformat().replace("+00:00", "Z"),
        "decision_episode_id": episode,
        "source_venue": "HYPERLIQUID",
        "canonical_asset": "BTC-PERP",
        "symbol": "HL-BTC-PERP",
        "label_status": "AVAILABLE",
        "label_next_action": "CLOSE_LONG",
        "raw_current_position_contracts": current,
        "raw_target_position_contracts": target,
        "raw_next_target_position_contracts": target,
        "feature_position_scale_contracts": 1.0,
        "feature_current_net_position_contracts": current,
        "feature_current_normalized_exposure": current,
        # This deliberately conflicts with the autonomous zero-start state.
        "feature_latest_action": "TEACHER_FAKE_ACTION",
    }


def test_same_time_aliases_produce_one_confidence_weighted_event() -> None:
    when = datetime(2025, 1, 1, tzinfo=UTC)
    left = make_signal(when, target_exposure=0.4, action="OPEN_LONG", confidence=0.8, strategy_version="test")
    right = make_signal(when, target_exposure=-0.2, action="OPEN_SHORT", confidence=0.2, strategy_version="test")
    merged = merge_same_time_signals([(_row(when, "a", 0, 0), left), (_row(when, "b", 0, 0), right)], key="HYPERLIQUID:BTC-PERP", decision_time=when)
    assert merged is not None
    assert merged["target_exposure"] == 0.28
    assert len(merged["source_signals"]) == 2


def test_autonomous_replay_overrides_teacher_state_and_starts_at_zero() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    rows = [_row(start, "a", 99, 99), _row(start + timedelta(hours=2), "b", -55, -55)]
    model = RecordingModel()
    result = roll_forward_predictions(model, rows, {"HYPERLIQUID:BTC-PERP": 100.0}, market_bar_opens={"HYPERLIQUID:BTC-PERP": [start + timedelta(hours=1), start + timedelta(hours=3)]})
    assert result["state_source"] == "SIMULATED_ZERO_START"
    assert result["teacher_state_fields_consumed"] == 0
    assert model.inputs[0].current_strategy_position == 0.0
    assert model.inputs[1].current_strategy_position == 0.25
    assert all("TEACHER_FAKE_ACTION" not in item.features.values() for item in model.inputs)
