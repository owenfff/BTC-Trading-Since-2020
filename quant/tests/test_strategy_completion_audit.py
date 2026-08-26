from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "quant" / "scripts"))

from audit_strategy_completion import build_payload, render_markdown


def _sources() -> dict[str, dict]:
    return {
        "state": {"test_count": 397, "research_status": "RESEARCH_ONLY"},
        "profile": {"overall": {"rows": 10, "non_idle_rows": 1, "non_idle_rate": 0.1}, "by_venue": {"BITMEX": {}}},
        "pre_action": {
            "market_context": {"latest_closed_bar_strictly_before_decision": 10, "latest_bar_equal_or_after_decision": 0},
            "pre_action_trigger_assessment": {"complete_pre_action_trigger_context_available": False},
        },
        "identifiability": {"venue_results": [{"venue": "BITMEX", "strict_autonomous_timing_reference": {"f1": 0.0}}]},
        "behavior_spec": {"active_runtime": {"promotion_allowed": False}},
        "hyperliquid_order_intent": {"status": "PARTIAL_PRE_ACTION_CONTEXT", "quality_checks": {"filled_order_join_rate": 1.0}},
        "hyperliquid_l2_archive": {"status": "REQUESTER_OR_OBJECT_ACCESS_BLOCKED", "download_performed": False},
        "native": {"status": "DIAGNOSTIC_ONLY"},
        "shared_intent": {"status": "DIAGNOSTIC_ONLY"},
        "shared_timing": {"status": "DIAGNOSTIC_ONLY"},
    }


def test_completion_audit_fails_exact_and_autonomous_gates() -> None:
    payload = build_payload(sources=_sources(), generated_at_utc="2026-01-01T00:00:00Z")
    assert payload["status"] == "NOT_COMPLETE"
    failed = {gate["id"] for gate in payload["gates"] if gate["status"] == "FAIL"}
    assert {"exact_strategy_recovery", "pre_action_trigger_context", "strict_autonomous_timing"} <= failed


def test_completion_audit_keeps_causal_bar_gate_separate() -> None:
    payload = build_payload(sources=_sources())
    causal = next(gate for gate in payload["gates"] if gate["id"] == "causal_closed_bar_features")
    assert causal["status"] == "PASS"
    assert payload["current_runtime"]["new_demo_orders_authorized"] is False


def test_completion_markdown_answers_user_directly() -> None:
    markdown = render_markdown(build_payload(sources=_sources()))
    assert "没有完全学会" in markdown
    assert "目标仓位调整" in markdown
    assert "不新增 Demo 订单" in markdown
