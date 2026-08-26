from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Keep the test runnable both from the repository root and under the normal
# pytest collection used by this repository.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "quant" / "scripts"))

from build_behavioral_strategy_spec import build_payload, render_markdown


def _sources() -> tuple[dict, dict, dict]:
    profile = {
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "overall": {"rows": 100, "non_idle_rows": 5, "non_idle_rate": 0.05, "action_counts": {"NO_TRADE": 95, "OPEN_LONG": 5}},
        "by_venue": {"BITMEX": {"rows": 100, "non_idle_rate": 0.05, "target_abs_mean": 0.1}},
        "holding_period_observed": {"mean_hours": 10},
        "action_interval_observed": {"mean_hours": 4},
    }
    pre_action = {
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "independent_quote_orderbook_history_present": False,
        "market_context": {"latest_closed_bar_strictly_before_decision": 100, "latest_bar_equal_or_after_decision": 0},
        "submission_time_alignment": {"non_idle_decisions_matched_to_order_episode": 5, "decision_time_equal_first_order_event": 5},
        "pre_action_trigger_assessment": {"complete_pre_action_trigger_context_available": False},
    }
    identifiability = {
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "venue_results": [{"venue": "BITMEX", "conditional_event_type": {"action_macro_f1": 0.4}, "strict_autonomous_timing_reference": {"f1": 0.0}}],
    }
    return profile, pre_action, identifiability


def test_spec_separates_observed_supported_and_unidentifiable() -> None:
    profile, pre_action, identifiability = _sources()
    payload = build_payload(profile=profile, pre_action=pre_action, identifiability=identifiability, generated_at_utc="2026-01-01T00:00:00Z")
    classifications = {layer["classification"] for layer in payload["layers"]}
    assert classifications == {"OBSERVED_FACT", "SUPPORTED_APPROXIMATION", "UNIDENTIFIABLE"}
    timing = next(layer for layer in payload["layers"] if layer["id"] == "pre_action_timing")
    assert timing["confidence"] == "BLOCKED"
    assert timing["evidence"]["complete_pre_action_trigger_context_available"] is False


def test_spec_prohibits_exact_learning_and_live_claims() -> None:
    profile, pre_action, identifiability = _sources()
    payload = build_payload(profile=profile, pre_action=pre_action, identifiability=identifiability)
    prohibited = " ".join(payload["prohibited_claims"])
    assert "exactly recovered" in prohibited
    assert "profitability" in prohibited
    assert payload["active_runtime"]["promotion_allowed"] is False
    assert payload["active_runtime"]["new_demo_orders_authorized"] is False


def test_spec_rejects_an_audit_that_claims_complete_trigger_context() -> None:
    profile, pre_action, identifiability = _sources()
    pre_action["pre_action_trigger_assessment"]["complete_pre_action_trigger_context_available"] = True
    with pytest.raises(ValueError, match="complete pre-action trigger context"):
        build_payload(profile=profile, pre_action=pre_action, identifiability=identifiability)


def test_markdown_exposes_chinese_summary_and_source_boundary() -> None:
    profile, pre_action, identifiability = _sources()
    payload = build_payload(profile=profile, pre_action=pre_action, identifiability=identifiability)
    markdown = render_markdown(payload)
    assert "目标仓位调整过程" in markdown
    assert "不可识别" in markdown
    assert "No credentials" in markdown
