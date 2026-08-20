#!/usr/bin/env python3
"""M0-02B-1B-0: replay derivative position cost, AEP, cycles, and gross PnL."""

from __future__ import annotations

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

from bitmex_replay.execution_normalizer import (  # noqa: E402
    assert_unique_exec_ids,
    load_instruments,
    load_settlement_evidence,
    normalize_executions,
)
from bitmex_replay.execution_price_reconciler import reconcile_execution_prices  # noqa: E402
from bitmex_replay.execution_valuation import load_asset_scale_registry, build_execution_valuation  # noqa: E402
from bitmex_replay.historical_spec_registry import load_historical_specs, resolve_specs_for_events  # noqa: E402
from bitmex_replay.io_utils import hash_files, iter_csv_dicts, parse_datetime  # noqa: E402
from bitmex_replay.order_dimension import build_order_dimension  # noqa: E402
from bitmex_replay.position_accounting import (  # noqa: E402
    ACCOUNTING_BLOCKED,
    BLOCKED,
    PASS,
    PositionAccountingError,
    build_position_accounting,
    load_accounting_policy,
    reconcile_terminal_snapshot,
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
EXPECTED_RAW = 173434
EXPECTED_DERIVATIVE = 173226
EXPECTED_TRADE = 160302
EXPECTED_FUNDING = 12905
EXPECTED_SETTLEMENT = 19
EXPECTED_SPOT = 208
SNAPSHOT_SYMBOL = "XBTUSD"
SNAPSHOT_CURRENT_COST = Decimal("1386445811")


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
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def _decimal(value: Any) -> Decimal | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        number = Decimal(str(value).strip())
    except Exception:
        return None
    return number if number.is_finite() else None


def _sum_decimal(rows: list[dict[str, Any]], field: str) -> str:
    total = Decimal(0)
    for row in rows:
        value = _decimal(row.get(field))
        if value is not None:
            total += value
    return format(total, "f")


def _table(headers: list[str], rows: list[list[Any]]) -> str:
    def cell(value: Any) -> str:
        return str("" if value is None else value).replace("|", "\\|").replace("\n", " ")

    return "\n".join([
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *["| " + " | ".join(cell(value) for value in row) + " |" for row in rows],
    ])


def read_snapshot(path: Path) -> dict[str, dict[str, str]]:
    rows = list(iter_csv_dicts(path))
    if not rows:
        return {}
    target = parse_datetime(rows[0][1].get("timestamp", ""))
    selected: dict[str, dict[str, str]] = {}
    for _, row in rows:
        event_time = parse_datetime(row.get("timestamp", ""))
        if target is None or event_time is None or event_time <= target:
            selected[row.get("symbol", "")] = row
    return selected


def build_report_tables(events: list[dict[str, Any]], terminal: list[dict[str, Any]], policy_rows: list[dict[str, Any]], anomalies: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    action_counts = Counter(str(row.get("action", "")) for row in events)
    action_summary = [
        {"action": action, "event_count": count, "flip": action.startswith("FLIP_")}
        for action, count in sorted(action_counts.items())
    ]
    terminal_rows = [
        {
            "symbol": row.get("symbol"),
            "payout_model": row.get("payout_model"),
            "settlement_currency": row.get("settlement_currency"),
            "position_qty": row.get("position_qty"),
            "current_cost_exact_raw": row.get("current_cost_exact_raw"),
            "current_cost_api_raw": row.get("current_cost_api_raw"),
            "average_entry_basis": row.get("average_entry_basis"),
            "average_entry_price": row.get("average_entry_price"),
            "position_cycle_id": row.get("position_cycle_id"),
            "cycle_count": row.get("cycle_count"),
        }
        for row in terminal
    ]
    reported = [
        row for row in events
        if row.get("reported_realisedPnl_raw") not in (None, "")
        and str(row.get("reported_realisedPnl_raw")).strip()
    ]
    diagnostics: list[dict[str, Any]] = []
    for dimension in ("execType", "payout_model", "symbol", "action"):
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for row in events:
            key = str(row.get(dimension, ""))
            grouped[key].append(row)
        for key, group in sorted(grouped.items()):
            non_null = [
                row for row in group
                if row.get("reported_realisedPnl_raw") not in (None, "")
                and str(row.get("reported_realisedPnl_raw")).strip()
            ]
            exact = sum(row.get("reported_pnl_difference_raw") == "0" for row in non_null)
            diagnostics.append({
                "group_by": dimension,
                "group_value": key,
                "execution_count": len(group),
                "reported_non_null_count": len(non_null),
                "reported_missing_count": len(group) - len(non_null),
                "reported_exact_match_count": exact,
                "reported_mismatch_count": len(non_null) - exact,
                "difference_raw_sum": _sum_decimal(non_null, "reported_pnl_difference_raw"),
                "max_abs_difference_raw": format(max((_decimal(row.get("reported_pnl_difference_raw")) or Decimal(0)).copy_abs() for row in non_null), "f") if non_null else "0",
            })
    difference_distribution = Counter(str(row.get("reported_pnl_difference_raw")) for row in reported)
    diagnostics.append({
        "group_by": "difference_distribution",
        "group_value": "ALL",
        "execution_count": len(events),
        "reported_non_null_count": len(reported),
        "reported_missing_count": len(events) - len(reported),
        "reported_exact_match_count": sum(row.get("reported_pnl_difference_raw") == "0" for row in reported),
        "reported_mismatch_count": sum(row.get("reported_pnl_difference_raw") != "0" for row in reported),
        "difference_raw_sum": _sum_decimal(reported, "reported_pnl_difference_raw"),
        "max_abs_difference_raw": format(max((_decimal(row.get("reported_pnl_difference_raw")) or Decimal(0)).copy_abs() for row in reported), "f") if reported else "0",
        "difference_frequency": json.dumps(dict(difference_distribution), ensure_ascii=False, sort_keys=True),
    })
    return {
        "terminal": terminal_rows,
        "action_summary": action_summary,
        "policy": policy_rows,
        "reported": diagnostics,
        "anomalies": anomalies[:200],
    }


def write_reports(
    reports: Path,
    tables: dict[str, list[dict[str, Any]]],
    summary: dict[str, Any],
    protected: dict[str, Any],
    source: str,
    analysis: str,
    branch: str,
) -> None:
    reports.mkdir(parents=True, exist_ok=True)
    write_csv(tables["terminal"], reports.parent / "outputs" / "terminal_position_accounting.csv", [
        "symbol", "payout_model", "settlement_currency", "position_qty", "current_cost_exact_raw", "current_cost_api_raw",
        "average_entry_basis", "average_entry_price", "position_cycle_id", "cycle_count",
    ])
    write_csv(tables["terminal"], reports / "position_accounting_by_symbol.csv", [
        "symbol", "payout_model", "settlement_currency", "position_qty", "current_cost_exact_raw", "current_cost_api_raw",
        "average_entry_basis", "average_entry_price", "position_cycle_id", "cycle_count",
    ])
    write_csv(tables["action_summary"], reports / "position_action_summary.csv", ["action", "event_count", "flip"])
    write_csv(tables["policy"], reports / "cost_rounding_policy_audit.csv", [
        "operation", "payout_model", "settlement_currency", "candidate_policy", "evaluated_event_count",
        "conservation_failure_count", "flat_cost_failure_count", "settlement_cost_failure_count",
        "xbtusd_terminal_current_cost", "xbtusd_current_cost_difference", "reported_pnl_exact_match_count",
        "reported_pnl_mismatch_count", "status", "selection_reason",
    ])
    write_csv(tables.get("snapshot", []), reports / "xbtusd_snapshot_reconciliation.csv", list(tables.get("snapshot", [{}])[0].keys()) if tables.get("snapshot") else ["symbol", "reconciliation_status"])
    write_csv(tables["reported"], reports / "reported_realised_pnl_diagnostics.csv", [
        "group_by", "group_value", "execution_count", "reported_non_null_count", "reported_missing_count",
        "reported_exact_match_count", "reported_mismatch_count", "difference_raw_sum", "max_abs_difference_raw", "difference_frequency",
    ])
    write_csv(tables["anomalies"], reports / "position_accounting_anomalies.csv", ["execID", "event_time", "symbol", "execType", "anomaly_type", "reason"])

    compact = {
        "report_version": "M0-02B-1B-0/1.0",
        "source_commit": source,
        "analysis_commit": analysis,
        "analysis_branch": branch,
        "position_accounting_status": summary["position_accounting_status"],
        "m0_02b1b1_readiness": summary["m0_02b1b1_readiness"],
        "blockers": summary["blockers"],
        "warnings": summary["warnings"],
        "input_counts": summary["input_counts"],
        "accounting_eligibility_counts": summary["accounting_eligibility_counts"],
        "action_counts": summary["action_counts"],
        "flip_count": summary["flip_count"],
        "full_close_count": summary["full_close_count"],
        "position_cycle_count": summary["position_cycle_count"],
        "conservation": summary["conservation"],
        "rounding_policy": summary["rounding_policy"],
        "terminal_checks": summary["terminal_checks"],
        "reported_realised_pnl": summary["reported_realised_pnl"],
        "gross_realised_pnl_by_currency": summary["gross_realised_pnl_by_currency"],
        "protected_files": protected,
        "output_rows": {"position_accounting_events": summary["output_rows"]},
    }
    (reports / "position_accounting.json").write_text(json.dumps(jsonable(compact), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    terminal = tables["terminal"]
    nonzero = [row for row in terminal if int(row.get("position_qty") or 0) != 0]
    snapshot_rows = tables.get("snapshot", [])
    lines = [
        "# M0-02B-1B-0 仓位成本与平均入场价回放",
        "",
        "> 本阶段只重放衍生品仓位数量、成本、平均入场价、仓位周期和毛已实现交易 PnL；不对 Wallet History 做最终对账，不计算净现金流、未实现 PnL、净值、杠杆或保证金。",
        "",
        "## 执行摘要",
        "",
        f"- `position_accounting_status`: **{summary['position_accounting_status']}**",
        f"- `m0_02b1b1_readiness`: **{summary['m0_02b1b1_readiness']}**",
        f"- source commit: `{source}`",
        f"- analysis commit: `{analysis}`",
        f"- branch: `{branch}`",
        f"- 处理行数: `{summary['output_rows']}`；Spot 进入 accounting: `{summary['input_counts']['spot_accounting_rows']}`。",
        "",
        "## Accounting eligibility",
        "",
        _table(["status", "count", "meaning"], [[key, value, "eligible" if key != ACCOUNTING_BLOCKED else "blocking"] for key, value in sorted(summary["accounting_eligibility_counts"].items())]),
        "",
        "`PASS` 和 `WARNING` 均被处理；只有 `BLOCKED` 才会阻塞本阶段。费用诊断 warning 不会把真实 Trade 排除。",
        "",
        "## 覆盖与动作",
        "",
        _table(["execType", "count"], [[key, value] for key, value in sorted(summary["input_counts"]["exec_type_counts"].items())]),
        "",
        _table(["action", "count"], [[key, value] for key, value in sorted(summary["action_counts"].items())]),
        "",
        f"- flip count: `{summary['flip_count']}`; full close count: `{summary['full_close_count']}`; position cycle count: `{summary['position_cycle_count']}`。",
        "",
        "## Cost conservation",
        "",
        _table(["check", "failure count"], [
            ["exact currentCost identity", summary["conservation"]["exact_conservation_failure_count"]],
            ["API raw currentCost identity", summary["conservation"]["api_conservation_failure_count"]],
            ["flip execCost split", summary["conservation"]["flip_exec_cost_split_failure_count"]],
            ["full-close residual cost", summary["conservation"]["full_close_residual_cost_count"]],
            ["Settlement residual cost", summary["conservation"]["settlement_residual_cost_count"]],
            ["flat terminal residual cost", summary["terminal_checks"]["flat_terminal_residual_cost_count"]],
        ]),
        "",
        "`execCost_raw` remains signed and authoritative. The exact layer may contain rational values during partial release or flip splitting; the API layer is an integer projection under one fixed policy, and the two legs always sum to the original raw cost.",
        "",
        "## Rounding policy audit",
        "",
        f"- selected average-cost release: `{summary['rounding_policy']['selected_average_cost_release']}`",
        f"- selected flip execCost split: `{summary['rounding_policy']['selected_flip_exec_cost_split']}`",
        f"- ambiguity count: `{summary['rounding_policy']['ambiguity_count']}`",
        f"- selection reason: {summary['rounding_policy']['selection_reason']}",
        "",
        "详表见 `cost_rounding_policy_audit.csv`。没有 execID 或 symbol 级 override，也没有逐行择优舍入。",
        "",
        "## Average entry price",
        "",
        "AEP 独立于 currentCost。Quanto/Linear 使用 Decimal 数量加权；Inverse 使用规格 lot_size / canonical price 的聪值 basis，长仓 ROUND_FLOOR 到 8 位，空头按配置的 ROUND_HALF_UP 到 8 位。不得使用 avgPx，也不得用 currentCost / currentQty 反推 AEP。",
        "",
        "## Settlement 与周期",
        "",
        f"- Settlement rows: `{summary['input_counts']['settlement_count']}`; applied close rows: `{summary['terminal_checks']['settlement_applied_count']}`。",
        f"- 非零终态 symbol: `{summary['terminal_checks']['nonzero_terminal_symbols']}`。",
        "- Funding 不改变 quantity、currentCost、AEP、cycle 或 gross trading PnL；Settlement 必须完整关闭并清零成本/AEP。",
        "",
        "## 每个 symbol 的终态",
        "",
        _table(["symbol", "qty", "currentCost API", "AEP", "cycle count"], [[row.get("symbol"), row.get("position_qty"), row.get("current_cost_api_raw"), row.get("average_entry_price"), row.get("cycle_count")] for row in terminal if int(row.get("position_qty") or 0) != 0] or [["无", 0, 0, None, 0]]),
        "",
        "## XBTUSD snapshot reconciliation",
        "",
        _table(["field", "reconstructed", "snapshot", "status"], [[
            "currentQty", row.get("reconstructed_currentQty"), row.get("snapshot_currentQty"), row.get("quantity_status")
        ] for row in snapshot_rows] + [[
            "currentCost", row.get("reconstructed_currentCost"), row.get("snapshot_currentCost"), row.get("current_cost_status")
        ] for row in snapshot_rows] + [[
            "posCost", row.get("reconstructed_posCost"), row.get("snapshot_posCost"), row.get("pos_cost_status")
        ] for row in snapshot_rows] + [[
            "avgEntryPrice displayed", row.get("reconstructed_aep_display"), row.get("snapshot_avgEntryPrice"), row.get("avg_entry_price_status")
        ] for row in snapshot_rows] + [[
            "avgCostPrice displayed", row.get("reconstructed_aep_display"), row.get("snapshot_avgCostPrice"), row.get("avg_cost_price_status")
        ] for row in snapshot_rows]),
        "",
        "Snapshot AEP comparison uses only the declared `Decimal('0.0001')` / ROUND_HALF_UP display quantization; no tolerance is used.",
        "",
        "## reported realisedPnl diagnostics",
        "",
        f"- non-null: `{summary['reported_realised_pnl']['non_null']}`; exact: `{summary['reported_realised_pnl']['exact']}`; mismatch: `{summary['reported_realised_pnl']['mismatch']}`; missing: `{summary['reported_realised_pnl']['missing']}`。",
        f"- maximum absolute difference raw: `{summary['reported_realised_pnl']['max_abs_difference_raw']}`。",
        "- reported realisedPnl never updates state and is not automatically combined with execComm or Funding. 詳細分布见 `reported_realised_pnl_diagnostics.csv`。",
        "",
        "## Gross realised PnL",
        "",
        _table(["currency", "gross realised PnL exact raw"], [[key, value] for key, value in sorted(summary["gross_realised_pnl_by_currency"].items())]),
        "",
        "## 未解决异常与边界",
        "",
        f"- blockers: `{json.dumps(summary['blockers'], ensure_ascii=False)}`",
        f"- warnings: `{json.dumps(summary['warnings'], ensure_ascii=False)}`",
        "- `position_accounting_anomalies.csv` 最多保留 200 个样例；完整逐 Execution 明细只写入被 `.gitignore` 保护的 Parquet。",
        "",
        "## 输出",
        "",
        "- ignored: `quant/outputs/position_accounting_events.parquet`",
        "- committed summaries: terminal_position_accounting.csv, position_accounting_by_symbol.csv, position_action_summary.csv, cost_rounding_policy_audit.csv, xbtusd_snapshot_reconciliation.csv, reported_realised_pnl_diagnostics.csv, position_accounting_anomalies.csv",
    ]
    (reports / "position_accounting.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(root: Path = ROOT) -> dict[str, Any]:
    reports = root / "quant" / "reports"
    outputs = root / "quant" / "outputs"
    reports.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    before_hashes = hash_files(root, PROTECTED_FILES)
    order = build_order_dimension(root / "api-v1-order.csv")
    instruments = load_instruments(root / "api-v1-instrument.all.csv")
    evidence = load_settlement_evidence(root / "quant" / "config" / "historical_settlement_evidence.json")
    normalized = normalize_executions(root / "api-v1-execution-tradeHistory.csv", order, instruments, evidence)
    assert_unique_exec_ids(normalized)
    position_replay = replay_positions(normalized["events"])
    registry = load_historical_specs(root / "quant" / "config" / "historical_instrument_specs.json", root / "api-v1-instrument.all.csv", source_commit())
    mapping = resolve_specs_for_events(normalized["events"], registry)
    price = reconcile_execution_prices(normalized["events"], registry, mapping)
    assets = load_asset_scale_registry(root / "api-v1-wallet-assets.csv")
    valuation = build_execution_valuation(normalized["events"], registry, mapping, assets, price_reconciliation=price)
    policy = load_accounting_policy(root / "quant" / "config" / "position_accounting_policy.json")
    specs = {str(spec.get("spec_id")): spec for spec in registry.get("specs", [])}
    accounting = build_position_accounting(valuation["valuations"], position_replay["position_events"], specs, policy)

    snapshot = read_snapshot(root / "api-v1-position.snapshot.csv")
    snapshot_result = {"rows": [], "status": BLOCKED}
    if accounting.get("terminal"):
        snapshot_result = reconcile_terminal_snapshot(
            accounting["terminal"],
            snapshot,
            snapshot_display_quantum=policy["snapshot_display"]["quantum"],
            snapshot_display_rounding=policy["snapshot_display"]["rounding"],
        )
    events = accounting.get("events", [])
    policy_rows = accounting.get("policy_audit", {}).get("rows", [])
    tables = build_report_tables(events, accounting.get("terminal", []), policy_rows, accounting.get("anomalies", []))
    tables["snapshot"] = snapshot_result.get("rows", [])

    raw_type_counts = Counter(event.get("execType", "") for event in normalized["events"])
    derivative_events = [event for event in normalized["events"] if event.get("instrument_class") == "DERIVATIVE"]
    eligibility_counts = Counter(row.get("accounting_eligibility", "") for row in events)
    action_counts = Counter(row.get("action", "") for row in events)
    gross_by_currency: dict[str, Decimal] = defaultdict(Decimal)
    for row in events:
        if row.get("execType") in {"Trade", "Settlement"}:
            value = _decimal(row.get("gross_realised_pnl_exact_raw"))
            if value is not None:
                gross_by_currency[str(row.get("settlement_currency", ""))] += value
    reported_non_null = [
        row for row in events
        if row.get("reported_realisedPnl_raw") not in (None, "")
        and str(row.get("reported_realisedPnl_raw")).strip()
    ]
    reported_differences = [_decimal(row.get("reported_pnl_difference_raw")) or Decimal(0) for row in reported_non_null]
    terminal = accounting.get("terminal", [])
    terminal_by_symbol = {row.get("symbol"): row for row in terminal}
    nonzero_terminal_symbols = sorted(symbol for symbol, row in terminal_by_symbol.items() if int(row.get("position_qty") or 0) != 0)
    flat_residual = sum(int(row.get("position_qty") or 0) == 0 and _decimal(row.get("current_cost_api_raw")) != 0 for row in terminal)
    position_after_by_exec = {
        item.get("execID"): item.get("position_after")
        for item in position_replay["position_events"]
    }
    position_after_matches = len(events) == len(derivative_events) and all(
        str(row.get("position_after")) == str(position_after_by_exec.get(row.get("execID"), "__missing__"))
        for row in events
    )
    protected_after = hash_files(root, PROTECTED_FILES)
    changed_files = [name for name in PROTECTED_FILES if before_hashes.get(name) != protected_after.get(name)]
    blockers = list(accounting.get("blockers", []))
    if normalized["raw_rows"] != EXPECTED_RAW:
        blockers.append(f"raw execution count {normalized['raw_rows']} != {EXPECTED_RAW}")
    if len(derivative_events) != EXPECTED_DERIVATIVE:
        blockers.append(f"derivative execution count {len(derivative_events)} != {EXPECTED_DERIVATIVE}")
    if raw_type_counts.get("Trade", 0) - EXPECTED_SPOT != EXPECTED_TRADE or raw_type_counts.get("Funding", 0) != EXPECTED_FUNDING or raw_type_counts.get("Settlement", 0) != EXPECTED_SETTLEMENT:
        blockers.append(f"execType counts differ: {dict(raw_type_counts)}")
    if len(events) != EXPECTED_DERIVATIVE:
        blockers.append("position accounting output does not cover all derivative executions")
    if not position_after_matches:
        blockers.append("position_after does not match the M0-02A stable quantity replay")
    if sum(event.get("instrument_class") == "SPOT" for event in events):
        blockers.append("Spot execution entered position accounting")
    if accounting.get("summary", {}).get("accounting_blocked_count", 0):
        blockers.append("accounting rows became BLOCKED during replay")
    if snapshot_result.get("status") != PASS:
        blockers.append("XBTUSD snapshot reconciliation failed")
    if flat_residual:
        blockers.append(f"flat terminal symbols have non-zero cost: {flat_residual}")
    if any(symbol != SNAPSHOT_SYMBOL for symbol in nonzero_terminal_symbols):
        blockers.append(f"non-XBTUSD terminal positions remain non-zero: {nonzero_terminal_symbols}")
    if changed_files:
        blockers.append(f"protected raw files changed: {changed_files}")
    if accounting.get("policy_audit", {}).get("selection_status") != PASS:
        blockers.append("rounding policy selection did not pass")
    warnings: list[str] = []
    if eligibility_counts.get("ACCOUNTING_ELIGIBLE_WITH_WARNING", 0):
        warnings.append(f"{eligibility_counts['ACCOUNTING_ELIGIBLE_WITH_WARNING']} valuation warnings remained accounting-eligible")
    if reported_differences:
        warnings.append(f"{sum(value != 0 for value in reported_differences)} reported realisedPnl rows differ from reconstructed gross trading PnL; diagnostic only")
    if not position_replay.get("position_replay_status") == "PASS":
        warnings.append("M0-02A position replay status was not PASS; quantity comparison is still performed row-by-row")
    status = BLOCKED if blockers else ("READY_WITH_WARNINGS" if warnings else PASS)
    if blockers:
        if accounting.get("policy_audit", {}).get("selection_status") != PASS:
            readiness = "BLOCKED_BY_ACCOUNTING_ROUNDING_POLICY"
        elif snapshot_result.get("status") != PASS:
            readiness = "BLOCKED_BY_TERMINAL_COST_RECONCILIATION"
        else:
            readiness = "BLOCKED_BY_POSITION_ACCOUNTING"
    else:
        readiness = "READY_FOR_POSITION_LIFECYCLE_REPLAY"
    summary = {
        "position_accounting_status": status,
        "m0_02b1b1_readiness": readiness,
        "blockers": blockers,
        "warnings": warnings,
        "input_counts": {
            "raw_execution_count": normalized["raw_rows"],
            "derivative_execution_count": len(derivative_events),
            "trade_count": sum(event.get("execType") == "Trade" for event in derivative_events),
            "funding_count": sum(event.get("execType") == "Funding" for event in derivative_events),
            "settlement_count": sum(event.get("execType") == "Settlement" for event in derivative_events),
            "spot_execution_count": sum(event.get("instrument_class") == "SPOT" for event in normalized["events"]),
            "spot_accounting_rows": sum(event.get("instrument_class") == "SPOT" for event in events),
            "exec_type_counts": dict(raw_type_counts),
        },
        "accounting_eligibility_counts": dict(eligibility_counts),
        "action_counts": dict(action_counts),
        "flip_count": sum(count for action, count in action_counts.items() if action.startswith("FLIP_")),
        "full_close_count": accounting.get("summary", {}).get("full_close_count", 0),
        "position_cycle_count": accounting.get("summary", {}).get("cycle_count", 0),
        "conservation": {
            "exact_conservation_failure_count": accounting.get("summary", {}).get("exact_conservation_failure_count", 0),
            "api_conservation_failure_count": accounting.get("summary", {}).get("api_conservation_failure_count", 0),
            "flip_exec_cost_split_failure_count": accounting.get("summary", {}).get("flip_exec_cost_split_failure_count", 0),
            "full_close_residual_cost_count": accounting.get("summary", {}).get("full_close_residual_cost_count", 0),
            "settlement_residual_cost_count": accounting.get("summary", {}).get("settlement_residual_cost_count", 0),
        },
        "rounding_policy": {
            "selected_average_cost_release": accounting.get("selected_average_cost_release"),
            "selected_flip_exec_cost_split": accounting.get("selected_flip_exec_cost_split"),
            "ambiguity_count": accounting.get("rounding_policy_ambiguity_count", accounting.get("policy_audit", {}).get("ambiguity_count", 0)),
            "selection_reason": accounting.get("policy_audit", {}).get("selection_reason", ""),
        },
        "terminal_checks": {
            "flat_terminal_residual_cost_count": flat_residual,
            "settlement_applied_count": sum(row.get("execType") == "Settlement" and row.get("position_after") == 0 for row in events),
            "nonzero_terminal_symbols": nonzero_terminal_symbols,
            "xbtusd": terminal_by_symbol.get(SNAPSHOT_SYMBOL, {}),
            "snapshot_reconciliation_status": snapshot_result.get("status"),
        },
        "reported_realised_pnl": {
            "non_null": len(reported_non_null),
            "exact": sum(value == 0 for value in reported_differences),
            "mismatch": sum(value != 0 for value in reported_differences),
            "missing": len(events) - len(reported_non_null),
            "max_abs_difference_raw": format(max((value.copy_abs() for value in reported_differences), default=Decimal(0)), "f"),
        },
        "gross_realised_pnl_by_currency": {currency: format(value, "f") for currency, value in sorted(gross_by_currency.items())},
        "output_rows": len(events),
    }
    protected = {"unchanged": not changed_files, "changed_files": changed_files, "before": before_hashes, "after": protected_after}
    if events:
        write_parquet(events, outputs / "position_accounting_events.parquet")
    write_reports(reports, tables, summary, protected, source_commit(), git_value(["rev-parse", "HEAD"]), git_value(["branch", "--show-current"]))
    return {"summary": summary, "accounting": accounting, "snapshot": snapshot_result, "protected": protected, "tables": tables}


def main() -> int:
    result = run(ROOT)
    summary = result["summary"]
    print(f"position_accounting_status={summary['position_accounting_status']}")
    print(f"m0_02b1b1_readiness={summary['m0_02b1b1_readiness']}")
    print(f"derivative_execution_count={summary['input_counts']['derivative_execution_count']}")
    print(f"accounting_eligibility={summary['accounting_eligibility_counts']}")
    print(f"action_counts={summary['action_counts']}")
    print(f"flip_count={summary['flip_count']}")
    print(f"position_cycle_count={summary['position_cycle_count']}")
    print(f"exact_conservation_failure={summary['conservation']['exact_conservation_failure_count']}")
    print(f"api_conservation_failure={summary['conservation']['api_conservation_failure_count']}")
    print(f"selected_average_cost_release={summary['rounding_policy']['selected_average_cost_release']}")
    print(f"selected_flip_exec_cost_split={summary['rounding_policy']['selected_flip_exec_cost_split']}")
    print(f"rounding_policy_ambiguity_count={summary['rounding_policy']['ambiguity_count']}")
    print(f"xbtusd={summary['terminal_checks']['xbtusd']}")
    print(f"snapshot_status={summary['terminal_checks']['snapshot_reconciliation_status']}")
    print(f"raw_files_unchanged={result['protected']['unchanged']}")
    if summary["blockers"]:
        print("blockers:")
        for blocker in summary["blockers"]:
            print(f"- {blocker}")
        return 1
    if summary["warnings"]:
        print("warnings:")
        for warning in summary["warnings"]:
            print(f"- {warning}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
