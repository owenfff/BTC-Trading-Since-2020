from __future__ import annotations

import csv
from pathlib import Path
from typing import Any

from .io_utils import clean, hash_files, iter_csv_dicts, parse_datetime, parse_int


def write_parquet(rows: list[dict[str, Any]], path: Path) -> None:
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("pyarrow is required to write M0-02A Parquet outputs") from exc
    table = pa.Table.from_pylist(rows)
    pq.write_table(table, path, compression="zstd")


def write_csv(rows: list[dict[str, Any]], path: Path, fieldnames: list[str]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: "" if row.get(field) is None else row.get(field, "") for field in fieldnames})


def read_position_snapshot(path: Path, symbol: str) -> dict[str, Any] | None:
    for _, row in iter_csv_dicts(path):
        if clean(row.get("symbol", "")).strip() == symbol:
            return {
                "symbol": symbol,
                "timestamp": clean(row.get("timestamp", "")),
                "currentQty": parse_int(row.get("currentQty", "")),
                "raw": row,
            }
    return None


def reconcile_snapshot(position_events: list[dict[str, Any]], snapshot: dict[str, Any] | None) -> dict[str, Any]:
    if snapshot is None:
        return {
            "symbol": "",
            "snapshot_timestamp": "",
            "reconstructed_current_qty": None,
            "snapshot_current_qty": None,
            "difference": None,
            "reconciliation_status": "BLOCKED_SNAPSHOT_MISSING",
        }
    snapshot_dt = parse_datetime(snapshot.get("timestamp", ""))
    eligible = []
    for event in position_events:
        if event.get("symbol") != snapshot.get("symbol"):
            continue
        event_dt = parse_datetime(event.get("event_time", ""))
        if snapshot_dt is not None and event_dt is not None and event_dt <= snapshot_dt:
            eligible.append(event)
    last = max(
        eligible,
        key=lambda event: (parse_datetime(event.get("event_time", "")) or parse_datetime("0001-01-01T00:00:00Z"), event.get("source_row_number", 0)),
        default=None,
    )
    reconstructed = int(last["position_after"]) if last is not None else 0
    snapshot_qty = snapshot.get("currentQty")
    difference = reconstructed - snapshot_qty if snapshot_qty is not None else None
    return {
        "symbol": snapshot.get("symbol", ""),
        "snapshot_timestamp": snapshot.get("timestamp", ""),
        "reconstructed_current_qty": reconstructed,
        "snapshot_current_qty": snapshot_qty,
        "difference": difference,
        "last_event_source_row_number": last.get("source_row_number") if last else None,
        "last_event_execID": last.get("execID") if last else None,
        "reconciliation_status": "PASS" if difference == 0 else "FAIL",
    }


def protected_hash_report(root: Path, filenames: list[str], before: dict[str, str]) -> dict[str, Any]:
    after = hash_files(root, filenames)
    changed = [filename for filename in filenames if before.get(filename) != after.get(filename)]
    return {"before": before, "after": after, "unchanged": not changed, "changed_files": changed}
