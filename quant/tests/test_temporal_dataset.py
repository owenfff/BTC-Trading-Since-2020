from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "quant" / "src"))
sys.path.insert(0, str(ROOT))
from features.market_features import build_market_features
SCRIPT = ROOT / "quant" / "scripts" / "build_cross_venue_temporal_dataset.py"
spec = importlib.util.spec_from_file_location("temporal_dataset", SCRIPT)
assert spec and spec.loader
temporal = importlib.util.module_from_spec(spec)
spec.loader.exec_module(temporal)

UTC = timezone.utc


def _market(count: int = 130) -> list[dict[str, object]]:
    start = datetime(2021, 1, 1, tzinfo=UTC)
    return [
        {
            "timestamp": start + timedelta(hours=index),
            "open": 100.0 + index,
            "high": 101.0 + index,
            "low": 99.0 + index,
            "close": 100.5 + index,
            "volume": 1000.0 + index,
            "mark_price": 100.5 + index,
            "index_price": 100.5 + index,
            "funding_rate": None,
            "funding_source_time": None,
        }
        for index in range(count)
    ]


def _event(event_id: str, when: datetime, before: float, after: float) -> dict[str, object]:
    return {
        "decision_episode_id": event_id,
        "decision_time": temporal.iso_time(when),
        "source_venue": "BITMEX",
        "source_symbol": "XBTUSD",
        "canonical_asset": "BTC-PERP",
        "symbol": "XBTUSD",
        "feature_symbol": "XBTUSD",
        "feature_instrument_class": "DERIVATIVE",
        "feature_payout_model": "INVERSE",
        "feature_quote_currency": "USD",
        "feature_settlement_currency": "XBT",
        "feature_market_bar_interval": "1h",
        "feature_contract_lot_size": "1",
        "feature_multiplier_major": "1",
        "raw_current_position_contracts": str(before),
        "raw_target_position_contracts": str(after),
        "observed_position_before_contracts": str(before),
        "observed_target_position_contracts": str(after),
        "observed_action": temporal._action(before, after),
        "feature_recent_add_count_24h": "0",
        "feature_recent_reduce_count_24h": "0",
        "feature_recent_flip_count_24h": "0",
        "feature_realised_drawdown": "0",
        "feature_fee_accumulation_raw": "0",
        "feature_funding_accumulation_raw": "0",
        "feature_order_execution_style": "",
        "feature_ordering_confidence": "HIGH",
        "feature_accounting_confidence": "HIGH",
        "feature_recent_realised_outcome": "",
        "feature_history_last_decision_time": "",
        "_time": when,
        "_before": before,
        "_after": after,
    }


def test_transition_actions_include_explicit_no_trade() -> None:
    assert temporal._action(0, 1) == "OPEN_LONG"
    assert temporal._action(1, 1) == "NO_TRADE"
    assert temporal._action(1, -1) == "FLIP_SHORT"
    assert temporal._action(-1, 0) == "CLOSE_SHORT"


def test_batch_features_match_reference_and_are_causal() -> None:
    market = _market()
    cache = temporal.precompute_market_features(market)
    when = market[100]["timestamp"]
    assert when in cache
    fast = cache[when]
    reference = build_market_features(market, when, timestamps=[row["timestamp"] for row in market], bar_seconds=3600)
    for key in ("feature_rsi_14", "feature_macd_histogram", "feature_bollinger_percent_b_20", "feature_atr_14bar", "feature_return_72bar"):
        assert fast[key] == reference[key]
    assert temporal.parse_time(fast["feature_latest_bar_time"]) < when


def test_build_rows_labels_gap_as_no_trade_and_is_deterministic() -> None:
    start = datetime(2021, 1, 1, tzinfo=UTC)
    events = {
        "BITMEX:BTC-PERP": [
            _event("e1", start + timedelta(hours=10, minutes=5), 0, 100),
            _event("e2", start + timedelta(hours=14, minutes=5), 100, 0),
        ]
    }
    market = {"BITMEX:BTC-PERP": _market(20)}
    rows_a, coverage_a = temporal.build_rows(events, market)
    rows_b, coverage_b = temporal.build_rows(events, market)
    assert [row["decision_episode_id"] for row in rows_a] == [row["decision_episode_id"] for row in rows_b]
    assert coverage_a == coverage_b
    assert any(row["label_next_action"] == "NO_TRADE" for row in rows_a)
    assert all(temporal.parse_time(row["feature_latest_bar_time"]) < temporal.parse_time(row["decision_time"]) for row in rows_a)


def test_dynamic_state_action_lags_use_only_prior_events() -> None:
    start = datetime(2021, 1, 1, tzinfo=UTC)
    events = [
        _event("e1", start + timedelta(hours=1), 0, 100),
        _event("e2", start + timedelta(hours=2), 100, 50),
    ]
    state = temporal._dynamic_state(events, 1, start + timedelta(hours=3), 50, 100)
    assert state["feature_action_lag_1"] == "REDUCE_LONG"
    assert state["feature_action_lag_2"] == "OPEN_LONG"
    assert state["feature_action_lag_3"] == ""
