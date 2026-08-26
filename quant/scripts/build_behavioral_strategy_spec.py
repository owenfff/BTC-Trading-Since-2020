#!/usr/bin/env python3
"""Build an evidence-bounded specification of the observable trading behavior.

This is deliberately not a model trainer and not an order-producing component.
It turns completed audits into a small, reviewable contract that distinguishes
observed facts, supported implementation hypotheses, and information that is
not identifiable from the public record.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
REPORT_DIR = ROOT / "quant" / "reports"
PROFILE = REPORT_DIR / "strategy_behavior_profile_v4.json"
PRE_ACTION = REPORT_DIR / "pre_action_observability_audit.json"
IDENTIFIABILITY = REPORT_DIR / "identifiability_ceiling_audit.json"
OUTPUT = REPORT_DIR / "behavioral_strategy_spec_v1.json"
OUTPUT_MD = REPORT_DIR / "behavioral_strategy_spec_v1.md"

SPEC_VERSION = "behavioral-strategy-spec-v1.0"
FIDELITY = "BEHAVIORAL_APPROXIMATION"
STATUS = "APPROXIMATION_ONLY"
UTC = timezone.utc

EXTERNAL_SOURCES = [
    {
        "kind": "PUBLIC_REPLAY_WEBSITE",
        "name": "Paul Wei Hyperliquid BTC tracker",
        "url": "https://paul.catseye.today/",
        "role": "visual replay and public-state cross-check",
        "limitations": "A replay of public candles, fills, orders and state snapshots; it does not by itself expose a complete pre-action quote/order-book history or private decision rule.",
    },
    {
        "kind": "INDEPENDENT_SECONDARY_ANALYSIS",
        "name": "TradeTrace Paul Wei trading pattern research",
        "url": "https://github.com/AaronL725/TradeTrace/blob/main/reports/paulwei-analysis.md",
        "role": "independent interpretation of observable execution and inventory patterns",
        "limitations": "Secondary analysis, not a private strategy disclosure or proof of causality; its conservative rules remain hypotheses.",
    },
]


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(path)
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _source_record(path: Path, payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)),
        "sha256": _sha256(path),
        "report_version": payload.get("report_version"),
        "status": payload.get("status"),
        "strategy_fidelity": payload.get("strategy_fidelity"),
    }


def _metric(profile: Mapping[str, Any], key: str, default: Any = None) -> Any:
    value = profile.get(key, default)
    return value


def _require_source_status(payload: Mapping[str, Any], path: Path, *, legacy_profile: bool = False) -> None:
    # The v4 profile predates the shared top-level fidelity field.  Its own
    # interpretation boundary explicitly declares the same limitation.
    if legacy_profile and payload.get("report_version") == "STRATEGY-BEHAVIOR-PROFILE-V4":
        return
    if payload.get("strategy_fidelity") != FIDELITY:
        raise ValueError(f"unexpected strategy fidelity in {path}")


def build_payload(
    *,
    profile: Mapping[str, Any],
    pre_action: Mapping[str, Any],
    identifiability: Mapping[str, Any],
    source_records: list[dict[str, Any]] | None = None,
    generated_at_utc: str | None = None,
) -> dict[str, Any]:
    """Build the deterministic strategy contract from completed audit facts."""

    if source_records is None:
        source_records = []
    _require_source_status(profile, Path("strategy_behavior_profile_v4.json"), legacy_profile=True)
    _require_source_status(pre_action, Path("pre_action_observability_audit.json"))
    _require_source_status(identifiability, Path("identifiability_ceiling_audit.json"))

    overall = profile.get("overall", {})
    by_venue = profile.get("by_venue", {})
    market_context = pre_action.get("market_context", {})
    assessment = pre_action.get("pre_action_trigger_assessment", {})
    venue_results = identifiability.get("venue_results", [])

    exact_trigger_available = bool(assessment.get("complete_pre_action_trigger_context_available"))
    if exact_trigger_available:
        raise ValueError("source audit unexpectedly claims complete pre-action trigger context")

    layers = [
        {
            "id": "inventory_state",
            "name": "目标库存 / 当前仓位状态",
            "classification": "OBSERVED_FACT",
            "confidence": "HIGH",
            "claim": "Non-idle behavior is strongly conditioned by current exposure and position state; the public record supports a stateful position-adjustment description.",
            "implementation_boundary": "Use the robot's own reconciled position and history only; never use the teacher's future or post-action state during autonomous replay.",
            "evidence": {
                "profile_non_idle_rate": overall.get("non_idle_rate"),
                "profile_by_venue": {
                    venue: {
                        "rows": data.get("rows"),
                        "non_idle_rate": data.get("non_idle_rate"),
                        "target_abs_mean": data.get("target_abs_mean"),
                    }
                    for venue, data in sorted(by_venue.items())
                    if isinstance(data, Mapping)
                },
                "profile_source": "strategy_behavior_profile_v4.json",
            },
        },
        {
            "id": "sparse_adjustment_actions",
            "name": "稀疏的开仓 / 加仓 / 减仓 / 平仓 / 反手调整",
            "classification": "OBSERVED_FACT",
            "confidence": "HIGH",
            "claim": "Most eligible clock rows are NO_TRADE; observed non-idle rows contain directional opens, adds, reductions, closes and flips.",
            "implementation_boundary": "A candidate must preserve an explicit NO_TRADE path and must not turn every indicator fluctuation into an order.",
            "evidence": {
                "eligible_rows": overall.get("rows"),
                "non_idle_rows": overall.get("non_idle_rows"),
                "non_idle_rate": overall.get("non_idle_rate"),
                "action_counts": overall.get("action_counts", {}),
            },
        },
        {
            "id": "passive_inventory_execution",
            "name": "被动挂单表达目标库存",
            "classification": "SUPPORTED_APPROXIMATION",
            "confidence": "MEDIUM",
            "claim": "Layered limit/GTC execution is a plausible implementation of the observed inventory-adjustment behavior, supported by an independent public analysis, but it is not proven to be the trader's private rule.",
            "implementation_boundary": "Use venue-native price, tick, lot, fee and post-only semantics; one net target per venue instrument and at most one active bot order.",
            "evidence": {
                "source_type": "independent_secondary_analysis",
                "source_claim": "planned inventory was associated with limit orders in the public execution record",
                "source_url": EXTERNAL_SOURCES[1]["url"],
                "not_proof_of_private_rule": True,
            },
        },
        {
            "id": "urgency_override",
            "name": "必要时的主动纠偏",
            "classification": "SUPPORTED_APPROXIMATION",
            "confidence": "MEDIUM",
            "claim": "Market/IOC-style execution can be used only as a bounded urgency override when passive execution cannot safely correct the target; this is an implementation hypothesis, not an identified trigger.",
            "implementation_boundary": "Require explicit urgency and risk checks, keep ReduceOnly for reductions, and fail closed when market context, account reconciliation or order state is stale.",
            "evidence": {
                "source_type": "independent_secondary_analysis",
                "source_claim": "urgent corrections were associated with active fills",
                "source_url": EXTERNAL_SOURCES[1]["url"],
                "not_proven_causal": True,
            },
        },
        {
            "id": "position_episode_risk",
            "name": "仓位周期与风险包络",
            "classification": "OBSERVED_FACT",
            "confidence": "HIGH",
            "claim": "The record is better described as position episodes with repeated adjustments than as isolated independent trades; holding duration and action interval are measurable, while the private risk limits are not.",
            "implementation_boundary": "Use observed historical distributions only as bounded risk references; do not infer unlimited leverage or assume past exposure is a safe future limit.",
            "evidence": {
                "holding_period_observed": profile.get("holding_period_observed", {}),
                "action_interval_observed": profile.get("action_interval_observed", {}),
                "external_source_url": EXTERNAL_SOURCES[1]["url"],
            },
        },
        {
            "id": "indicator_inputs",
            "name": "RSI / MACD / 布林带等指标",
            "classification": "SUPPORTED_APPROXIMATION",
            "confidence": "LOW",
            "claim": "Indicators are valid causal model inputs when computed from already-closed bars, but correlations and bucket lifts do not establish that the original trader used these indicators or that they caused an action.",
            "implementation_boundary": "Keep indicator features leakage-safe and explicitly label them as model-input evidence; missing funding, mark/index or microstructure context must remain missing.",
            "evidence": {
                "indicator_fields": [
                    "feature_rsi_14",
                    "feature_macd_histogram",
                    "feature_bollinger_percent_b_20",
                    "feature_volume_percentile_72bar",
                ],
                "closed_bar_strictly_before_decision": market_context.get("latest_closed_bar_strictly_before_decision"),
                "bar_equal_or_after_decision": market_context.get("latest_bar_equal_or_after_decision"),
                "interpretation": "association_only",
            },
        },
        {
            "id": "pre_action_timing",
            "name": "下单前精确触发时机",
            "classification": "UNIDENTIFIABLE",
            "confidence": "BLOCKED",
            "claim": "The current public export does not identify the exact pre-action trigger, quote state, order-book condition, cancellation intent or private decision rule.",
            "implementation_boundary": "Do not convert the conditional event benchmark into a deployable timing signal; any autonomous timing model remains research-only until independently observed pre-action context is available.",
            "evidence": {
                "complete_pre_action_trigger_context_available": exact_trigger_available,
                "independent_quote_orderbook_history_present": pre_action.get("independent_quote_orderbook_history_present"),
                "non_idle_decisions_matched": pre_action.get("submission_time_alignment", {}).get("non_idle_decisions_matched_to_order_episode"),
                "decision_time_equal_first_order_event": pre_action.get("submission_time_alignment", {}).get("decision_time_equal_first_order_event"),
                "conditional_vs_autonomous": [
                    {
                        "venue": result.get("venue"),
                        "conditional_action_macro_f1": (result.get("conditional_event_type") or {}).get("action_macro_f1"),
                        "autonomous_timing_f1": (result.get("strict_autonomous_timing_reference") or {}).get("f1"),
                    }
                    for result in venue_results
                    if isinstance(result, Mapping)
                ],
            },
        },
        {
            "id": "cross_venue_execution",
            "name": "跨交易所统一行为层 + 原生执行层",
            "classification": "SUPPORTED_APPROXIMATION",
            "confidence": "MEDIUM",
            "claim": "The same trader identity can support a shared high-level intent vocabulary, but executable behavior remains venue-native because contract scale, funding, liquidity, symbol coverage and order semantics differ.",
            "implementation_boundary": "Keep BitMEX and Hyperliquid evidence separated; share only venue-neutral intent features, then calibrate exposure and execution per venue.",
            "evidence": {
                "venues_in_profile": sorted(str(value) for value in by_venue),
                "same_trader_not_same_policy": True,
                "source_report": "venue_native_behavior_audit / shared_intent_native_layer_audit",
            },
        },
    ]

    generated = generated_at_utc or datetime.now(UTC).isoformat().replace("+00:00", "Z")
    payload = {
        "spec_version": SPEC_VERSION,
        "status": STATUS,
        "strategy_fidelity": FIDELITY,
        "generated_at_utc": generated,
        "purpose": "Evidence-bounded behavioral strategy contract; not a model artifact and not an order authorization.",
        "active_runtime": {
            "status": "UNCHANGED",
            "research_status": "RESEARCH_ONLY",
            "promotion_allowed": False,
            "new_demo_orders_authorized": False,
        },
        "data_scope": {
            "eligible_rows": overall.get("rows"),
            "non_idle_rows": overall.get("non_idle_rows"),
            "non_idle_rate": overall.get("non_idle_rate"),
            "venues": sorted(str(value) for value in by_venue),
            "teacher_data_type": "TRADE_RECORDS_ONLY",
        },
        "layers": layers,
        "operational_policy": {
            "mode": "RESEARCH_AND_BOUNDED_DEMO_ONLY",
            "signal_contract": ["action", "target_exposure", "confidence", "risk_tags", "valid_until"],
            "requires": [
                "causal_closed_bar_features",
                "venue_native_contract_and_unit_normalization",
                "reconciled_account_and_position_state",
                "fresh_market_and_private_streams",
                "risk_gates_and_single_active_order_guard",
                "strict_autonomous_walk_forward_validation",
            ],
            "forbids": [
                "teacher_future_state_in_autonomous_replay",
                "unbounded_exposure",
                "synthetic_market_data_substitution",
                "silent_missing_value_to_zero_forcing",
                "automatic_model_promotion",
            ],
        },
        "prohibited_claims": [
            "The robot has exactly recovered the original trader's private strategy.",
            "The trader definitely used RSI, MACD, Bollinger Bands or any other named indicator.",
            "Historical replay results guarantee future profitability.",
            "BitMEX and Hyperliquid are executable-policy interchangeable.",
            "The specification itself authorizes live or mainnet orders.",
        ],
        "sources": [*source_records, *EXTERNAL_SOURCES],
        "conclusion": "The strongest defensible result is a sparse, stateful inventory-adjustment approximation with venue-native execution. Action type and sizing are partly observable once an event is known, but exact autonomous timing and the trader's private trigger remain unidentifiable from the current public record.",
        "raw_inputs_untouched": True,
    }
    return payload


def render_markdown(payload: Mapping[str, Any]) -> str:
    lines = [
        "# Behavioral Strategy Specification V1",
        "",
        "> `BEHAVIORAL_APPROXIMATION` / `APPROXIMATION_ONLY`. This document is an evidence contract, not a trained model, profitability claim, or order authorization.",
        "",
        "## Plain-language conclusion",
        "",
        "当前最可靠的提炼不是“某一个指标发出买卖信号”，而是一个**有状态的目标仓位调整过程**：大多数时间观望，进入非空仓位后反复小步加仓、减仓、平仓或反手；执行层可用被动挂单作为近似，必要时才做受限主动纠偏。",
        "",
        "这仍然不是原交易员私有策略的精确恢复。成交前的精确触发条件、当时盘口、撤单意图和主观判断，在当前公开导出中不可识别。RSI、MACD、布林带等只属于模型输入候选，不是原交易员真实使用它们的证据。",
        "",
        "## Evidence layers",
        "",
        "| layer | classification | confidence | safe interpretation |",
        "|---|---|---|---|",
    ]
    for layer in payload.get("layers", []):
        claim = str(layer.get("claim", "")).replace("|", "\\|")
        lines.append(f"| `{layer.get('id')}` | `{layer.get('classification')}` | `{layer.get('confidence')}` | {claim} |")
    lines += [
        "",
        "## What the robot may implement",
        "",
        "1. 只在自己的已对账仓位状态上计算目标暴露。",
        "2. 保留显式观望路径，不把每次指标波动都转成订单。",
        "3. 跨交易所共享高层动作词汇，但按交易所分别处理合约乘数、币种、资金费、盘口和执行语义。",
        "4. 被动挂单、单合约单活动订单、ReduceOnly 反手先减仓、过期/失联/对账失败时拒绝下单。",
        "5. 只有严格自主时间外回放通过门槛，才允许候选模型进入 Demo 观察。",
        "",
        "## What remains blocked",
        "",
        "- 精确知道“为什么在这一秒下单”。",
        "- 证明指标就是原交易员当时使用的指标。",
        "- 从公开成交记录恢复未公开的盘口、撤单前意图或主观风险限额。",
        "- 把条件式动作分类分数当成自主信号。",
        "- 宣称盈利或允许主网/实盘自动切换。",
        "",
        "## Audit facts",
        "",
        f"- Eligible rows: `{payload.get('data_scope', {}).get('eligible_rows')}`; non-idle rows: `{payload.get('data_scope', {}).get('non_idle_rows')}`; non-idle rate: `{float(payload.get('data_scope', {}).get('non_idle_rate') or 0):.2%}`.",
        f"- Venues retained separately: `{', '.join(payload.get('data_scope', {}).get('venues', []))}`.",
        "- The current active runtime/model is unchanged; no new Demo orders are authorized by this specification.",
        "",
        "## Sources",
        "",
    ]
    for source in payload.get("sources", []):
        if "url" in source:
            lines.append(f"- [{source.get('name')}]({source.get('url')}) — {source.get('role')}. Limitation: {source.get('limitations')}")
        else:
            lines.append(f"- `{source.get('path')}` — `{source.get('report_version')}`; SHA256 `{source.get('sha256')}`.")
    lines += [
        "",
        "## Boundary",
        "",
        "No credentials, private endpoint, mainnet connection or order was used. Root raw CSV/JSON inputs remain read-only.",
    ]
    return "\n".join(lines) + "\n"


def build(
    *,
    profile_path: Path = PROFILE,
    pre_action_path: Path = PRE_ACTION,
    identifiability_path: Path = IDENTIFIABILITY,
    report_path: Path = OUTPUT,
    markdown_path: Path = OUTPUT_MD,
) -> dict[str, Any]:
    profile = _read_json(profile_path)
    pre_action = _read_json(pre_action_path)
    identifiability = _read_json(identifiability_path)
    sources = [
        _source_record(profile_path, profile),
        _source_record(pre_action_path, pre_action),
        _source_record(identifiability_path, identifiability),
    ]
    payload = build_payload(
        profile=profile,
        pre_action=pre_action,
        identifiability=identifiability,
        source_records=sources,
    )
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
        print(json.dumps({"status": "BLOCKED", "error_code": "BEHAVIORAL_SPEC_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({
        "status": payload["status"],
        "spec_version": payload["spec_version"],
        "report": str(args.report.resolve()),
        "markdown": str(args.markdown.resolve()),
        "promotion_allowed": payload["active_runtime"]["promotion_allowed"],
        "layers": len(payload["layers"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
