#!/usr/bin/env python3
"""Build a currency-separated wallet ledger and reconciliation reports."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bitmex_replay.execution_valuation import load_asset_scale_registry  # noqa: E402
from bitmex_replay.io_utils import hash_files  # noqa: E402
from bitmex_replay.reconciliation import write_csv, write_parquet  # noqa: E402
from bitmex_replay.wallet_ledger import (  # noqa: E402
    build_daily_wallet_ledger,
    build_execution_aggregate,
    compare_wallet_execution_aggregates,
    load_wallet_ledger,
    reconcile_equity_curve,
    reconcile_wallet_snapshots,
    summarize_wallet_by_type,
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


def git_value(args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def jsonable(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [jsonable(item) for item in value]
    return value


def write_markdown(reports: Path, summary: dict[str, Any]) -> None:
    lines = [
        "# Wallet Reconciliation",
        "",
        f"- status: **{summary['wallet_reconciliation_status']}**",
        f"- analysis commit: `{summary['analysis_commit']}`",
        f"- source commit: `{summary['source_commit']}`",
        f"- raw wallet rows: `{summary['wallet_row_count']}`",
        f"- completed rows: `{summary['completed_row_count']}`; pending/canceled rows excluded from balance continuity: `{summary['non_completed_row_count']}`",
        f"- raw inputs unchanged: **{summary['raw_inputs_unchanged']}**",
        "",
        "## Unit and currency boundary",
        "",
        "Each amount remains an integer raw wallet unit and also has a Decimal major-unit view using the frozen wallet-assets scale. Currencies are never combined without an explicit conversion source. USDt Conversion and SpotTrade remain separate transaction groups.",
        "",
        "## Coverage",
        "",
        "| check | value |",
        "| --- | ---: |",
        f"| continuity PASS rows | {summary['continuity_status_counts'].get('PASS', 0)} |",
        f"| continuity mismatch rows | {summary['continuity_status_counts'].get('BALANCE_DELTA_MISMATCH', 0)} |",
        f"| continuity batches | {summary['continuity_batch_count']} |",
        f"| continuity mismatch batches | {summary['continuity_batch_status_counts'].get('BALANCE_DELTA_MISMATCH', 0)} |",
        f"| currencies | {', '.join(summary['currencies'])} |",
        f"| snapshot exact PASS rows | {summary['snapshot_pass_count']} / {summary['snapshot_row_count']} |",
        f"| snapshot zero-without-history rows | {summary['snapshot_zero_without_history_count']} |",
        f"| snapshot unresolved/mismatch rows | {summary['snapshot_unresolved_count']} |",
        f"| equity terminal status | {summary['equity_curve']['status']} |",
        "",
        "## Wallet / Execution / Funding comparison",
        "",
        "The comparison is aggregate-only. A difference does not claim a broken row-level mapping because wallet rows do not carry a universally unique execution reference.",
        "",
        "| wallet type | execution type | currency | wallet raw | execution raw | difference | status |",
        "| --- | --- | --- | ---: | ---: | ---: | --- |",
    ]
    for row in summary["wallet_execution_comparisons"]:
        lines.append(f"| {row['wallet_type']} | {row['execution_type']} | {row['currency']} | {row['wallet_amount_raw']} | {row['execution_amount_raw']} | {row['difference_raw']} | {row['status']} |")
    lines.extend([
        "",
        "## Snapshot and equity boundaries",
        "",
        "Wallet snapshot, margin snapshot, and derived equity curve are retained as separate evidence. Margin balance and unrealised PnL are not added to wallet cash.",
        "",
        "## Next action",
        "",
        "Use this ledger's per-event and per-day features to build BTC-first order episodes, decision episodes, and trade cycles; carry wallet and reconciliation confidence into each episode.",
        "",
        "## Outputs",
        "",
        "- ignored: `quant/outputs/wallet_ledger.parquet`, `quant/outputs/wallet_daily_ledger.parquet`",
        "- committed: wallet_reconciliation.json, wallet_reconciliation_by_day.csv, wallet_reconciliation_by_type.csv, wallet_reconciliation_anomalies.csv",
    ])
    (reports / "wallet_reconciliation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(root: Path = ROOT) -> dict[str, Any]:
    root = Path(root)
    reports = root / "quant" / "reports"
    outputs = root / "quant" / "outputs"
    reports.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    before = hash_files(root, PROTECTED_FILES)
    assets = load_asset_scale_registry(root / "api-v1-wallet-assets.csv")
    rows = load_wallet_ledger(root / "api-v1-user-walletHistory.csv", assets)
    daily = build_daily_wallet_ledger(rows)
    by_type = summarize_wallet_by_type(rows)
    snapshots = reconcile_wallet_snapshots(rows, root / "api-v1-user-wallet.snapshot-all.csv")
    equity = reconcile_equity_curve(rows, root / "derived-equity-curve.csv")
    execution = build_execution_aggregate(root / "api-v1-execution-tradeHistory.csv")
    comparisons = compare_wallet_execution_aggregates(by_type, execution)
    after = hash_files(root, PROTECTED_FILES)
    changed = [name for name in PROTECTED_FILES if before.get(name) != after.get(name)]
    continuity = Counter(str(row.get("continuity_status", "")) for row in rows)
    batch_status_by_id = {
        str(row["continuity_batch_id"]): str(row.get("continuity_batch_status", ""))
        for row in rows if row.get("continuity_batch_id")
    }
    continuity_batches = Counter(batch_status_by_id.values())
    completed = sum(row.get("is_completed") is True for row in rows)
    snapshot_pass = sum(row.get("status") == "PASS" for row in snapshots)
    mismatch_count = continuity.get("BALANCE_DELTA_MISMATCH", 0)
    snapshot_unresolved = sum(row.get("status") == "UNRESOLVED_OR_MISMATCH" for row in snapshots)
    status = "PASS" if not changed and not any(row.get("parse_status") == "BLOCKED" for row in rows) and mismatch_count == 0 and snapshot_unresolved == 0 and equity.get("status") == "PASS" else "READY_WITH_WARNINGS"
    summary = {
        "report_version": "M1-WALLET-LEDGER-1.0",
        "analysis_commit": git_value(["rev-parse", "HEAD"]),
        "analysis_branch": git_value(["branch", "--show-current"]),
        "source_commit": next((line.split(":", 1)[1].strip().strip("`") for line in (root / "quant" / "SOURCE_VERSION.md").read_text(encoding="utf-8").splitlines() if line.lower().startswith("- source commit:")), ""),
        "wallet_reconciliation_status": status,
        "wallet_row_count": len(rows),
        "completed_row_count": completed,
        "non_completed_row_count": len(rows) - completed,
        "currencies": sorted({str(row.get("currency", "")) for row in rows}),
        "transaction_type_counts": dict(Counter(str(row.get("transactType", "")) for row in rows)),
        "continuity_status_counts": dict(continuity),
        "continuity_batch_count": len(batch_status_by_id),
        "continuity_batch_status_counts": dict(continuity_batches),
        "parse_status_counts": dict(Counter(str(row.get("parse_status", "")) for row in rows)),
        "snapshot_row_count": len(snapshots),
        "snapshot_pass_count": snapshot_pass,
        "snapshot_zero_without_history_count": sum(row.get("status") == "ZERO_SNAPSHOT_NO_HISTORY" for row in snapshots),
        "snapshot_unresolved_count": snapshot_unresolved,
        "snapshot_reconciliation": snapshots,
        "equity_curve": equity,
        "wallet_execution_comparisons": comparisons,
        "raw_inputs_unchanged": not changed,
        "changed_protected_files": changed,
        "next_action": "Build BTC-first order episodes, decision episodes, and trade cycles with wallet/reconciliation confidence columns.",
    }
    write_parquet(rows, outputs / "wallet_ledger.parquet")
    write_parquet(daily, outputs / "wallet_daily_ledger.parquet")
    write_csv(daily, reports / "wallet_reconciliation_by_day.csv", list(daily[0].keys()) if daily else ["event_date", "currency", "event_count"])
    write_csv(by_type, reports / "wallet_reconciliation_by_type.csv", list(by_type[0].keys()) if by_type else ["wallet_type_group", "transactType", "currency"])
    anomalies = [row for row in rows if row.get("continuity_status") == "BALANCE_DELTA_MISMATCH" or row.get("parse_status") == "BLOCKED"][:200]
    write_csv(anomalies, reports / "wallet_reconciliation_anomalies.csv", ["source_row_number", "event_time", "transactType", "transactStatus", "currency", "amount_raw", "walletBalance_raw", "previous_walletBalance_raw", "balance_delta_raw", "continuity_status", "parse_status", "parse_reason"])
    (reports / "wallet_reconciliation.json").write_text(json.dumps(jsonable(summary), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_markdown(reports, summary)
    return summary


if __name__ == "__main__":
    result = run()
    print(f"wallet_reconciliation_status={result['wallet_reconciliation_status']}")
    print(f"wallet_row_count={result['wallet_row_count']}")
    print(f"currencies={result['currencies']}")
    print(f"continuity={result['continuity_status_counts']}")
    print(f"snapshot_exact={result['snapshot_pass_count']}/{result['snapshot_row_count']}; zero_without_history={result['snapshot_zero_without_history_count']}; unresolved={result['snapshot_unresolved_count']}")
    print(f"equity_status={result['equity_curve']['status']}")
    print(f"raw_inputs_unchanged={result['raw_inputs_unchanged']}")
