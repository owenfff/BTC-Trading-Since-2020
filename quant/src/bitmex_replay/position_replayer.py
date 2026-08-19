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


def _mark_settlement_error(event: dict[str, Any], reason: str) -> None:
    event.update(
        normalization_status="ERROR",
        normalization_reason=reason,
        settlement_status="ERROR",
        settlement_reason=reason,
        signed_qty=0,
        signed_contract_qty=0,
        position_effect="UNRESOLVED",
    )


def _validate_settlement(event: dict[str, Any], position_before: int) -> tuple[int, bool]:
    signed_qty = int(event.get("signed_contract_qty") or event.get("signed_qty") or 0)
    qty = event.get("lastQty")
    side = event.get("side")
    if event.get("settlement_status") != "PENDING_POSITION_VALIDATION":
        return 0, False
    if position_before == 0:
        _mark_settlement_error(event, "Settlement would act on zero derivative position; close invariant failed.")
        return 0, False
    expected_side = "Sell" if position_before > 0 else "Buy"
    if side != expected_side:
        _mark_settlement_error(event, f"Settlement side {side!r} does not close position_before={position_before}.")
        return 0, False
    if qty is None or abs(int(qty)) != abs(position_before):
        _mark_settlement_error(event, f"Settlement lastQty={qty!r} does not equal abs(position_before)={abs(position_before)}.")
        return 0, False
    if signed_qty != -position_before or position_before + signed_qty != 0:
        _mark_settlement_error(event, "Settlement signed quantity does not fully close the current derivative position.")
        return 0, False
    if event.get("evidence_status") == "OFFICIAL_EARLY_SETTLEMENT":
        method = "OFFICIAL_EARLY_SETTLEMENT_AND_POSITION_CLOSE_INVARIANT"
        evidence_status = "OFFICIAL_EARLY_SETTLEMENT"
    else:
        method = "INSTRUMENT_METADATA_AND_POSITION_CLOSE_INVARIANT"
        evidence_status = "INSTRUMENT_METADATA_CLOSE_INVARIANT"
    event.update(
        settlement_status="APPLIED_POSITION_DELTA",
        settlement_reason="Settlement side and quantity exactly close the pre-settlement derivative position.",
        settlement_resolution_method=method,
        evidence_status=evidence_status,
        normalization_reason="Settlement validated against position_before/position_after; no PnL is calculated.",
        position_effect="POSITION_DELTA",
    )
    return signed_qty, True


