#!/usr/bin/env python3
"""M0-02A: reconstruct contract-count positions from the frozen execution ledger."""

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

from bitmex_replay.execution_normalizer import assert_unique_exec_ids, load_instruments, normalize_executions  # noqa: E402
from bitmex_replay.io_utils import clean, hash_files, iter_csv_dicts  # noqa: E402
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
SETTLEMENT_DOC = "https://support.bitmex.com/hc/en-gb/articles/18588991131933-What-Is-Settlement-and-How-Is-Settlement-Price-Calculated-on-BitMEX"
EXECUTION_DOC = "https://docs.bitmex.com/api-explorer/get-execution"


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
            for key in ("source_row_number", "event_time", "execID", "execType", "symbol", "side", "lastQty", "orderID", "order_join_status")
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


def build_readiness(
    *,
    hashes: dict[str, Any],
    normalized: dict[str, Any],
    order_dimension: Any,
    join_rows_equal: bool,
    reconciliation: dict[str, Any],
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
    unresolved_settlements = [event for event in normalized["settlement_events"] if event.get("settlement_status") == "UNRESOLVED"]
    if unresolved_settlements:
        blockers.append(f"{len(unresolved_settlements)} Settlement rows remain UNRESOLVED.")
    invalid_trades = [event for event in normalized["events"] if event.get("execType") == "Trade" and event.get("normalization_status") == "ERROR"]
    if invalid_trades:
        blockers.append(f"{len(invalid_trades)} Trade rows have invalid side/lastQty and were not applied.")
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
    warnings.append("This is contract-quantity replay only; no average entry price, PnL, equity, leverage, margin, market data, or trading API was used.")
    return {"status": "BLOCKED" if blockers else "READY_WITH_WARNINGS", "blockers": blockers, "warnings": warnings}


def write_markdown_report(data: dict[str, Any], path: Path) -> None:
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

    counts = data["execution"]["type_counts"]
    reconciliation = data["reconciliation"]
    readiness = data["readiness"]
    terminal = data["terminal_positions"]
    nonzero = [row for row in terminal if row["reconstructed_position"] != 0]
    settlement_rows = data["settlement"]["events"]
    lines = [
        "# M0-02A 合约张数仓位回放报告",
        "",
        f"分析 commit：`{data['analysis']['commit']}`；分支：`{data['analysis']['branch']}`",
        f"数据源 commit：`{data['source']['data_commit']}`",
        "",
        "## 执行摘要",
        "",
        f"- 状态：**{readiness['status']}**",
        f"- 标准化 execution：`{data['execution']['normalized_rows']:,}` 行；Join 前后：`{data['execution']['join_rows_before']:,}` → `{data['execution']['join_rows_after']:,}`。",
        f"- XBTUSD 终态对账：**{reconciliation['reconciliation_status']}**，重建值 `{reconciliation['reconstructed_current_qty']}`，快照值 `{reconciliation['snapshot_current_qty']}`。",
        "- 本阶段只重建合约张数；不计算 PnL、净值、杠杆、保证金或行情指标。",
        "",
        "## 原始数据保护",
        "",
        f"保护文件 SHA256 未改变：**{data['protected_files']['unchanged']}**。",
        "",
        table(["指标", "值"], [["变化文件", data["protected_files"]["changed_files"] or "无"]]),
        "",
        "## Execution 标准化与排序",
        "",
        "`event_time` 优先使用 `transactTime`，缺失时回退 `timestamp`；排序键为 event_time、timestamp、source_row_number、execID。原始行号保留为稳定锚点。",
        "",
        table(["execType", "数量"], [[key, value] for key, value in sorted(counts.items())]),
        "",
        table(["normalization_status", "数量"], [[key, value] for key, value in sorted(data["execution"]["normalization_status_counts"].items())]),
        "",
        "## 订单维表与关联",
        "",
        f"订单输入 `{data['order_dimension']['rows_read']:,}` 行；派生唯一 `orderID` `{data['order_dimension']['unique_order_ids']:,}`；派生表删除完全重复行 `{data['order_dimension']['duplicate_full_rows']}`。Join 使用唯一字典映射，不会扩展 execution 行。",
        "",
        table(["指标", "值"], [
            ["Join 前 execution 行数", data["execution"]["join_rows_before"]],
            ["Join 后 execution 行数", data["execution"]["join_rows_after"]],
            ["Join 行数断言", data["execution"]["join_rows_before"] == data["execution"]["join_rows_after"]],
            ["非 identical orderID 版本组", len(data["order_dimension"]["non_identical_order_versions"])],
        ]),
        "",
        "### orderID 缺失与关联状态",
        "",
        table(["execType", "orderID 缺失", "UNMATCHED", "NO_ORDER_ID", "NOT_APPLICABLE"], [
            [exec_type, data["execution"]["missing_order_by_type"].get(exec_type, 0),
             data["execution"]["join_counts"].get(f"{exec_type}|UNMATCHED", 0),
             data["execution"]["join_counts"].get(f"{exec_type}|NO_ORDER_ID", 0),
             data["execution"]["join_counts"].get(f"{exec_type}|NOT_APPLICABLE", 0)]
            for exec_type in sorted(counts)
        ]),
        "",
        "无法匹配的 execution 示例：",
        "",
        f"共 `{len(data['execution']['unmatched_unique_order_ids'])}` 个唯一未匹配 orderID，对应 `{sum(1 for event in data['execution']['unmatched_examples'])}` 个示例行（报告最多展示 100 行）：",
        "",
        f"`{data['execution']['unmatched_unique_order_ids']}`",
        "",
        "```json",
        json.dumps(data["execution"]["unmatched_examples"], ensure_ascii=False, indent=2),
        "```",
        "",
        "## Settlement 处理",
        "",
        f"共 `{data['settlement']['total']}` 条；状态分布：`{data['settlement']['status_counts']}`。依据：BitMEX 说明到期时未平仓合约自动关闭；本阶段只应用合约数量变化，不计算结算 PnL。",
        "",
        table(["execID", "symbol", "side", "lastQty", "settlement_status", "reason"], [[
            row.get("execID"), row.get("symbol"), row.get("side"), row.get("lastQty"), row.get("settlement_status"), row.get("settlement_reason")
        ] for row in settlement_rows]),
        "",
        "## 仓位回放",
        "",
        table(["action", "数量"], [[key, value] for key, value in sorted(data["position"]["action_counts"].items())]),
        "",
        "### 非零终态仓位",
        "",
        table(["symbol", "reconstructed_position", "trade_events", "settlement_events", "final_status"], [[
            row["symbol"], row["reconstructed_position"], row["trade_event_count"], row["settlement_event_count"], row["final_status"]
        ] for row in nonzero] or [["无", 0, 0, 0, "PASS"]]),
        "",
        "### XBTUSD 终态快照对账",
        "",
        table(["字段", "值"], [[key, value] for key, value in reconciliation.items()]),
        "",
        "## 未解决异常与 M0-02B 判断",
        "",
    ]
    if readiness["blockers"]:
        lines.extend(["阻塞项：", "", *[f"- {item}" for item in readiness["blockers"]], ""])
    else:
        lines.extend(["没有达到阻塞阈值的异常。", ""])
    if readiness["warnings"]:
        lines.extend(["警告：", "", *[f"- {item}" for item in readiness["warnings"]], ""])
    lines.extend([
        "M0-02B 仍应另行实现单位、合约类型、平均开仓价和 PnL 规则；本报告不把张数回放误当成财务对账。",
        "",
        f"参考：[Get Executions]({EXECUTION_DOC})、[BitMEX Settlement 说明]({SETTLEMENT_DOC})。",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def run(root: Path = ROOT) -> dict[str, Any]:
    reports = root / "quant" / "reports"
    outputs = root / "quant" / "outputs"
    reports.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    before = hash_files(root, PROTECTED_FILES)

    order_dimension = build_order_dimension(root / "api-v1-order.csv")
    instruments = load_instruments(root / "api-v1-instrument.all.csv")
    normalized = normalize_executions(root / "api-v1-execution-tradeHistory.csv", order_dimension, instruments)
    assert_unique_exec_ids(normalized)
    replay = replay_positions(normalized["events"])
    execution_rows_before = count_execution_rows(root / "api-v1-execution-tradeHistory.csv")
    execution_rows_after = len(normalized["events"])
    hashes = protected_hash_report(root, PROTECTED_FILES, before)
    snapshot = read_position_snapshot(root / "api-v1-position.snapshot.csv", "XBTUSD")
    reconciliation = reconcile_snapshot(replay["position_events"], snapshot)

    normalized_public = [{key: value for key, value in event.items() if not key.startswith("_")} for event in normalized["events"]]
    write_parquet(normalized_public, outputs / "normalized_execution_events.parquet")
    write_parquet(replay["position_events"], outputs / "position_events.parquet")
    terminal_fields = ["symbol", "last_event_time", "reconstructed_position", "trade_event_count", "funding_event_count", "settlement_event_count", "event_count", "final_status"]
    write_csv(replay["terminal_positions"], outputs / "terminal_positions.csv", terminal_fields)
    settlement_fields = [
        "source_row_number", "event_time", "timestamp", "transactTime", "execID", "execType", "symbol", "side", "orderQty", "lastQty", "leavesQty", "price", "lastPx", "avgPx", "currency", "settlCurrency", "execCost", "execComm", "realisedPnl", "homeNotional", "foreignNotional", "orderID", "cumQty", "order_join_status", "settled_position_effect", "settlement_status", "settlement_reason", "normalization_status", "normalization_reason", "signed_qty"
    ]
    settlement_rows = []
    for event in normalized["settlement_events"]:
        row = dict(event)
        row["settled_position_effect"] = row.get("settlement_status", "")
        settlement_rows.append(row)
    write_csv(settlement_rows, reports / "settlement_events.csv", settlement_fields)

    type_mismatch = {key: {"actual": normalized["type_counts"].get(key, 0), "expected": expected} for key, expected in EXPECTED_TYPE_COUNTS.items() if normalized["type_counts"].get(key, 0) != expected}
    join_rows_equal = execution_rows_before == execution_rows_after
    readiness = build_readiness(
        hashes=hashes,
        normalized=normalized,
        order_dimension=order_dimension,
        join_rows_equal=join_rows_equal,
        reconciliation=reconciliation,
    )
    if type_mismatch:
        readiness["blockers"].append(f"execType counts differ from frozen M0-01 facts: {type_mismatch}")
        readiness["status"] = "BLOCKED"

    data: dict[str, Any] = {
        "audit_version": "M0-02A/1.0",
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
        },
        "settlement": {
            "total": len(normalized["settlement_events"]),
            "status_counts": dict(Counter(event.get("settlement_status", "") for event in normalized["settlement_events"])),
            "events": [{key: value for key, value in event.items() if not key.startswith("_")} for event in normalized["settlement_events"]],
            "reference": SETTLEMENT_DOC,
        },
        "position": {"position_event_rows": len(replay["position_events"]), "action_counts": replay["action_counts"]},
        "terminal_positions": replay["terminal_positions"],
        "reconciliation": reconciliation,
        "readiness": readiness,
        "references": {"execution_api": EXECUTION_DOC, "settlement": SETTLEMENT_DOC},
    }
    data["protected_files"] = hashes
    # Re-hash after all derived outputs are written; the output files are not protected.
    data["protected_files"] = protected_hash_report(root, PROTECTED_FILES, before)
    data["readiness"] = build_readiness(
        hashes=data["protected_files"],
        normalized=normalized,
        order_dimension=order_dimension,
        join_rows_equal=join_rows_equal,
        reconciliation=reconciliation,
    )
    if type_mismatch:
        data["readiness"]["blockers"].append(f"execType counts differ from frozen M0-01 facts: {type_mismatch}")
        data["readiness"]["status"] = "BLOCKED"
    json_path = reports / "position_replay.json"
    json_path.write_text(json.dumps(jsonable(data), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown_report(data, reports / "position_replay.md")
    return data


def main() -> int:
    data = run(ROOT)
    print(f"M0-02A position replay completed: {data['readiness']['status']}")
    print(f"Normalized execution rows: {data['execution']['normalized_rows']}")
    print(f"Join rows: {data['execution']['join_rows_before']} -> {data['execution']['join_rows_after']}")
    print(f"XBTUSD reconciliation: {data['reconciliation']['reconciliation_status']}")
    print(f"Report: {ROOT / 'quant' / 'reports' / 'position_replay.md'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
