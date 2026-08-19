from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .io_utils import clean, iter_csv_dicts, parse_datetime


def _fingerprint(row: dict[str, str], columns: list[str]) -> str:
    payload = json.dumps([clean(row.get(column, "")) for column in columns], ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha1(payload.encode("utf-8")).hexdigest()


@dataclass
class OrderDimensionResult:
    dimension: dict[str, dict[str, str]]
    rows_read: int
    unique_order_ids: int
    duplicate_full_rows: int
    duplicate_order_id_counts: dict[str, int]
    non_identical_order_versions: list[dict[str, Any]]
    columns: list[str]


def build_order_dimension(path: Path) -> OrderDimensionResult:
    """Build one deterministic row per orderID without editing the source CSV.

    Exact duplicate rows are removed only in this derived in-memory dimension.
    If a key has distinct rows, the latest timestamp/source line is used as the
    join representative and every version is retained in the audit metadata.
    """

    from .io_utils import read_csv_header

    columns = read_csv_header(path)
    seen_full_rows: set[str] = set()
    groups: dict[str, list[tuple[int, dict[str, str]]]] = {}
    duplicate_order_id_counts: dict[str, int] = {}
    rows_read = 0
    duplicate_full_rows = 0

    for line_number, row in iter_csv_dicts(path):
        rows_read += 1
        fingerprint = _fingerprint(row, columns)
        order_id = clean(row.get("orderID", "")).strip()
        if fingerprint in seen_full_rows:
            duplicate_full_rows += 1
            if order_id:
                duplicate_order_id_counts[order_id] = duplicate_order_id_counts.get(order_id, 0) + 1
            continue
        seen_full_rows.add(fingerprint)
        if order_id:
            groups.setdefault(order_id, []).append((line_number, row))

    dimension: dict[str, dict[str, str]] = {}
    non_identical: list[dict[str, Any]] = []
    for order_id, versions in groups.items():
        def sort_key(item: tuple[int, dict[str, str]]) -> tuple[datetime_sort, int]:
            line_number, row = item
            timestamp = parse_datetime(row.get("timestamp", ""))
            return (timestamp or datetime_sort.max_value(), line_number)

        chosen_line, chosen_row = max(versions, key=sort_key)
        derived = dict(chosen_row)
        derived["_source_row_number"] = str(chosen_line)
        derived["_version_count"] = str(len(versions))
        dimension[order_id] = derived
        if len(versions) > 1:
            non_identical.append(
                {
                    "orderID": order_id,
                    "version_count": len(versions),
                    "source_rows": [line for line, _ in versions],
                    "statuses": sorted({clean(row.get("ordStatus", "")) for _, row in versions}),
                    "timestamps": sorted({clean(row.get("timestamp", "")) for _, row in versions}),
                    "join_representative_source_row": chosen_line,
                }
            )

    return OrderDimensionResult(
        dimension=dimension,
        rows_read=rows_read,
        unique_order_ids=len(dimension),
        duplicate_full_rows=duplicate_full_rows,
        duplicate_order_id_counts=duplicate_order_id_counts,
        non_identical_order_versions=non_identical,
        columns=columns,
    )


class datetime_sort:
    """Small comparable sentinel to avoid importing datetime in sort closures."""

    @staticmethod
    def max_value():
        from datetime import datetime, timezone

        return datetime.max.replace(tzinfo=timezone.utc)
