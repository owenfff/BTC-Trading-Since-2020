from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any


VALID_POSITION_STATUSES = {"OK", "OK_WITHOUT_ORDER_ID", "OK_WITH_UNMATCHED_ORDER"}


def classify_action(position_before: int, signed_qty: int, position_after: int) -> str:
    if signed_qty == 0 or position_after == position_before:
        return "NO_POSITION_CHANGE"
    if position_before == 0:
        return "OPEN_LONG" if position_after > 0 else "OPEN_SHORT"
    if position_before > 0:
        if position_after == 0:
            return "CLOSE_LONG"
        if position_after < 0:
            return "FLIP_LONG_TO_SHORT"
        return "ADD_LONG" if signed_qty > 0 else "REDUCE_LONG"
    if position_after == 0:
        return "CLOSE_SHORT"
    if position_after > 0:
        return "FLIP_SHORT_TO_LONG"
    return "ADD_SHORT" if signed_qty < 0 else "REDUCE_SHORT"


def replay_positions(events: list[dict[str, Any]]) -> dict[str, Any]:
    positions: dict[str, int] = defaultdict(int)
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "trade_event_count": 0,
            "funding_event_count": 0,
            "settlement_event_count": 0,
            "event_count": 0,
            "last_event_time": "",
            "has_unresolved": False,
        }
    )
    position_events: list[dict[str, Any]] = []
    action_counts: Counter[str] = Counter()

    for event in events:
        symbol = event.get("symbol", "")
        before = int(positions[symbol])
        status = event.get("normalization_status", "ERROR")
        signed_qty = int(event.get("signed_qty") or 0) if status in VALID_POSITION_STATUSES else 0
        after = before + signed_qty
        action = classify_action(before, signed_qty, after)
        crossed_zero = (before > 0 and after < 0) or (before < 0 and after > 0)
        positions[symbol] = after

        symbol_stats = stats[symbol]
        symbol_stats["event_count"] += 1
        symbol_stats["last_event_time"] = event.get("event_time", "")
        if event.get("execType") == "Trade":
            symbol_stats["trade_event_count"] += 1
        elif event.get("execType") == "Funding":
            symbol_stats["funding_event_count"] += 1
        elif event.get("execType") == "Settlement":
            symbol_stats["settlement_event_count"] += 1
        if status not in VALID_POSITION_STATUSES and event.get("execType") != "Funding":
            symbol_stats["has_unresolved"] = True

        row = {
            "event_time": event.get("event_time", ""),
            "source_row_number": event.get("source_row_number"),
            "symbol": symbol,
            "execID": event.get("execID", ""),
            "execType": event.get("execType", ""),
            "side": event.get("side", ""),
            "lastQty": event.get("lastQty"),
            "signed_qty": signed_qty,
            "position_before": before,
            "position_after": after,
            "action": action,
            "crossed_zero": crossed_zero,
            "lastPx": event.get("lastPx", ""),
            "orderID": event.get("orderID", ""),
            "order_join_status": event.get("order_join_status", ""),
            "normalization_status": status,
        }
        position_events.append(row)
        action_counts[action] += 1

    terminal_positions = []
    for symbol in sorted(stats):
        symbol_stats = stats[symbol]
        terminal_positions.append(
            {
                "symbol": symbol,
                "last_event_time": symbol_stats["last_event_time"],
                "reconstructed_position": int(positions[symbol]),
                "trade_event_count": symbol_stats["trade_event_count"],
                "funding_event_count": symbol_stats["funding_event_count"],
                "settlement_event_count": symbol_stats["settlement_event_count"],
                "event_count": symbol_stats["event_count"],
                "final_status": "WARNING" if symbol_stats["has_unresolved"] else "PASS",
            }
        )

    return {
        "position_events": position_events,
        "terminal_positions": terminal_positions,
        "action_counts": dict(action_counts),
    }
