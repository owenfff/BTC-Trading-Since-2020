#!/usr/bin/env python3
"""Audit whether the public-record strategy-learning objective is complete.

The audit is intentionally fail-closed: a descriptive profile, an
event-conditioned score, or green unit tests cannot be promoted to a claim
that a robot has learned the original trader's complete private strategy.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "quant" / "reports"
OUTPUT = REPORT_DIR / "strategy_completion_audit.json"
OUTPUT_MD = REPORT_DIR / "strategy_completion_audit.md"
UTC = timezone.utc

REQUIRED_REPORTS = {
    "state": ROOT / "quant" / "AUTONOMOUS_STATE.json",
    "profile": REPORT_DIR / "strategy_behavior_profile_v4.json",
    "pre_action": REPORT_DIR / "pre_action_observability_audit.json",
    "identifiability": REPORT_DIR / "identifiability_ceiling_audit.json",
    "behavior_spec": REPORT_DIR / "behavioral_strategy_spec_v1.json",
    "hyperliquid_order_intent": REPORT_DIR / "hyperliquid_order_intent_audit.json",
    "native": REPORT_DIR / "venue_native_behavior_audit.json",
    "shared_intent": REPORT_DIR / "shared_intent_native_layer_audit.json",
    "shared_timing": REPORT_DIR / "shared_intent_timing_audit.json",
}


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _gate(gate_id: str, status: str, evidence: str, detail: str) -> dict[str, str]:
    return {"id": gate_id, "status": status, "evidence": evidence, "detail": detail}


def _timing_f1(identifiability: Mapping[str, Any]) -> dict[str, float | None]:
    output: dict[str, float | None] = {}
    for result in identifiability.get("venue_results", []):
        if not isinstance(result, Mapping):
            continue
        timing = result.get("strict_autonomous_timing_reference", {})
        value = timing.get("f1") if isinstance(timing, Mapping) else None
        output[str(result.get("venue") or "UNKNOWN")] = float(value) if value is not None else None
    return output


def build_payload(*, sources: Mapping[str, Mapping[str, Any]], generated_at_utc: str | None = None) -> dict[str, Any]:
    state = sources["state"]
    profile = sources["profile"]
    pre_action = sources["pre_action"]
    identifiability = sources["identifiability"]
    behavior_spec = sources["behavior_spec"]
    hyperliquid_order_intent = sources["hyperliquid_order_intent"]
    native = sources["native"]
    shared_intent = sources["shared_intent"]
    shared_timing = sources["shared_timing"]

    overall = profile.get("overall", {})
    market_context = pre_action.get("market_context", {})
    assessment = pre_action.get("pre_action_trigger_assessment", {})
    timing = _timing_f1(identifiability)
    candidate_statuses = [
        str(native.get("status") or ""),
        str(shared_intent.get("status") or ""),
        str(shared_timing.get("status") or ""),
    ]
    blocked_candidates = sum(status in {"DIAGNOSTIC_ONLY", "DEMO_CONTINUE_LIVE_BLOCKED"} for status in candidate_statuses)
    tests = int(state.get("test_count") or 0)

    gates = [
        _gate(
            "exact_strategy_recovery",
            "FAIL",
            "behavior_spec.strategy_fidelity",
            "The evidence contract is BEHAVIORAL_APPROXIMATION, not an exact private-rule recovery.",
        ),
        _gate(
            "pre_action_trigger_context",
            "FAIL" if not assessment.get("complete_pre_action_trigger_context_available") else "PASS",
            "pre_action.pre_action_trigger_assessment.complete_pre_action_trigger_context_available",
            "Complete pre-action trigger, cancellation intent and order-book context are absent from the current public export.",
        ),
        _gate(
            "hyperliquid_partial_order_intent",
            "PASS" if hyperliquid_order_intent.get("status") == "PARTIAL_PRE_ACTION_CONTEXT" and hyperliquid_order_intent.get("quality_checks", {}).get("filled_order_join_rate") == 1.0 else "WARNING",
            "hyperliquid_order_intent.order_intent",
            "Hyperliquid submitted order terms are available for a recent snapshot and all filled-status order IDs in that snapshot join to fills; this improves execution analysis but is not complete trigger context.",
        ),
        _gate(
            "strict_autonomous_timing",
            "FAIL" if timing and all(value == 0.0 for value in timing.values() if value is not None) else "WARNING",
            "identifiability.venue_results[*].strict_autonomous_timing_reference.f1",
            f"Strict autonomous timing F1 by venue: {timing}.",
        ),
        _gate(
            "causal_closed_bar_features",
            "PASS" if market_context.get("latest_bar_equal_or_after_decision", 1) == 0 else "FAIL",
            "pre_action.market_context",
            f"{market_context.get('latest_closed_bar_strictly_before_decision', 0)} rows use a strictly prior closed bar; equal/after rows: {market_context.get('latest_bar_equal_or_after_decision', 0)}.",
        ),
        _gate(
            "candidate_promotion",
            "FAIL" if blocked_candidates == len(candidate_statuses) else "WARNING",
            "venue_native/shared_intent/shared_timing.status",
            f"{blocked_candidates}/{len(candidate_statuses)} latest venue-generalization candidates remain diagnostic or blocked; active model is unchanged.",
        ),
        _gate(
            "autonomous_demo_authorization",
            "FAIL" if not behavior_spec.get("active_runtime", {}).get("promotion_allowed", False) else "PASS",
            "behavior_spec.active_runtime.promotion_allowed",
            "The specification does not authorize Demo order additions or automatic model promotion.",
        ),
        _gate(
            "regression_verification",
            "PASS" if tests >= 397 else "WARNING",
            "state.test_count",
            f"Current recorded full-suite count is {tests}; this verifies code regressions, not strategy fidelity.",
        ),
    ]
    status = "COMPLETE" if all(gate["status"] == "PASS" for gate in gates) else "NOT_COMPLETE"
    return {
        "report_version": "M15-STRATEGY-COMPLETION-AUDIT-1.0",
        "status": status,
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "generated_at_utc": generated_at_utc or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "objective": "Determine whether the robot has fully learned the original trader's complete strategy from the available public records.",
        "completion_definition": [
            "exact private strategy recovery",
            "autonomous pre-action timing",
            "stable out-of-time validation",
            "authorized deployable model promotion",
        ],
        "gates": gates,
        "observed_behavior": {
            "eligible_rows": overall.get("rows"),
            "non_idle_rows": overall.get("non_idle_rows"),
            "non_idle_rate": overall.get("non_idle_rate"),
            "venues": sorted(str(value) for value in profile.get("by_venue", {})),
            "description": "Sparse, stateful inventory adjustment with explicit NO_TRADE and open/add/reduce/close/flip actions.",
        },
        "current_runtime": {
            "active_model_unchanged": True,
            "research_status": state.get("research_status"),
            "promotion_allowed": False,
            "new_demo_orders_authorized": False,
        },
        "next_action": "Keep the active Demo model unchanged. To pursue exact imitation, obtain a verified public source with pre-action quote/order-book and order-intent context; otherwise treat the auditable behavioral approximation as the honest ceiling and develop any standalone trading strategy as a separate objective.",
        "raw_inputs_untouched": True,
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Strategy Learning Completion Audit",
        "",
        f"> Overall status: **`{payload.get('status')}`**. This audit does not equate passing software tests with learning a private trading strategy.",
        "",
        "## Answer",
        "",
        "机器人**没有完全学会**原交易员的完整策略。当前完成的是可审计的行为近似：稀疏观望 + 有状态目标仓位调整 + 交易所原生执行约束。",
        "",
        "## Completion gates",
        "",
        "| gate | status | evidence | detail |",
        "|---|---|---|---|",
    ]
    for gate in payload.get("gates", []):
        detail = str(gate.get("detail", "")).replace("|", "\\|")
        lines.append(f"| `{gate.get('id')}` | **{gate.get('status')}** | `{gate.get('evidence')}` | {detail} |")
    lines += [
        "",
        "## What is actually distilled",
        "",
        "- 观察事实：多数时间 `NO_TRADE`；非空仓时围绕当前仓位执行开仓、加仓、减仓、平仓、反手。",
        "- 近似框架：目标库存优先；被动挂单作为执行近似；必要时做受限主动纠偏；风险和规格按交易所分开。",
        "- 未识别部分：精确触发秒点、当时盘口、撤单意图、私有风险限额和原交易员是否使用某个指标。",
        "",
        "## Runtime boundary",
        "",
        "当前 Demo 模型保持不变；本报告不允许自动模型切换、不新增 Demo 订单、不连接主网，也不构成盈利保证。",
        "",
        "## Next action",
        "",
        payload.get("next_action", ""),
        "",
        "No credentials, private endpoint, mainnet connection or order was used. Root raw CSV/JSON inputs remain read-only.",
    ]
    return "\n".join(lines) + "\n"


def build(*, report_path: Path = OUTPUT, markdown_path: Path = OUTPUT_MD) -> dict[str, Any]:
    sources = {name: _read_json(path) for name, path in REQUIRED_REPORTS.items()}
    payload = build_payload(sources=sources)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, default=OUTPUT)
    parser.add_argument("--markdown", type=Path, default=OUTPUT_MD)
    args = parser.parse_args()
    try:
        payload = build(report_path=args.report.resolve(), markdown_path=args.markdown.resolve())
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "STRATEGY_COMPLETION_AUDIT_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": payload["status"], "report": str(args.report.resolve()), "markdown": str(args.markdown.resolve()), "failed_gates": [gate["id"] for gate in payload["gates"] if gate["status"] == "FAIL"]}, ensure_ascii=False))
    return 0 if payload["status"] == "NOT_COMPLETE" else 1


if __name__ == "__main__":
    raise SystemExit(main())
