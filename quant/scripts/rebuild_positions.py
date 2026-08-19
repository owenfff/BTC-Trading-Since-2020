#!/usr/bin/env python3
"""M0-02A.1: replay derivative contract quantities and isolate spot executions."""

from __future__ import annotations

import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bitmex_replay.execution_normalizer import (  # noqa: E402
    assert_unique_exec_ids,
    build_instrument_temporal_audit,
    load_instruments,
    load_settlement_evidence,
    normalize_executions,
)
from bitmex_replay.io_utils import hash_files, iter_csv_dicts  # noqa: E402
from bitmex_replay.order_dimension import build_order_dimension  # noqa: E402
from bitmex_replay.position_replayer import replay_positions  # noqa: E402
from bitmex_replay.reconciliation import (  # noqa: E402
    protected_hash_report,
    read_position_snapshot,
    reconcile_snapshot,
    write_csv,
    write_parquet,
)


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
EXPECTED_EXECUTION_ROWS = 173434
EXPECTED_TYPE_COUNTS = {"Trade": 160510, "Funding": 12905, "Settlement": 19}
INSTRUMENT_DOC = "https://docs.bitmex.com/api-explorer/get-instruments"
SETTLEMENT_DOC = "https://www.bitmex.com/blog/axs-eos-link-sol-aave-matic-srm-sushi-trx-uni-vet-and-xlm-quanto-perpetuals-new-listing-and-early-settlement-of-contracts-due-to-naming-conventions"


def git_value(root: Path, args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=root, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def source_commit(root: Path) -> str:
    version_file = root / "quant" / "SOURCE_VERSION.md"
    if version_file.is_file():
        for line in version_file.read_text(encoding="utf-8").splitlines():
            if line.lower().startswith("- source commit:"):
                return line.split(":", 1)[1].strip().strip("`")
    return ""


def jsonable(value: Any) -> Any:
    if isinstance(value, Counter):
        return dict(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items() if not str(key).startswith("_")}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value


def count_execution_rows(path: Path) -> int:
    return sum(1 for _ in iter_csv_dicts(path))


def unmatched_examples(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            key: event.get(key)
            for key in (
                "source_row_number",
                "event_time",
                "execID",
                "execType",
                "symbol",
                "side",
                "lastQty",
                "orderID",
                "order_join_status",
            )
        }
        for event in events
        if event.get("order_join_status") == "UNMATCHED"
    ][:100]


def unmatched_unique_order_ids(events: list[dict[str, Any]]) -> list[str]:
    return sorted(
        {
            str(event.get("orderID"))
            for event in events
            if event.get("order_join_status") == "UNMATCHED" and event.get("orderID")
        }
    )


def _refresh_normalized_counts(normalized: dict[str, Any]) -> None:
    normalized["normalization_status_counts"] = dict(Counter(event.get("normalization_status", "") for event in normalized["events"]))
    normalized["unresolved"] = [
        {
            key: event.get(key)
            for key in (
                "source_row_number",
                "execID",
                "execType",
                "symbol",
                "side",
                "lastQty",
                "orderID",
                "instrument_typ",
                "instrument_class",
                "normalization_status",
                "normalization_reason",
            )
        }
        for event in normalized["events"]
        if event.get("normalization_status") in {"ERROR", "UNRESOLVED"}
    ]


