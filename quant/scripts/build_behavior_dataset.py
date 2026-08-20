#!/usr/bin/env python3
"""Build BTC-first behavioral actions, order episodes, decisions, and cycles."""

from __future__ import annotations

import csv
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from behavior import (  # noqa: E402
    build_decision_episodes,
    build_execution_batches,
    build_order_episodes,
    build_trade_actions,
    build_trade_cycles,
)
from bitmex_replay.execution_normalizer import (  # noqa: E402
    assert_unique_exec_ids,
    load_instruments,
    load_settlement_evidence,
    normalize_executions,
)
from bitmex_replay.execution_order_audit import (  # noqa: E402
    apply_execution_order_policy,
    audit_execution_order,
)
from bitmex_replay.execution_price_reconciler import reconcile_execution_prices  # noqa: E402
from bitmex_replay.execution_valuation import (  # noqa: E402
    build_execution_valuation,
    load_asset_scale_registry,
)
from bitmex_replay.historical_spec_registry import (  # noqa: E402
    load_historical_specs,
    resolve_specs_for_events,
)
from bitmex_replay.io_utils import hash_files, iter_csv_dicts, parse_datetime  # noqa: E402
from bitmex_replay.order_dimension import build_order_dimension  # noqa: E402
from bitmex_replay.position_accounting import (  # noqa: E402
    build_position_accounting,
    load_accounting_policy,
)
from bitmex_replay.position_replayer import replay_positions  # noqa: E402
from bitmex_replay.reconciliation import write_csv, write_parquet  # noqa: E402


PROTECTED_FILES = [
    "api-v1-execution-tradeHistory.csv",
    "api-v1-order.csv",
    "api-v1-user-walletHistory.csv",
    "api-v1-position.snapshot.csv",
    "api-v1-user-wallet.snapshot-all.csv",
    "api-v1-user-margin.snapshot-all.csv",
    "api-v1-instrument.all.csv",
    "api-v1-wallet-assets.csv",
    "derived-equity-curve.csv",
    "manifest.json",
]


