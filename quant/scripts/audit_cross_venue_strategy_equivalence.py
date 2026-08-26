#!/usr/bin/env python3
"""Audit shared intent versus venue-native execution behavior.

This is a descriptive evidence report.  It does not assert that two public
accounts belong to the same person, does not merge venue records, and does
not create training labels.  The purpose is to make a safe boundary explicit
when a trader appears across more than one venue.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "quant" / "reports"
PROFILE = REPORT_DIR / "strategy_behavior_profile_v4.json"
HYPERLIQUID = REPORT_DIR / "external_hyperliquid_paul_audit.json"
ORDER_INTENT = REPORT_DIR / "hyperliquid_order_intent_audit.json"
OUTPUT = REPORT_DIR / "cross_venue_strategy_equivalence_audit.json"
OUTPUT_MD = REPORT_DIR / "cross_venue_strategy_equivalence_audit.md"
UTC = timezone.utc

FAMILIES = ("OPEN", "ADD", "REDUCE", "CLOSE", "FLIP", "NO_TRADE")


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _family(action: str) -> str:
    normalized = str(action or "").upper()
    for family in FAMILIES:
        if normalized == family or normalized.startswith(family + "_"):
            return family
    return "UNKNOWN"


def _family_counts(action_counts: Mapping[str, Any]) -> dict[str, int]:
    result: Counter[str] = Counter()
    for action, count in action_counts.items():
        family = _family(str(action))
        if family != "UNKNOWN":
            result[family] += int(count)
    return {family: int(result.get(family, 0)) for family in FAMILIES}


def _shares(counts: Mapping[str, int], denominator: int) -> dict[str, float | None]:
    if denominator <= 0:
        return {family: None for family in FAMILIES}
    return {family: counts.get(family, 0) / denominator for family in FAMILIES}


def _bitmex(profile: Mapping[str, Any]) -> dict[str, Any]:
    venue = profile.get("by_venue", {}).get("BITMEX", {})
    raw_counts = venue.get("action_counts", {})
    counts = _family_counts(raw_counts)
    action_events = sum(value for family, value in counts.items() if family != "NO_TRADE")
    rows = int(venue.get("rows") or 0)
    return {
        "venue": "BITMEX",
        "source_role": "teacher_behavior_profile",
        "source_report": "strategy_behavior_profile_v4.json",
        "rows_or_clock_rows": rows,
        "action_events": action_events,
        "action_event_rate": action_events / rows if rows else None,
        "action_family_counts": counts,
        "action_family_shares_among_rows": _shares(counts, rows),
        "action_family_shares_among_non_idle": _shares(counts, action_events),
        "holding_period_observed": profile.get("holding_period_observed", {}),
        "action_interval_observed": profile.get("action_interval_observed", {}),
    }


def _hyperliquid(source: Mapping[str, Any], order_intent: Mapping[str, Any]) -> dict[str, Any]:
    behavior = source.get("behavior", {})
    raw_counts = behavior.get("action_counts", {})
    counts = _family_counts(raw_counts)
    fills = int(source.get("coverage", {}).get("fills") or 0)
    action_events = sum(value for family, value in counts.items() if family != "NO_TRADE")
    order_profile = source.get("behavior_profile", {}).get("orders", {})
    execution_profile = source.get("behavior_profile", {}).get("execution", {})
    intent = order_intent.get("order_intent", {})
    return {
        "venue": "HYPERLIQUID",
        "source_role": "external_public_reference",
        "source_report": "external_hyperliquid_paul_audit.json",
        "rows_or_clock_rows": None,
        "fill_events": fills,
        "action_events": action_events,
        "action_event_rate_over_fills": action_events / fills if fills else None,
        "action_family_counts": counts,
        "action_family_shares_among_action_events": _shares(counts, action_events),
        "position_episodes": source.get("behavior_profile", {}).get("position_episodes", {}),
        "order_execution_style": {
            "unique_order_ids": order_profile.get("unique_order_ids"),
            "orders_with_filled_event": order_profile.get("orders_with_filled_event"),
            "orders_with_canceled_event": order_profile.get("orders_with_canceled_event"),
            "all_limit_orders": order_profile.get("all_limit_orders"),
            "all_gtc_orders": order_profile.get("all_gtc_orders"),
            "reduce_only_event_count": order_profile.get("reduce_only_event_count"),
            "crossed_fill_fraction": execution_profile.get("crossed_fill_fraction"),
            "fill_latency_ms_median": execution_profile.get("fill_latency_ms_median"),
        },
        "partial_pre_action_intent": {
            "status": order_intent.get("status"),
            "order_records": intent.get("order_records"),
            "unique_order_ids": intent.get("unique_order_ids"),
            "filled_status_fill_overlap": intent.get("filled_status_fill_overlap"),
            "complete_pre_action_trigger_context_available": order_intent.get("limitations", {}).get("complete_pre_action_trigger_context_available"),
        },
    }


def build_payload(*, profile: Mapping[str, Any], hyperliquid: Mapping[str, Any], order_intent: Mapping[str, Any], generated_at_utc: str | None = None) -> dict[str, Any]:
    bitmex = _bitmex(profile)
    hl = _hyperliquid(hyperliquid, order_intent)
    bitmex_families = {family for family, count in bitmex["action_family_counts"].items() if family != "NO_TRADE" and count > 0}
    hl_families = {family for family, count in hl["action_family_counts"].items() if family != "NO_TRADE" and count > 0}
    common = sorted(bitmex_families & hl_families)
    venue_native = [
        "contract_multiplier_and_settlement_currency",
        "symbol_and_market_availability",
        "fee_funding_margin_and_leverage_rules",
        "quote_depth_latency_and_order_queue",
        "order_lifecycle_and_fill_semantics",
    ]
    gates = {
        "shared_action_vocabulary": {
            "status": "SUPPORTED_APPROXIMATION" if {"OPEN", "ADD", "REDUCE", "FLIP"}.issubset(set(common)) else "INSUFFICIENT_EVIDENCE",
            "common_action_families": common,
            "detail": "The two sources share several high-level position-adjustment actions; this supports a shared vocabulary, not identical rules.",
        },
        "same_executable_policy": {
            "status": "NOT_ESTABLISHED",
            "detail": "Venue-native contract, market, cost, liquidity and execution context differ; records must remain separated.",
        },
        "same_trader_identity": {
            "status": "USER_PROVIDED_PREMISE_NOT_DATA_VERIFIED",
            "detail": "The audit accepts the research premise that the accounts are one trader, but the repository does not cryptographically prove identity from these reports.",
        },
        "exact_private_trigger_recovery": {
            "status": "BLOCKED",
            "detail": "The available sources do not contain complete pre-action quote/order-book state and private trigger intent for both venues.",
        },
    }
    return {
        "report_version": "M15-CROSS-VENUE-STRATEGY-EQUIVALENCE-1.0",
        "status": "SHARED_INTENT_SUPPORTED_VENUE_NATIVE_POLICY_REQUIRED",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "generated_at_utc": generated_at_utc or datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "scope": {
            "venues": ["BITMEX", "HYPERLIQUID"],
            "records_merged": False,
            "hyperliquid_used_as_training_label": False,
            "identity_assumption": "The requester states that the public accounts represent the same trader; this is treated as a research premise, not as a data-derived fact.",
        },
        "venue_profiles": {"BITMEX": bitmex, "HYPERLIQUID": hl},
        "shared_behavior_evidence": {
            "common_action_families": common,
            "supported_high_level_intent": ["stateful inventory adjustment", "open/add/reduce/flip vocabulary", "position episodes rather than isolated fills"],
        },
        "venue_native_execution_boundary": venue_native,
        "gates": gates,
        "modeling_rule": "Use a shared high-level intent layer with independent venue adapters/calibration; never combine positions, units, fees, funding or order books across venues.",
        "promotion_allowed": False,
        "active_demo_unchanged": True,
        "raw_inputs_untouched": True,
        "conclusion": "The evidence supports a common behavioral skeleton, but not an identical executable policy or complete recovery of the trader's private strategy.",
    }


def render_markdown(payload: Mapping[str, Any]) -> str:
    bitmex = payload["venue_profiles"]["BITMEX"]
    hl = payload["venue_profiles"]["HYPERLIQUID"]
    gates = payload["gates"]
    lines = [
        "# Cross-Venue Strategy Equivalence Audit",
        "",
        f"> Status: **`{payload['status']}`**. This is a descriptive boundary report, not a model promotion or identity proof.",
        "",
        "## Direct answer",
        "",
        "如果两个公开账户确实属于同一个交易员，最合理的解释是：**共享高层交易意图，但执行策略按交易所条件变化**。同一人的仓位管理习惯可以一致，订单价格、数量、时机和风险尺度不应直接视为一致。",
        "",
        "## Venue evidence",
        "",
        "| venue | source role | observations | action events | execution evidence |",
        "|---|---|---:|---:|---|",
        f"| BITMEX | teacher behavior profile | {bitmex['rows_or_clock_rows']} clock rows | {bitmex['action_events']} | lifecycle/order export; no independent historical order-book stream |",
        f"| Hyperliquid | external public reference | {hl['fill_events']} fills | {hl['action_events']} | {hl['order_execution_style']['all_limit_orders']} Limit, {hl['order_execution_style']['all_gtc_orders']} GTC in the pinned snapshot |",
        "",
        "Common action families observed: `" + ", ".join(payload["shared_behavior_evidence"]["common_action_families"]) + "`.",
        "",
        "The denominators are intentionally not treated as interchangeable: BitMEX is a clock-row behavior profile while Hyperliquid is a partial public order/fill snapshot.",
        "",
        "## What can be shared",
        "",
        "- 有状态目标仓位调整；",
        "- 开仓、加仓、减仓、反手等高层动作词汇；",
        "- 持仓 episode、分批调整和观望路径。",
        "",
        "## What must stay venue-native",
        "",
    ]
    lines.extend(f"- `{item}`；" for item in payload["venue_native_execution_boundary"])
    lines += [
        "",
        "## Gates",
        "",
        "| gate | status | detail |",
        "|---|---|---|",
    ]
    for name, gate in gates.items():
        lines.append(f"| `{name}` | **{gate['status']}** | {gate['detail']} |")
    lines += [
        "",
        "## Modeling rule",
        "",
        f"`{payload['modeling_rule']}`",
        "",
        "当前结论仍为 `BEHAVIORAL_APPROXIMATION`；本报告不授权模型切换、不新增 Demo 订单、不连接主网。原始 CSV/JSON 保持不变。",
    ]
    return "\n".join(lines) + "\n"


def build(*, output: Path = OUTPUT, markdown: Path = OUTPUT_MD) -> dict[str, Any]:
    payload = build_payload(
        profile=_read_json(PROFILE),
        hyperliquid=_read_json(HYPERLIQUID),
        order_intent=_read_json(ORDER_INTENT),
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown.write_text(render_markdown(payload), encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    parser.add_argument("--markdown", type=Path, default=OUTPUT_MD)
    args = parser.parse_args()
    try:
        payload = build(output=args.output.resolve(), markdown=args.markdown.resolve())
    except (FileNotFoundError, OSError, ValueError, json.JSONDecodeError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "CROSS_VENUE_EQUIVALENCE_AUDIT_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": payload["status"], "report": str(args.output.resolve()), "markdown": str(args.markdown.resolve()), "common_action_families": payload["shared_behavior_evidence"]["common_action_families"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
