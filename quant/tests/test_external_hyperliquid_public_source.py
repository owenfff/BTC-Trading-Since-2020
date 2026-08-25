from __future__ import annotations

import importlib.util
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve().parents[1] / "scripts" / "audit_hyperliquid_public_source.py"
SPEC = importlib.util.spec_from_file_location("audit_hyperliquid_public_source", SCRIPT_PATH)
assert SPEC and SPEC.loader
audit_source = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(audit_source)


def test_behavior_profile_is_descriptive_and_separate() -> None:
    orders = [
        {"order": {"oid": 1, "orderType": "Limit", "tif": "Gtc", "reduceOnly": False, "timestamp": 1000}, "status": "open", "statusTimestamp": 1000},
        {"order": {"oid": 1, "orderType": "Limit", "tif": "Gtc", "reduceOnly": False, "timestamp": 1000}, "status": "filled", "statusTimestamp": 2000},
        {"order": {"oid": 2, "orderType": "Limit", "tif": "Gtc", "reduceOnly": False, "timestamp": 1000}, "status": "open", "statusTimestamp": 1000},
        {"order": {"oid": 2, "orderType": "Limit", "tif": "Gtc", "reduceOnly": False, "timestamp": 1000}, "status": "canceled", "statusTimestamp": 3000},
    ]
    fills = [
        {"oid": 1, "tid": 10, "time": 2000, "side": "B", "sz": "1", "px": "100", "fee": "0.1", "crossed": False},
        {"oid": 1, "tid": 11, "time": 4000, "side": "A", "sz": "1", "px": "110", "fee": "0.1", "crossed": True},
    ]
    replay_rows = [
        {"time": 2000, "before": "0", "after": "1", "action": "OPEN_LONG"},
        {"time": 4000, "before": "1", "after": "0", "action": "CLOSE_LONG"},
    ]

    profile = audit_source.build_behavior_profile(orders, fills, replay_rows)

    assert profile["orders"]["unique_order_ids"] == 2
    assert profile["orders"]["orders_with_filled_event"] == 1
    assert profile["orders"]["orders_with_canceled_event"] == 1
    assert profile["execution"]["crossed_fill_count"] == 1
    assert profile["position_episodes"]["closed_episode_count"] == 1
    assert profile["position_episodes"]["open_at_end_count"] == 0
    assert profile["interpretation_boundary"]