def build_statuses(
    *,
    hashes: dict[str, Any],
    normalized: dict[str, Any],
    order_dimension: Any,
    join_rows_equal: bool,
    reconciliation: dict[str, Any],
    replay: dict[str, Any],
    temporal_audit: list[dict[str, Any]],
) -> dict[str, Any]:
    blockers: list[str] = []
    warnings: list[str] = []
    if not hashes["unchanged"]:
        blockers.append(f"Protected raw files changed: {hashes['changed_files']}")
    if normalized["raw_rows"] != EXPECTED_EXECUTION_ROWS:
        blockers.append(f"Normalized execution rows are {normalized['raw_rows']}, expected {EXPECTED_EXECUTION_ROWS}.")
    if not join_rows_equal:
        blockers.append("Execution row count changed across the order join.")
    if normalized["duplicate_exec_ids"]:
        blockers.append("Duplicate execID values were detected.")
    if reconciliation.get("reconciliation_status") != "PASS":
        blockers.append("XBTUSD terminal position does not reconcile to the snapshot.")
    if replay["derivative_errors"]:
        blockers.append(f"{len(replay['derivative_errors'])} derivative execution/Settlement events failed normalization or close validation.")
    unknown_trades = [
        event
        for event in normalized["events"]
        if event.get("execType") == "Trade" and event.get("instrument_class") in {"UNKNOWN", "REFERENCE_INDEX"}
    ]
    if unknown_trades:
        blockers.append(f"{len(unknown_trades)} Trade events have UNKNOWN/REFERENCE_INDEX instrument class.")
    if order_dimension.duplicate_full_rows:
        warnings.append(f"{order_dimension.duplicate_full_rows} exact duplicate order rows were removed only in the derived order dimension.")
    if order_dimension.non_identical_order_versions:
        warnings.append(f"{len(order_dimension.non_identical_order_versions)} orderID groups still have non-identical versions; representative rows are documented.")
    unmatched = sum(1 for event in normalized["events"] if event.get("order_join_status") == "UNMATCHED")
    if unmatched:
        warnings.append(f"{unmatched} execution rows have an orderID that is not present in order_dimension; executions were retained.")
    no_order_trade = sum(1 for event in normalized["events"] if event.get("execType") == "Trade" and event.get("order_join_status") == "NO_ORDER_ID")
    if no_order_trade:
        warnings.append(f"{no_order_trade} Trade rows have no orderID and were replayed from execution fields.")
    historical_symbols = [row["symbol"] for row in temporal_audit if row.get("requires_historical_spec")]
    if historical_symbols:
        warnings.append(f"{len(historical_symbols)} symbols have execution before current metadata listing; M0-02B remains blocked until historical specs are versioned.")
    if normalized["instrument_class_counts"].get("SPOT", 0):
        spot_trade_count = sum(1 for event in normalized["events"] if event.get("instrument_class") == "SPOT" and event.get("execType") == "Trade")
        warnings.append(f"{spot_trade_count} Spot Trade events were retained as SPOT_BALANCE_DELTA and excluded from derivative positions.")
    warnings.append("This is contract-quantity replay only; no average entry price, PnL, equity, leverage, margin, market data, or trading API was used.")
    position_status = "BLOCKED" if blockers else ("READY_WITH_WARNINGS" if warnings else "PASS")
    m0_02b_status = "BLOCKED_BY_HISTORICAL_INSTRUMENT_METADATA" if historical_symbols else "READY_WITH_WARNINGS"
    return {
        "status": position_status,
        "position_replay_status": position_status,
        "m0_02b_readiness": m0_02b_status,
        "blockers": blockers,
        "warnings": warnings,
        "historical_spec_symbols": historical_symbols,
    }


def table(headers: list[str], rows: list[list[Any]]) -> str:
    def cell(value: Any) -> str:
        return str("" if value is None else value).replace("|", "\\|").replace("\n", " ")

    return "\n".join(
        [
            "| " + " | ".join(headers) + " |",
            "| " + " | ".join("---" for _ in headers) + " |",
            *["| " + " | ".join(cell(value) for value in row) + " |" for row in rows],
        ]
    )


def write_temporal_audit(rows: list[dict[str, Any]], csv_path: Path, md_path: Path) -> None:
    fields = [
        "symbol", "first_execution_time", "last_execution_time", "metadata_listing", "metadata_expiry",
        "metadata_settle", "typ", "instrument_class", "first_execution_before_listing",
        "metadata_temporal_status", "requires_historical_spec", "metadata_record_count", "note",
    ]
    write_csv(rows, csv_path, fields)
    md_lines = [
        "# Instrument Temporal Audit",
        "",
        "`api-v1-instrument.all.csv` is treated as a snapshot. It is retained as a list of metadata records per symbol and is not silently overwritten. A symbol with execution before current listing requires historical contract specifications before M0-02B.",
        "",
        table(["metadata_temporal_status", "count"], [[status, sum(row["metadata_temporal_status"] == status for row in rows)] for status in sorted({row["metadata_temporal_status"] for row in rows})]),
        "",
        table(["symbol", "first_execution_time", "metadata_listing", "typ", "status", "requires_historical_spec"], [[
            row["symbol"], row["first_execution_time"], row["metadata_listing"], row["typ"], row["metadata_temporal_status"], row["requires_historical_spec"]
        ] for row in rows]),
        "",
        f"Reference: [Get Instruments | BitMEX API]({INSTRUMENT_DOC})",
        "",
    ]
    md_path.write_text("\n".join(md_lines), encoding="utf-8")