def _spot_summary(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("instrument_class") != "SPOT" or event.get("execType") != "Trade":
            continue
        symbol = str(event.get("symbol", ""))
        row = grouped.setdefault(
            symbol,
            {
                "symbol": symbol,
                "instrument_typ": event.get("instrument_typ", ""),
                "trade_count": 0,
                "buy_raw_qty": 0,
                "sell_raw_qty": 0,
                "net_base_qty_raw": 0,
                "currency": event.get("currency", ""),
                "first_event_time": event.get("event_time", ""),
                "last_event_time": event.get("event_time", ""),
                "note": "Raw spot trade quantity only; no asset-unit or wallet-balance standardization in M0-02A.1.",
            },
        )
        qty = int(event.get("lastQty") or 0)
        row["trade_count"] += 1
        if event.get("side") == "Buy":
            row["buy_raw_qty"] += qty
            row["net_base_qty_raw"] += qty
        elif event.get("side") == "Sell":
            row["sell_raw_qty"] += qty
            row["net_base_qty_raw"] -= qty
        row["first_event_time"] = min(row["first_event_time"], event.get("event_time", ""))
        row["last_event_time"] = max(row["last_event_time"], event.get("event_time", ""))
    return [grouped[symbol] for symbol in sorted(grouped)]


def replay_positions(events: list[dict[str, Any]]) -> dict[str, Any]:
    positions: dict[str, int] = defaultdict(int)
    stats: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "instrument_typ": "",
            "instrument_class": "UNKNOWN",
            "trade_event_count": 0,
            "funding_event_count": 0,
            "settlement_event_count": 0,
            "event_count": 0,
            "last_event_time": "",
            "has_unresolved": False,
            "affects_derivative_position": False,
        }
    )
    position_events: list[dict[str, Any]] = []
    action_counts: Counter[str] = Counter()

    for event in events:
        symbol = str(event.get("symbol", ""))
        instrument_class = event.get("instrument_class", "UNKNOWN")
        affects_derivative = instrument_class == "DERIVATIVE" and bool(event.get("affects_derivative_position"))
        before = int(positions[symbol]) if affects_derivative else 0
        signed_qty = 0
        status = event.get("normalization_status", "ERROR")
        if affects_derivative and status in VALID_POSITION_STATUSES:
            signed_qty = int(event.get("signed_contract_qty") or event.get("signed_qty") or 0)
        if affects_derivative and event.get("execType") == "Settlement":
            signed_qty, applied = _validate_settlement(event, before)
            if not applied:
                signed_qty = 0
            status = event.get("normalization_status", status)
        after = before + signed_qty
        action = classify_action(before, signed_qty, after)
        crossed_zero = (before > 0 and after < 0) or (before < 0 and after > 0)
        if affects_derivative:
            positions[symbol] = after

        symbol_stats = stats[symbol]
        symbol_stats["instrument_typ"] = event.get("instrument_typ", symbol_stats["instrument_typ"])
        symbol_stats["instrument_class"] = instrument_class
        symbol_stats["event_count"] += 1
        symbol_stats["last_event_time"] = event.get("event_time", "")
        symbol_stats["affects_derivative_position"] = symbol_stats["affects_derivative_position"] or affects_derivative
        if event.get("execType") == "Trade":
            symbol_stats["trade_event_count"] += 1
        elif event.get("execType") == "Funding":
            symbol_stats["funding_event_count"] += 1
        elif event.get("execType") == "Settlement":
            symbol_stats["settlement_event_count"] += 1
        if affects_derivative and status not in VALID_POSITION_STATUSES:
            symbol_stats["has_unresolved"] = True

        event.update(
            derivative_position_before=before,
            derivative_position_after=after,
            position_before=before,
            position_after=after,
            action=action,
            crossed_zero=crossed_zero,
        )
        position_events.append(
            {
                "event_time": event.get("event_time", ""),
                "source_row_number": event.get("source_row_number"),
                "symbol": symbol,
                "execID": event.get("execID", ""),
                "execType": event.get("execType", ""),
                "side": event.get("side", ""),
                "lastQty": event.get("lastQty"),
                "signed_qty": signed_qty,
                "signed_contract_qty": signed_qty,
                "position_before": before,
                "position_after": after,
                "action": action,
                "crossed_zero": crossed_zero,
                "lastPx": event.get("lastPx", ""),
                "orderID": event.get("orderID", ""),
                "order_join_status": event.get("order_join_status", ""),
                "normalization_status": status,
                "instrument_typ": event.get("instrument_typ", ""),
                "instrument_class": instrument_class,
                "affects_derivative_position": affects_derivative,
                "position_effect": event.get("position_effect", ""),
                "settlement_status": event.get("settlement_status", "NOT_APPLICABLE"),
                "settlement_resolution_method": event.get("settlement_resolution_method", ""),
                "evidence_status": event.get("evidence_status", "NONE"),
            }
        )
        action_counts[action] += 1

    terminal_positions = []
    for symbol in sorted(stats):
        symbol_stats = stats[symbol]
        terminal_positions.append(
            {
                "symbol": symbol,
                "instrument_typ": symbol_stats["instrument_typ"],
                "instrument_class": symbol_stats["instrument_class"],
                "affects_derivative_position": symbol_stats["affects_derivative_position"],
                "last_event_time": symbol_stats["last_event_time"],
                "reconstructed_position": int(positions[symbol]) if symbol_stats["instrument_class"] == "DERIVATIVE" else 0,
                "trade_event_count": symbol_stats["trade_event_count"],
                "funding_event_count": symbol_stats["funding_event_count"],
                "settlement_event_count": symbol_stats["settlement_event_count"],
                "event_count": symbol_stats["event_count"],
                "final_status": "WARNING" if symbol_stats["has_unresolved"] else "PASS",
            }
        )

    settlement_events = [event for event in events if event.get("execType") == "Settlement"]
    settlement_status_counts = Counter(event.get("settlement_status", "") for event in settlement_events)
    derivative_errors = [
        event
        for event in events
        if event.get("instrument_class") == "DERIVATIVE" and event.get("normalization_status") in {"ERROR", "UNRESOLVED"}
    ]
    replay_status = "PASS" if not derivative_errors and settlement_status_counts.get("APPLIED_POSITION_DELTA", 0) == len(settlement_events) else "BLOCKED"
    return {
        "position_events": position_events,
        "terminal_positions": terminal_positions,
        "terminal_derivative_positions": [row for row in terminal_positions if row["instrument_class"] == "DERIVATIVE"],
        "spot_execution_summary": _spot_summary(events),
        "action_counts": dict(action_counts),
        "settlement_status_counts": dict(settlement_status_counts),
        "derivative_errors": derivative_errors,
        "position_replay_status": replay_status,
    }
