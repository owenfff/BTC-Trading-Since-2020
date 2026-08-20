from __future__ import annotations

from collections import Counter, defaultdict
from copy import copy
from typing import Any, Iterable


def _key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("symbol", "")),
        str(row.get("transactTime", "")),
        str(row.get("timestamp", "")),
        str(row.get("orderID", "")),
    )


def _cumqty_chain(group: list[dict[str, Any]]) -> tuple[str, list[dict[str, Any]], str]:
    if any(row.get("cumQty") in (None, "") or row.get("lastQty") in (None, "") for row in group):
        return "AMBIGUOUS", group, "cumQty or lastQty missing"
    try:
        ordered = sorted(group, key=lambda row: (int(row["cumQty"]), int(row.get("source_row_number") or 0)))
        seen = [int(row["cumQty"]) for row in ordered]
        if len(set(seen)) != len(seen):
            return "AMBIGUOUS", group, "duplicate cumQty values"
        previous = 0
        for row in ordered:
            if previous + abs(int(row["lastQty"])) != int(row["cumQty"]):
                return "AMBIGUOUS", group, "cumQty chain has a gap or contradiction"
            previous = int(row["cumQty"])
        return "UNIQUE_CUMQTY_CHAIN", ordered, "previous cumQty + lastQty equals current cumQty"
    except (TypeError, ValueError):
        return "AMBIGUOUS", group, "cumQty/lastQty is not integral"


def audit_execution_order(events: Iterable[dict[str, Any]]) -> dict[str, Any]:
    groups: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("instrument_class") == "DERIVATIVE" and event.get("execType") == "Trade" and event.get("orderID"):
            groups[_key(event)].append(event)
    rows: list[dict[str, Any]] = []
    chain_status_by_exec: dict[str, str] = {}
    rank_by_exec: dict[str, int] = {}
    for key, group in groups.items():
        if len(group) < 2:
            continue
        status, ordered, reason = _cumqty_chain(group)
        for rank, event in enumerate(ordered, start=1):
            exec_id = str(event.get("execID", ""))
            chain_status_by_exec[exec_id] = status
            rank_by_exec[exec_id] = rank if status == "UNIQUE_CUMQTY_CHAIN" else 0
        rows.append({
            "symbol": key[0],
            "transactTime": key[1],
            "timestamp": key[2],
            "orderID": key[3],
            "trade_count": len(group),
            "raw_source_order": ",".join(str(item.get("source_row_number", "")) for item in group),
            "raw_cumQty_order": ",".join(str(item.get("cumQty", "")) for item in group),
            "recovered_execID_order": ",".join(str(item.get("execID", "")) for item in ordered),
            "chain_status": status,
            "reason": reason,
        })
    tie_groups: dict[tuple[str, str, str], set[str]] = defaultdict(set)
    for event in events:
        if event.get("instrument_class") == "DERIVATIVE" and event.get("execType") == "Trade":
            tie_groups[(str(event.get("symbol", "")), str(event.get("transactTime", "")), str(event.get("timestamp", "")))].add(str(event.get("orderID", "")))
    cross_order_tie_count = sum(len(order_ids) > 1 for order_ids in tie_groups.values())
    return {
        "rows": rows,
        "chain_status_by_exec": chain_status_by_exec,
        "rank_by_exec": rank_by_exec,
        "multi_trade_group_count": len(rows),
        "unique_chain_group_count": sum(row["chain_status"] == "UNIQUE_CUMQTY_CHAIN" for row in rows),
        "ambiguous_group_count": sum(row["chain_status"] == "AMBIGUOUS" for row in rows),
        "cross_order_tie_count": cross_order_tie_count,
        "status": "PASS" if not cross_order_tie_count and not any(row["chain_status"] == "AMBIGUOUS" for row in rows) else "READY_WITH_AMBIGUOUS_CROSS_ORDER_TIES",
    }


def apply_execution_order_policy(events: Iterable[dict[str, Any]], audit: dict[str, Any], policy: str) -> list[dict[str, Any]]:
    copied = [copy(event) for event in events]
    ranks = audit.get("rank_by_exec", {})
    statuses = audit.get("chain_status_by_exec", {})
    for event in copied:
        exec_id = str(event.get("execID", ""))
        event["execution_order_policy"] = policy
        event["execution_order_chain_status"] = statuses.get(exec_id, "NOT_IN_MULTI_TRADE_GROUP")
        event["execution_order_rank"] = ranks.get(exec_id, 0)
    if policy == "SOURCE_ROW_STABLE":
        return copied
    if policy != "CUMQTY_WITHIN_ORDER":
        raise ValueError(f"unknown execution order policy: {policy}")
    return sorted(
        copied,
        key=lambda row: (
            row.get("_event_dt"),
            row.get("_timestamp_dt"),
            0 if row.get("execution_order_rank", 0) else 1,
            row.get("execution_order_rank", 0) if row.get("execution_order_rank", 0) else int(row.get("source_row_number") or 0),
            int(row.get("source_row_number") or 0),
        ),
    )


__all__ = ["apply_execution_order_policy", "audit_execution_order"]