def git_value(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def source_commit() -> str:
    path = ROOT / "quant" / "SOURCE_VERSION.md"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("- source commit:"):
            return line.split(":", 1)[1].strip().strip("`")
    return ""


def jsonable(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    if isinstance(value, set):
        return sorted(jsonable(item) for item in value)
    return value


def _fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                names.append(key)
    return names or ["empty"]


def write_large_output(rows: list[dict[str, Any]], parquet_path: Path) -> dict[str, Any]:
    """Write Parquet when the pinned dependency exists; otherwise audibly fall back to CSV."""

    try:
        write_parquet(rows, parquet_path)
        return {"format": "parquet", "path": str(parquet_path.relative_to(ROOT)), "row_count": len(rows)}
    except (ImportError, RuntimeError):
        fallback = parquet_path.with_suffix(".csv")
        write_csv(rows, fallback, _fieldnames(rows))
        return {
            "format": "csv_fallback_no_parquet_engine",
            "path": str(fallback.relative_to(ROOT)),
            "requested_path": str(parquet_path.relative_to(ROOT)),
            "row_count": len(rows),
        }


def _wallet_summary() -> dict[str, Any]:
    path = ROOT / "quant" / "reports" / "wallet_reconciliation.json"
    if not path.is_file():
        return {"status": "MISSING"}
    return json.loads(path.read_text(encoding="utf-8"))


def _confidence_report(datasets: dict[str, list[dict[str, Any]]]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    fields = ["ordering_confidence", "action_confidence", "accounting_confidence", "price_confidence", "wallet_confidence", "overall_confidence"]
    for dataset, values in datasets.items():
        for field in fields:
            counts = Counter(str(row.get(field, "")) for row in values)
            for status, count in sorted(counts.items()):
                rows.append({"dataset": dataset, "confidence_field": field, "status": status, "row_count": count})
    return rows


def _transition_report(decisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    previous = "START"
    for row in decisions:
        action = str(row.get("action", ""))
        counts[(previous, action)] += 1
        previous = action
    return [{"previous_action": previous_action, "next_action": next_action, "count": count} for (previous_action, next_action), count in sorted(counts.items())]


def _style_report(order_episodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in order_episodes:
        count = int(row.get("execution_count") or 0)
        bucket = "SINGLE_FILL" if count == 1 else ("2_TO_5_FILLS" if count <= 5 else "6_PLUS_FILLS")
        groups[(str(row.get("symbol", "")), str(row.get("ordType", "")), str(row.get("side", "")), bucket)].append(row)
    result: list[dict[str, Any]] = []
    for (symbol, ord_type, side, bucket), values in sorted(groups.items()):
        result.append({
            "symbol": symbol,
            "ordType": ord_type,
            "side": side,
            "execution_count_bucket": bucket,
            "order_episode_count": len(values),
            "filled_qty_sum": sum(int(row.get("filled_qty") or 0) for row in values),
            "partial_or_multi_fill_count": sum(int(row.get("execution_count") or 0) > 1 for row in values),
            "ambiguous_order_count": sum(row.get("execution_order_chain_status") == "AMBIGUOUS" for row in values),
        })
    return result


def _run_pipeline() -> dict[str, Any]:
    order_dimension = build_order_dimension(ROOT / "api-v1-order.csv")
    instruments = load_instruments(ROOT / "api-v1-instrument.all.csv")
    evidence = load_settlement_evidence(ROOT / "quant" / "config" / "historical_settlement_evidence.json")
    normalized = normalize_executions(ROOT / "api-v1-execution-tradeHistory.csv", order_dimension, instruments, evidence)
    assert_unique_exec_ids(normalized)
    order_audit = audit_execution_order(normalized["events"])
    events = apply_execution_order_policy(normalized["events"], order_audit, "SOURCE_ROW_STABLE")
    replay = replay_positions(events)

    registry = load_historical_specs(
        ROOT / "quant" / "config" / "historical_instrument_specs.json",
        ROOT / "api-v1-instrument.all.csv",
        source_commit(),
    )
    mapping = resolve_specs_for_events(events, registry)
    price = reconcile_execution_prices(events, registry, mapping)
    assets = load_asset_scale_registry(ROOT / "api-v1-wallet-assets.csv")
    valuation = build_execution_valuation(events, registry, mapping, assets, price_reconciliation=price)
    order_status_by_exec = order_audit.get("chain_status_by_exec", {})
    order_rank_by_exec = order_audit.get("rank_by_exec", {})
    for row in valuation["valuations"]:
        exec_id = str(row.get("execID", ""))
        row["execution_order_policy"] = "SOURCE_ROW_STABLE"
        row["execution_order_chain_status"] = order_status_by_exec.get(exec_id, "NOT_IN_MULTI_TRADE_GROUP")
        row["execution_order_rank"] = order_rank_by_exec.get(exec_id, 0)
    policy = load_accounting_policy(ROOT / "quant" / "config" / "position_accounting_policy.json")
    specs = {str(spec.get("spec_id")): spec for spec in registry.get("specs", [])}
    accounting = build_position_accounting(valuation["valuations"], replay["position_events"], specs, policy)
    valuation_by_exec = {str(row.get("execID", "")): row for row in valuation["valuations"]}
    accounting_by_exec = {str(row.get("execID", "")): row for row in accounting.get("events", [])}
    trade_actions = build_trade_actions(events, valuation_by_exec, accounting_by_exec, order_status_by_exec)
    batches, exec_to_batch = build_execution_batches(
        events,
        order_status_by_exec,
        max_gap_seconds=300,
    )
    for row in trade_actions:
        row["execution_batch_id"] = exec_to_batch.get(str(row.get("execID", "")), "")
    order_episodes = build_order_episodes(
        events,
        order_dimension,
        valuation_by_exec,
        accounting_by_exec,
        order_status_by_exec,
    )
    batch_counts = Counter(str(row.get("order_episode_key", "")) for row in batches)
    for row in order_episodes:
        key = str(row.get("orderID", "")) or f"UNMATCHED:{row.get('execution_ids', '').split(',')[0]}"
        row["execution_batch_count"] = batch_counts.get(key, 0)
    decisions = build_decision_episodes(order_episodes, replay["position_events"], btc_symbol="XBTUSD")
    cycles = build_trade_cycles(events, valuation_by_exec, accounting_by_exec, order_status_by_exec)
    return {
        "normalized": normalized,
        "order_audit": order_audit,
        "replay": replay,
        "valuation": valuation,
        "accounting": accounting,
        "trade_actions": trade_actions,
        "batches": batches,
        "order_episodes": order_episodes,
        "decisions": decisions,
        "cycles": cycles,
        "price": price,
    }


def _write_profile(reports: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Trader Behavior Profile",
        "",
        f"- status: **{summary['behavior_dataset_status']}**",
        f"- analysis commit: `{summary['analysis_commit']}`",
        f"- source commit: `{summary['source_commit']}`",
        f"- teacher data: `{summary['teacher_data_type']}`",
        f"- strategy fidelity: `{summary['strategy_fidelity']}`",
        "",
        "## Layered dataset",
        "",
        "Raw fills are not treated as independent decisions. The dataset keeps a visible chain from fills to order episodes, execution batches, position actions, decision episodes, and zero-to-zero position cycles.",
        "",
        "| layer | rows |",
        "| --- | ---: |",
    ]
    for key, value in summary["counts"].items():
        lines.append(f"| {key} | {value} |")
    lines.extend([
        "",
        "## BTC-first boundary",
        "",
        f"- XBTUSD trade actions: `{summary['btc_first_counts']['trade_actions']}`; order episodes: `{summary['btc_first_counts']['order_episodes']}`; decisions: `{summary['btc_first_counts']['decisions']}`; cycles: `{summary['btc_first_counts']['cycles']}`.",
        "- Altcoin and non-XBTUSD derivative behavior remains in the layered outputs for generalization diagnostics; it does not redefine the BTC teacher scope.",
        "- Daily synthetic observations provide `HOLD_LONG`, `HOLD_SHORT`, and `NO_TRADE` samples only for XBTUSD and are marked synthetic.",
        "",
        "## Confidence and accounting boundary",
        "",
        "Every action, decision, and cycle carries ordering, action, accounting, price, wallet, and overall confidence. Wallet confidence is aggregate-only because wallet history cannot prove a universal row-level execution join. Exchange internal currentCost and AEP are not used as exact teacher labels.",
        "",
        f"- wallet reconciliation status: `{summary['wallet_status']}`",
        f"- downstream accounting status: `{summary['accounting_status']}`",
        f"- accounting engine audit status: `{summary['accounting_engine_status']}` (residual policy audit is retained, not silently repaired)",
        f"- execution-order audit: `{summary['execution_order_status']}`",
        f"- raw inputs unchanged: **{summary['raw_inputs_unchanged']}**",
        "",
        "## Output format",
        "",
    ])
    for name, output in summary["large_outputs"].items():
        lines.append(f"- `{name}`: `{output['format']}` at `{output['path']}` (`{output['row_count']}` rows).")
    lines.extend([
        "",
        "The requested Parquet outputs are ignored by Git. If the local runtime lacks the pinned Parquet engine, the script writes a clearly labeled ignored CSV fallback and keeps the same schema; installing `quant/requirements.txt` restores Parquet output.",
        "",
        "## Next action",
        "",
        "Acquire and freeze public BTC canonical market context before constructing leakage-safe features and labels.",
    ])
    (reports / "trader_behavior_profile.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(root: Path = ROOT) -> dict[str, Any]:
    root = Path(root)
    reports = root / "quant" / "reports"
    outputs = root / "quant" / "outputs"
    reports.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    before = hash_files(root, PROTECTED_FILES)
    data = _run_pipeline()
    after = hash_files(root, PROTECTED_FILES)
    changed = [name for name in PROTECTED_FILES if before.get(name) != after.get(name)]
    wallet = _wallet_summary()
    trade_actions = data["trade_actions"]
    batches = data["batches"]
    order_episodes = data["order_episodes"]
    decisions = data["decisions"]
    cycles = data["cycles"]
    xbt_actions = [row for row in trade_actions if row.get("symbol") == "XBTUSD"]
    xbt_orders = [row for row in order_episodes if row.get("symbol") == "XBTUSD"]
    xbt_decisions = [row for row in decisions if row.get("symbol") == "XBTUSD"]
    xbt_cycles = [row for row in cycles if row.get("symbol") == "XBTUSD"]
    large_outputs = {
        "trade_actions": write_large_output(trade_actions, outputs / "trade_actions.parquet"),
        "order_episodes": write_large_output(order_episodes, outputs / "order_episodes.parquet"),
        "decision_episodes": write_large_output(decisions, outputs / "decision_episodes.parquet"),
        "trade_cycles": write_large_output(cycles, outputs / "trade_cycles.parquet"),
    }
    confidence_rows = _confidence_report({
        "trade_actions": trade_actions,
        "order_episodes": order_episodes,
        "decision_episodes": decisions,
        "trade_cycles": cycles,
    })
    transition_rows = _transition_report(decisions)
    style_rows = _style_report(order_episodes)
    write_csv(cycles, reports / "trade_cycle_summary.csv", _fieldnames(cycles))
    write_csv(transition_rows, reports / "action_transition_matrix.csv", ["previous_action", "next_action", "count"])
    write_csv(confidence_rows, reports / "behavior_confidence_summary.csv", ["dataset", "confidence_field", "status", "row_count"])
    write_csv(style_rows, reports / "order_execution_style.csv", _fieldnames(style_rows))
    analysis = git_value(["rev-parse", "HEAD"])
    account_summary = data["accounting"].get("summary", {})
    accounting_engine_status = data["accounting"].get("status", "MISSING")
    downstream_accounting_status = "READY_WITH_KNOWN_ACCOUNTING_RESIDUALS" if data["accounting"].get("events") else "BLOCKED"
    summary: dict[str, Any] = {
        "report_version": "M2-BEHAVIOR-1.0",
        "source_commit": source_commit(),
        "analysis_commit": analysis,
        "analysis_branch": git_value(["branch", "--show-current"]),
        "teacher_data_type": "TRADE_RECORDS_ONLY",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "behavior_dataset_status": "READY_WITH_WARNINGS",
        "wallet_status": wallet.get("wallet_reconciliation_status", "MISSING"),
        "accounting_status": downstream_accounting_status,
        "accounting_engine_status": accounting_engine_status,
        "execution_order_status": data["order_audit"].get("status", "MISSING"),
        "raw_inputs_unchanged": not changed,
        "changed_protected_files": changed,
        "counts": {
            "raw_execution_rows": data["normalized"]["raw_rows"],
            "derivative_trade_fills": sum(row.get("execType") == "Trade" and row.get("instrument_class") == "DERIVATIVE" for row in data["normalized"]["events"]),
            "execution_batches": len(batches),
            "order_episodes": len(order_episodes),
            "decision_episodes": len(decisions),
            "trade_cycles": len(cycles),
        },
        "btc_first_counts": {
            "trade_actions": len(xbt_actions),
            "order_episodes": len(xbt_orders),
            "decisions": len(xbt_decisions),
            "cycles": len(xbt_cycles),
            "synthetic_decisions": sum(row.get("synthetic_negative_sample") for row in xbt_decisions),
        },
        "action_counts": dict(Counter(str(row.get("action", "")) for row in decisions)),
        "cycle_close_type_counts": dict(Counter(str(row.get("close_type", "")) for row in cycles)),
        "execution_order_audit": {key: value for key, value in data["order_audit"].items() if key not in {"rows", "chain_status_by_exec", "rank_by_exec"}},
        "accounting_summary": {
            "position_accounting_engine_status": accounting_engine_status,
            "downstream_accounting_status": downstream_accounting_status,
            "accounting_event_rows": len(data["accounting"].get("events", [])),
            "gross_realised_pnl_available": bool(account_summary),
        },
        "wallet_reconciliation_evidence": {
            "status": wallet.get("wallet_reconciliation_status", "MISSING"),
            "row_count": wallet.get("wallet_row_count", 0),
            "snapshot_pass_count": wallet.get("snapshot_pass_count", 0),
            "snapshot_zero_without_history_count": wallet.get("snapshot_zero_without_history_count", 0),
            "snapshot_unresolved_count": wallet.get("snapshot_unresolved_count", 0),
        },
        "large_outputs": large_outputs,
        "next_action": "Acquire and freeze public BTC canonical market context before leakage-safe feature and label construction.",
    }
    summary["large_outputs"] = large_outputs
    (reports / "behavior_dataset.json").write_text(json.dumps(jsonable(summary), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _write_profile(reports, summary)
    return summary


if __name__ == "__main__":
    result = run()
    print(f"behavior_dataset_status={result['behavior_dataset_status']}")
    print(f"counts={result['counts']}")
    print(f"btc_first_counts={result['btc_first_counts']}")
    print(f"action_counts={result['action_counts']}")
    print(f"cycle_close_type_counts={result['cycle_close_type_counts']}")
    print(f"raw_inputs_unchanged={result['raw_inputs_unchanged']}")
