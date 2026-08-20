from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from bitmex_replay.io_utils import parse_datetime

from .confidence import ordering_confidence


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _time_key(row: dict[str, Any]) -> tuple[Any, Any, int, str]:
    return (
        parse_datetime(row.get("event_time")) or parse_datetime("9999-12-31T23:59:59.999999Z"),
        parse_datetime(row.get("timestamp")) or parse_datetime("9999-12-31T23:59:59.999999Z"),
        _int(row.get("source_row_number")),
        str(row.get("execID", "")),
    )


def build_execution_batches(
    events: Iterable[dict[str, Any]],
    chain_status_by_exec: dict[str, str] | None = None,
    max_gap_seconds: int = 300,
) -> tuple[list[dict[str, Any]], dict[str, str]]:
    """Group fills into auditable batches without pretending batches are decisions.

    A batch is scoped to one symbol/orderID and is split only on a time gap larger
    than ``max_gap_seconds`` or an explicit cumulative-quantity reset.
    """

    chain_status_by_exec = chain_status_by_exec or {}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("execType") != "Trade" or event.get("instrument_class") != "DERIVATIVE":
            continue
        key = (str(event.get("symbol", "")), str(event.get("orderID", "")) or f"UNMATCHED:{event.get('execID', '')}")
        groups[key].append(event)

    batches: list[dict[str, Any]] = []
    exec_to_batch: dict[str, str] = {}
    for (symbol, order_key), members in sorted(groups.items()):
        members.sort(key=_time_key)
        current: list[dict[str, Any]] = []
        previous_time = None
        previous_cum = None
        batch_number = 0

        def flush(reason: str = "") -> None:
            nonlocal current, batch_number
            if not current:
                return
            batch_number += 1
            batch_id = f"{symbol}-{order_key}-B{batch_number:04d}"
            qty = sum(_int(row.get("lastQty")) for row in current)
            signed_qty = sum(_int(row.get("signed_contract_qty", row.get("signed_qty"))) for row in current)
            prices = []
            price_qty = Decimal(0)
            qty_decimal = Decimal(0)
            for row in current:
                price = _decimal(row.get("lastPx"))
                row_qty = Decimal(abs(_int(row.get("lastQty"))))
                if price is not None and row_qty:
                    price_qty += price * row_qty
                    qty_decimal += row_qty
            if qty_decimal:
                prices.append(format(price_qty / qty_decimal, "f"))
            statuses = [chain_status_by_exec.get(str(row.get("execID", "")), "NOT_IN_MULTI_TRADE_GROUP") for row in current]
            chain_status = "AMBIGUOUS" if "AMBIGUOUS" in statuses else ("UNIQUE_CUMQTY_CHAIN" if "UNIQUE_CUMQTY_CHAIN" in statuses else "NOT_IN_MULTI_TRADE_GROUP")
            for row in current:
                exec_to_batch[str(row.get("execID", ""))] = batch_id
            batches.append({
                "execution_batch_id": batch_id,
                "order_episode_key": order_key,
                "symbol": symbol,
                "is_btc_first_scope": symbol == "XBTUSD",
                "orderID": current[0].get("orderID", ""),
                "first_event_time": current[0].get("event_time", ""),
                "last_event_time": current[-1].get("event_time", ""),
                "execution_count": len(current),
                "execIDs": ",".join(str(row.get("execID", "")) for row in current),
                "filled_qty": qty,
                "signed_contract_qty": signed_qty,
                "weighted_execution_price": prices[0] if prices else "",
                "chain_status": chain_status,
                "ordering_confidence": ordering_confidence(chain_status),
                "batch_break_reason": reason,
            })
            current = []

        for event in members:
            event_time = parse_datetime(event.get("event_time"))
            cum_qty = _int(event.get("cumQty"), -1)
            gap = (event_time - previous_time).total_seconds() if event_time and previous_time else 0
            reset = previous_cum is not None and cum_qty >= 0 and cum_qty < previous_cum
            if current and (gap > max_gap_seconds or reset):
                flush("TIME_GAP" if gap > max_gap_seconds else "CUMQTY_RESET")
            current.append(event)
            previous_time = event_time
            previous_cum = cum_qty if cum_qty >= 0 else previous_cum
        flush("END_OF_ORDER")
    batches.sort(key=lambda row: (parse_datetime(row.get("first_event_time")) or parse_datetime("9999-12-31T23:59:59.999999Z"), row["execution_batch_id"]))
    return batches, exec_to_batch


__all__ = ["build_execution_batches"]
