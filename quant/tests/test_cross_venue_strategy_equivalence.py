from __future__ import annotations

import sys

ROOT = __import__("pathlib").Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "quant" / "scripts"))

from audit_cross_venue_strategy_equivalence import build_payload, render_markdown


def _sources() -> tuple[dict, dict, dict]:
    profile = {
        "by_venue": {
            "BITMEX": {
                "rows": 100,
                "action_counts": {"NO_TRADE": 90, "OPEN_LONG": 2, "ADD_LONG": 3, "REDUCE_LONG": 3, "FLIP_SHORT": 1, "CLOSE_LONG": 1},
            }
        },
        "holding_period_observed": {"mean_hours": 10},
        "action_interval_observed": {"mean_hours": 2},
    }
    hyperliquid = {
        "coverage": {"fills": 5},
        "behavior": {"action_counts": {"OPEN_LONG": 1, "ADD_LONG": 1, "REDUCE_LONG": 2, "FLIP_SHORT": 1}},
        "behavior_profile": {
            "orders": {"unique_order_ids": 5, "orders_with_filled_event": 5, "orders_with_canceled_event": 0, "all_limit_orders": True, "all_gtc_orders": True, "reduce_only_event_count": 0},
            "execution": {"crossed_fill_fraction": "0", "fill_latency_ms_median": "1"},
            "position_episodes": {"episode_count": 1},
        },
    }
    intent = {"status": "PARTIAL_PRE_ACTION_CONTEXT", "order_intent": {"order_records": 5, "unique_order_ids": 5, "filled_status_fill_overlap": 5}, "limitations": {"complete_pre_action_trigger_context_available": False}}
    return profile, hyperliquid, intent


def test_shared_action_families_are_normalized_without_merging_records() -> None:
    payload = build_payload(profile=_sources()[0], hyperliquid=_sources()[1], order_intent=_sources()[2], generated_at_utc="2026-01-01T00:00:00Z")
    assert payload["scope"]["records_merged"] is False
    assert payload["shared_behavior_evidence"]["common_action_families"] == ["ADD", "FLIP", "OPEN", "REDUCE"]
    assert payload["gates"]["same_executable_policy"]["status"] == "NOT_ESTABLISHED"


def test_hyperliquid_missing_no_trade_is_not_treated_as_zero_clock_rows() -> None:
    payload = build_payload(profile=_sources()[0], hyperliquid=_sources()[1], order_intent=_sources()[2])
    assert payload["venue_profiles"]["HYPERLIQUID"]["rows_or_clock_rows"] is None
    assert payload["venue_profiles"]["HYPERLIQUID"]["action_family_counts"]["NO_TRADE"] == 0
    assert payload["gates"]["exact_private_trigger_recovery"]["status"] == "BLOCKED"


def test_markdown_preserves_boundary_language() -> None:
    payload = build_payload(profile=_sources()[0], hyperliquid=_sources()[1], order_intent=_sources()[2])
    rendered = render_markdown(payload)
    assert "BEHAVIORAL_APPROXIMATION" in rendered
    assert "共享高层交易意图" in rendered
    assert "不授权模型切换" in rendered