def write_markdown_report(data: dict[str, Any], path: Path) -> None:
    counts = data["execution"]["type_counts"]
    readiness = data["readiness"]
    reconciliation = data["reconciliation"]
    settlement_rows = data["settlement"]["events"]
    nonzero_derivative = [row for row in data["terminal_positions"] if row["instrument_class"] == "DERIVATIVE" and row["reconstructed_position"] != 0]
    instrument_classes = data["execution"]["instrument_class_counts"]
    spot_rows = data["spot_execution_summary"]
    lines = [
        "# M0-02A.1 合约张数仓位回放报告",
        "",
        f"分析 commit：`{data['analysis']['commit']}`；分支：`{data['analysis']['branch']}`",
        f"数据源 commit：`{data['source']['data_commit']}`",
        "",
        "## 状态",
        "",
        f"- `position_replay_status`：**{readiness['position_replay_status']}**",
        f"- `m0_02b_readiness`：**{readiness['m0_02b_readiness']}**",
        f"- 标准化 execution：`{data['execution']['normalized_rows']:,}` 行；Join 前后：`{data['execution']['join_rows_before']:,}` → `{data['execution']['join_rows_after']:,}`。",
        f"- XBTUSD 对账：**{reconciliation['reconciliation_status']}**，重建 `{reconciliation['reconstructed_current_qty']}`，快照 `{reconciliation['snapshot_current_qty']}`。",
        "- 本阶段只重建衍生品合约张数；Spot 只保留原始成交余额方向，不计算完整资产单位；不计算 PnL、净值、杠杆或保证金。",
        "",
        "## 原始数据保护",
        "",
        f"保护文件 SHA256 未改变：**{data['protected_files']['unchanged']}**；变化文件：`{data['protected_files']['changed_files'] or '无'}`。",
        "",
        "## Execution 与 instrument 分类",
        "",
        "`event_time` 优先使用 `transactTime`，缺失时回退 `timestamp`；随后按 timestamp、原始行号和 execID 稳定排序。BitMEX 的 instrument `typ` 分类依据官方 API 文档；不通过 symbol 下划线推断 Spot。",
        "",
        table(["execType", "count"], [[key, value] for key, value in sorted(counts.items())]),
        "",
        table(["instrument_class", "execution_count"], [[key, value] for key, value in sorted(instrument_classes.items())]),
        "",
        table(["Trade instrument_class", "trade_count"], [[key, value] for key, value in sorted(data["execution"]["trade_class_counts"].items())]),
        "",
        table(["instrument_typ", "execution_count"], [[key, value] for key, value in sorted(data["execution"]["instrument_typ_counts"].items())]),
        "",
        "## 订单维表与关联",
        "",
        f"订单输入 `{data['order_dimension']['rows_read']:,}` 行；一行一个 `orderID` 的派生维表 `{data['order_dimension']['unique_order_ids']:,}` 个；完全重复行 `{data['order_dimension']['duplicate_full_rows']}`；非 identical 版本组 `{len(data['order_dimension']['non_identical_order_versions'])}`。",
        "",
        table(["execType", "missing orderID", "UNMATCHED", "NO_ORDER_ID", "NOT_APPLICABLE"], [[
            exec_type,
            data["execution"]["missing_order_by_type"].get(exec_type, 0),
            data["execution"]["join_counts"].get(f"{exec_type}|UNMATCHED", 0),
            data["execution"]["join_counts"].get(f"{exec_type}|NO_ORDER_ID", 0),
            data["execution"]["join_counts"].get(f"{exec_type}|NOT_APPLICABLE", 0),
        ] for exec_type in sorted(counts)]),
        "",
        f"唯一未匹配 orderID：`{data['execution']['unmatched_unique_order_ids']}`；具体 execution 示例：",
        "",
        "```json",
        json.dumps(data["execution"]["unmatched_examples"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Spot Trade 隔离",
        "",
        "Spot Trade 仍在 normalized execution 中，但 `signed_contract_qty=0`，不进入衍生品仓位累计；摘要单独输出。",
        "",
        table(["symbol", "typ", "trade_count", "buy_raw_qty", "sell_raw_qty", "net_base_qty_raw"], [[
            row["symbol"], row["instrument_typ"], row["trade_count"], row["buy_raw_qty"], row["sell_raw_qty"], row["net_base_qty_raw"]
        ] for row in spot_rows]),
        "",
        "## Settlement 处理",
        "",
        f"共 `{len(settlement_rows)}` 条；状态分布：`{data['settlement']['status_counts']}`。每条 Settlement 都经过 position_before、side、lastQty、signed_qty、position_after 和完整归零校验。AAVEUSDT 使用配置化官方提前结算证据，仍必须满足仓位闭合不变量。",
        "",
        table(["execID", "symbol", "side", "lastQty", "position_before", "signed_qty", "position_after", "settlement_status", "resolution_method"], [[
            row.get("execID"), row.get("symbol"), row.get("side"), row.get("lastQty"), row.get("position_before"), row.get("signed_contract_qty"), row.get("position_after"), row.get("settlement_status"), row.get("settlement_resolution_method")
        ] for row in settlement_rows]),
        "",
        "## 衍生品仓位终态",
        "",
        table(["symbol", "typ", "reconstructed_position", "trade_events", "settlement_events", "final_status"], [[
            row["symbol"], row["instrument_typ"], row["reconstructed_position"], row["trade_event_count"], row["settlement_event_count"], row["final_status"]
        ] for row in nonzero_derivative] or [["无", "", 0, 0, 0, "PASS"]]),
        "",
        table(["field", "value"], [[key, value] for key, value in reconciliation.items()]),
        "",
        "## Instrument Temporal Audit",
        "",
        f"需要历史规格的 symbol：`{readiness['historical_spec_symbols']}`。这些历史元数据风险不阻塞已完成的张数回放，但使 M0-02B 保持 `BLOCKED_BY_HISTORICAL_INSTRUMENT_METADATA`。",
        "",
        "## 未解决异常",
        "",
    ]
    if readiness["blockers"]:
        lines.extend(["阻塞项：", "", *[f"- {item}" for item in readiness["blockers"]], ""])
    else:
        lines.extend(["没有达到仓位回放阻塞阈值的异常。", ""])
    if readiness["warnings"]:
        lines.extend(["警告：", "", *[f"- {item}" for item in readiness["warnings"]], ""])
    lines.extend(
        [
            "M0-02B 仍需建立按历史时间版本化的合约规格表，再处理 multiplier、结算币种、平均成本和 PnL。",
            "",
            f"参考：[Get Instruments | BitMEX API]({INSTRUMENT_DOC})、[BitMEX 提前结算公告]({SETTLEMENT_DOC})。",
            "",
        ]
    )
    path.write_text("\n".join(lines), encoding="utf-8")


def run(root: Path = ROOT) -> dict[str, Any]:
    reports = root / "quant" / "reports"
    outputs = root / "quant" / "outputs"
    config = root / "quant" / "config" / "historical_settlement_evidence.json"
    reports.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    before = hash_files(root, PROTECTED_FILES)

    order_dimension = build_order_dimension(root / "api-v1-order.csv")
    instruments = load_instruments(root / "api-v1-instrument.all.csv")
    settlement_evidence = load_settlement_evidence(config)
    normalized = normalize_executions(root / "api-v1-execution-tradeHistory.csv", order_dimension, instruments, settlement_evidence)
    assert_unique_exec_ids(normalized)
    replay = replay_positions(normalized["events"])
    _refresh_normalized_counts(normalized)
    temporal_audit = build_instrument_temporal_audit(normalized["events"], instruments, {item.get("symbol", "") for item in settlement_evidence.values()})
    execution_rows_before = count_execution_rows(root / "api-v1-execution-tradeHistory.csv")
    execution_rows_after = len(normalized["events"])
    snapshot = read_position_snapshot(root / "api-v1-position.snapshot.csv", "XBTUSD")
    reconciliation = reconcile_snapshot(replay["position_events"], snapshot)
    hashes = protected_hash_report(root, PROTECTED_FILES, before)

    normalized_public = [{key: value for key, value in event.items() if not key.startswith("_")} for event in normalized["events"]]
    write_parquet(normalized_public, outputs / "normalized_execution_events.parquet")
    write_parquet(replay["position_events"], outputs / "position_events.parquet")
    terminal_fields = [
        "symbol", "instrument_typ", "instrument_class", "affects_derivative_position", "last_event_time",
        "reconstructed_position", "trade_event_count", "funding_event_count", "settlement_event_count", "event_count", "final_status",
    ]
    write_csv(replay["terminal_positions"], outputs / "terminal_positions.csv", terminal_fields)
    write_csv(replay["terminal_derivative_positions"], outputs / "terminal_derivative_positions.csv", terminal_fields)
    write_csv(replay["spot_execution_summary"], reports / "spot_execution_summary.csv", [
        "symbol", "instrument_typ", "trade_count", "buy_raw_qty", "sell_raw_qty", "net_base_qty_raw", "currency", "first_event_time", "last_event_time", "note",
    ])
    settlement_fields = [
        "source_row_number", "event_time", "timestamp", "transactTime", "execID", "execType", "symbol", "side", "instrument_typ", "instrument_class",
        "instrument_metadata_listing", "instrument_metadata_expiry", "instrument_metadata_settle", "instrument_metadata_status", "orderQty", "lastQty", "cumQty", "leavesQty",
        "price", "lastPx", "avgPx", "currency", "settlCurrency", "execCost", "execComm", "realisedPnl", "homeNotional", "foreignNotional", "orderID",
        "order_join_status", "position_before", "signed_contract_qty", "position_after", "action", "settled_position_effect", "settlement_status", "settlement_reason",
        "settlement_resolution_method", "evidence_status", "evidence_source_url", "normalization_status", "normalization_reason",
    ]
    settlement_rows = []
    for event in normalized["settlement_events"]:
        row = dict(event)
        row["settled_position_effect"] = row.get("settlement_status", "")
        settlement_rows.append(row)
    write_csv(settlement_rows, reports / "settlement_events.csv", settlement_fields)
    write_temporal_audit(temporal_audit, reports / "instrument_temporal_audit.csv", reports / "instrument_temporal_audit.md")

    type_mismatch = {
        key: {"actual": normalized["type_counts"].get(key, 0), "expected": expected}
        for key, expected in EXPECTED_TYPE_COUNTS.items()
        if normalized["type_counts"].get(key, 0) != expected
    }
    join_rows_equal = execution_rows_before == execution_rows_after
    readiness = build_statuses(
        hashes=hashes,
        normalized=normalized,
        order_dimension=order_dimension,
        join_rows_equal=join_rows_equal,
        reconciliation=reconciliation,
        replay=replay,
        temporal_audit=temporal_audit,
    )
    if type_mismatch:
        readiness["blockers"].append(f"execType counts differ from frozen M0-01 facts: {type_mismatch}")
        readiness["status"] = "BLOCKED"
        readiness["position_replay_status"] = "BLOCKED"

    data: dict[str, Any] = {
        "audit_version": "M0-02A.1/1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "source": {
            "repository": "owenfff/BTC-Trading-Since-2020",
            "data_commit": source_commit(root),
            "analysis_commit": git_value(root, ["rev-parse", "HEAD"]),
        },
        "analysis": {"commit": git_value(root, ["rev-parse", "HEAD"]), "branch": git_value(root, ["rev-parse", "--abbrev-ref", "HEAD"])},
        "protected_files": hashes,
        "order_dimension": {
            "rows_read": order_dimension.rows_read,
            "unique_order_ids": order_dimension.unique_order_ids,
            "duplicate_full_rows": order_dimension.duplicate_full_rows,
            "duplicate_order_id_counts": order_dimension.duplicate_order_id_counts,
            "non_identical_order_versions": order_dimension.non_identical_order_versions,
        },
        "execution": {
            "normalized_rows": len(normalized["events"]),
            "join_rows_before": execution_rows_before,
            "join_rows_after": execution_rows_after,
            "type_counts": normalized["type_counts"],
            "expected_type_counts": EXPECTED_TYPE_COUNTS,
            "type_mismatch": type_mismatch,
            "join_counts": normalized["join_counts"],
            "missing_order_by_type": normalized["missing_order_by_type"],
            "normalization_status_counts": normalized["normalization_status_counts"],
            "duplicate_exec_ids": normalized["duplicate_exec_ids"],
            "unmatched_examples": unmatched_examples(normalized["events"]),
            "unmatched_unique_order_ids": unmatched_unique_order_ids(normalized["events"]),
            "unresolved": normalized["unresolved"],
            "instrument_typ_counts": normalized["instrument_typ_counts"],
            "instrument_class_counts": normalized["instrument_class_counts"],
            "trade_class_counts": normalized["trade_class_counts"],
            "instrument_distribution": normalized["instrument_distribution"],
        },
        "settlement": {
            "total": len(normalized["settlement_events"]),
            "status_counts": dict(Counter(event.get("settlement_status", "") for event in normalized["settlement_events"])),
            "events": [{key: value for key, value in event.items() if not key.startswith("_")} for event in normalized["settlement_events"]],
            "evidence_config": str(config.relative_to(root)),
            "reference": SETTLEMENT_DOC,
        },
        "position": {
            "position_event_rows": len(replay["position_events"]),
            "action_counts": replay["action_counts"],
            "settlement_status_counts": replay["settlement_status_counts"],
            "position_replay_status": replay["position_replay_status"],
        },
        "terminal_positions": replay["terminal_positions"],
        "terminal_derivative_positions": replay["terminal_derivative_positions"],
        "spot_execution_summary": replay["spot_execution_summary"],
        "instrument_temporal_audit": temporal_audit,
        "reconciliation": reconciliation,
        "readiness": readiness,
        "position_replay_status": readiness["position_replay_status"],
        "m0_02b_readiness": readiness["m0_02b_readiness"],
        "references": {"instrument_api": INSTRUMENT_DOC, "early_settlement": SETTLEMENT_DOC},
    }
    data["protected_files"] = protected_hash_report(root, PROTECTED_FILES, before)
    data["readiness"] = build_statuses(
        hashes=data["protected_files"],
        normalized=normalized,
        order_dimension=order_dimension,
        join_rows_equal=join_rows_equal,
        reconciliation=reconciliation,
        replay=replay,
        temporal_audit=temporal_audit,
    )
    data["position_replay_status"] = data["readiness"]["position_replay_status"]
    data["m0_02b_readiness"] = data["readiness"]["m0_02b_readiness"]
    if type_mismatch:
        data["readiness"]["blockers"].append(f"execType counts differ from frozen M0-01 facts: {type_mismatch}")
        data["readiness"]["status"] = "BLOCKED"
        data["readiness"]["position_replay_status"] = "BLOCKED"
        data["position_replay_status"] = "BLOCKED"
    json_path = reports / "position_replay.json"
    json_path.write_text(json.dumps(jsonable(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown_report(data, reports / "position_replay.md")
    return data


def main() -> int:
    data = run(ROOT)
    print(f"M0-02A.1 position replay status: {data['position_replay_status']}")
    print(f"M0-02B readiness: {data['m0_02b_readiness']}")
    print(f"Normalized execution rows: {data['execution']['normalized_rows']}")
    print(f"Join rows: {data['execution']['join_rows_before']} -> {data['execution']['join_rows_after']}")
    print(f"Spot trades: {sum(row['trade_count'] for row in data['spot_execution_summary'])}")
    print(f"Derivative trades: {data['execution']['trade_class_counts'].get('DERIVATIVE', 0)}")
    print(f"Settlement statuses: {data['settlement']['status_counts']}")
    print(f"XBTUSD reconciliation: {data['reconciliation']['reconciliation_status']}")
    print(f"Report: {ROOT / 'quant' / 'reports' / 'position_replay.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
