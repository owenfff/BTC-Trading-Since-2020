from __future__ import annotations

from datetime import datetime, timezone

from audit_shared_intent_native_layer import (
    apply_native_layer,
    chronological_three_way,
    fit_native_exposure_layer,
    intent_action,
    neutralize_for_shared_intent,
)
from quant_bot.strategy.base import make_signal


def test_intent_action_collapses_direction_without_losing_family() -> None:
    assert intent_action("OPEN_LONG") == "OPEN"
    assert intent_action("ADD_SHORT") == "ADD"
    assert intent_action("CLOSE_LONG") == "REDUCE"
    assert intent_action("FLIP_SHORT") == "FLIP"
    assert intent_action("NO_TRADE") == "NO_TRADE"


def test_three_way_split_is_ordered_and_non_overlapping() -> None:
    rows = [{"decision_time": f"2026-01-{day:02d}T00:00:00Z"} for day in range(1, 11)]
    train, calibration, test = chronological_three_way(rows)
    assert len(train) == 6
    assert len(calibration) == 2
    assert len(test) == 2
    assert train[-1]["decision_time"] < calibration[0]["decision_time"] < test[0]["decision_time"]


def test_neutralization_keeps_missingness_and_removes_contract_units() -> None:
    row = {
        "canonical_asset": "BTC-PERP",
        "feature_symbol": "HYPERLIQUID:BTC-PERP",
        "feature_payout_model": "LINEAR",
        "feature_quote_currency": "USDC",
        "feature_settlement_currency": "USDC",
        "feature_contract_lot_size": "1",
        "feature_multiplier_major": "1",
        "feature_current_normalized_exposure": "0.2",
        "feature_funding_rate": "0.0001",
        "feature_mark_index_basis": "0.01",
        "label_next_action": "OPEN_LONG",
    }
    output = neutralize_for_shared_intent(row)
    assert output["feature_symbol"] == "BTC-PERP"
    assert output["feature_payout_model"] == "VENUE_NEUTRAL"
    assert output["feature_current_net_position_contracts"] == 0.2
    assert output["feature_funding_rate"] is None
    assert output["feature_funding_rate_missing"] is True
    assert output["label_next_action"] == "OPEN"


def test_native_layer_resizes_without_reversing_direction() -> None:
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    signal = make_signal(dt, target_exposure=0.5, action="OPEN", confidence=0.8)
    resized = apply_native_layer(signal, {"intercept": 0.0, "slope": 0.4})
    assert resized.target_exposure == 0.2
    assert "VENUE_NATIVE_EXPOSURE_LAYER" in resized.risk_tags


def test_native_layer_fit_is_bounded_and_train_only() -> None:
    rows = [{"decision_episode_id": str(index), "label_next_target_exposure": str(value)} for index, value in enumerate([0.2, 0.4, -0.2, -0.4] * 10)]
    predictions = []
    dt = datetime(2026, 1, 1, tzinfo=timezone.utc)
    for index, value in enumerate([0.1, 0.2, -0.1, -0.2] * 10):
        predictions.append((rows[index], make_signal(dt, target_exposure=value, action="OPEN", confidence=0.8)))
    layer = fit_native_exposure_layer(rows, predictions)
    assert layer["status"] == "PASS"
    assert 0.0 <= layer["slope"] <= 2.0
    assert layer["residual_mae"] is not None
