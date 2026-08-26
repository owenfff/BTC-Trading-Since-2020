from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "quant" / "scripts"))

from audit_hyperliquid_order_intent import analyze_order_intent


def test_order_intent_matches_fills_and_preserves_pre_fill_time() -> None:
    orders = [
        {"order": {"oid": 7, "coin": "BTC", "side": "B", "limitPx": "100", "sz": "1", "origSz": "1", "orderType": "Limit", "tif": "Gtc", "timestamp": 1000, "reduceOnly": False, "isTrigger": False}, "status": "open", "statusTimestamp": 1000},
        {"order": {"oid": 7, "coin": "BTC", "side": "B", "limitPx": "100", "sz": "0", "origSz": "1", "orderType": "Limit", "tif": "Gtc", "timestamp": 1000, "reduceOnly": False, "isTrigger": False}, "status": "filled", "statusTimestamp": 2000},
    ]
    fills = [{"oid": 7, "time": 2000, "coin": "BTC", "px": "100", "sz": "1"}]
    result = analyze_order_intent(orders, fills)
    assert result["unique_order_ids"] == 1
    assert result["filled_status_fill_overlap"] == 1
    assert result["order_created_at_or_before_first_fill"] == 1


def test_order_intent_does_not_fabricate_missing_fill_join() -> None:
    result = analyze_order_intent([
        {"order": {"oid": 8, "timestamp": 3000, "orderType": "Limit", "tif": "Gtc"}, "status": "canceled", "statusTimestamp": 4000},
    ], [])
    assert result["filled_status_order_ids"] == 0
    assert result["filled_status_fill_overlap"] == 0
    assert result["order_created_at_or_before_first_fill"] == 0


def test_order_intent_keeps_status_lifecycle_separate_from_order_creation() -> None:
    result = analyze_order_intent([
        {"order": {"oid": 9, "timestamp": 1000, "orderType": "Limit", "tif": "Gtc"}, "status": "open", "statusTimestamp": 1000},
        {"order": {"oid": 9, "timestamp": 1000, "orderType": "Limit", "tif": "Gtc"}, "status": "canceled", "statusTimestamp": 5000},
    ], [])
    assert result["orders_per_id"] == {2: 1}
    assert result["status_counts"] == {"canceled": 1, "open": 1}
