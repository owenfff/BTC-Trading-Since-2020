from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from .io_utils import clean, iter_csv_dicts, parse_datetime, parse_int, read_csv_header
from .order_dimension import OrderDimensionResult


def load_instruments(path: Path) -> dict[str, dict[str, str]]:
    instruments: dict[str, dict[str, str]] = {}
    for _, row in iter_csv_dicts(path):
        symbol = clean(row.get("symbol", "")).strip()
        if symbol:
            instruments[symbol] = {
                field: clean(row.get(field, ""))
                for field in ("symbol", "state", "typ", "expiry", "settle", "settlCurrency", "positionCurrency", "isInverse", "isQuanto", "multiplier")
            }
    return instruments


def _join_status(row: dict[str, str], order_dimension: OrderDimensionResult) -> str:
    order_id = clean(row.get("orderID", "")).strip()
    exec_type = clean(row.get("execType", "")).strip()
    if not order_id:
        return "NOT_APPLICABLE" if exec_type in {"Funding", "Settlement"} else "NO_ORDER_ID"
    return "MATCHED" if order_id in order_dimension.dimension else "UNMATCHED"


def _status_for_order_join(join_status: str) -> str:
    if join_status == "NO_ORDER_ID":
        return "OK_WITHOUT_ORDER_ID"
    if join_status == "UNMATCHED":
        return "OK_WITH_UNMATCHED_ORDER"
    return "OK"


def _base_event(line_number: int, row: dict[str, str], order_dimension: OrderDimensionResult) -> dict[str, Any]:
    timestamp = clean(row.get("timestamp", ""))
    transact_time = clean(row.get("transactTime", ""))
    timestamp_dt = parse_datetime(timestamp)
    transact_dt = parse_datetime(transact_time)
    event_dt = transact_dt or timestamp_dt
    join_status = _join_status(row, order_dimension)
    event = {
        "source_row_number": line_number,
        "event_time": event_dt.isoformat().replace("+00:00", "Z") if event_dt else "",
        "timestamp": timestamp,
        "transactTime": transact_time,
        "execID": clean(row.get("execID", "")).strip(),
        "execType": clean(row.get("execType", "")).strip(),
        "symbol": clean(row.get("symbol", "")).strip(),
        "side": clean(row.get("side", "")).strip(),
        "orderQty": parse_int(row.get("orderQty", "")),
        "lastQty": parse_int(row.get("lastQty", "")),
        "cumQty": parse_int(row.get("cumQty", "")),
        "leavesQty": parse_int(row.get("leavesQty", "")),
        "price": clean(row.get("price", "")),
        "lastPx": clean(row.get("lastPx", "")),
        "avgPx": clean(row.get("avgPx", "")),
        "currency": clean(row.get("currency", "")).strip(),
        "settlCurrency": clean(row.get("settlCurrency", "")).strip(),
        "execCost": clean(row.get("execCost", "")),
        "execComm": clean(row.get("execComm", "")),
        "realisedPnl": clean(row.get("realisedPnl", "")),
        "homeNotional": clean(row.get("homeNotional", "")),
        "foreignNotional": clean(row.get("foreignNotional", "")),
        "orderID": clean(row.get("orderID", "")).strip(),
        "ordType": clean(row.get("ordType", "")).strip(),
        "ordStatus": clean(row.get("ordStatus", "")).strip(),
        "order_join_status": join_status,
        "position_effect": "UNRESOLVED",
        "normalization_status": "ERROR",
        "normalization_reason": "",
        "signed_qty": 0,
        "settlement_status": "NOT_APPLICABLE",
        "settlement_reason": "",
        "_event_dt": event_dt,
        "_timestamp_dt": timestamp_dt,
    }
    return event


def normalize_executions(
    execution_path: Path,
    order_dimension: OrderDimensionResult,
    instruments: dict[str, dict[str, str]],
) -> dict[str, Any]:
    columns = read_csv_header(execution_path)
    events: list[dict[str, Any]] = []
    settlement_events: list[dict[str, Any]] = []
    exec_ids: set[str] = set()
    duplicate_exec_ids: list[str] = []
    type_counts: Counter[str] = Counter()
    join_counts: Counter[tuple[str, str]] = Counter()
    missing_order_by_type: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    unresolved: list[dict[str, Any]] = []

    for line_number, row in iter_csv_dicts(execution_path):
        event = _base_event(line_number, row, order_dimension)
        exec_id = event["execID"]
        if exec_id in exec_ids:
            duplicate_exec_ids.append(exec_id)
        exec_ids.add(exec_id)
        exec_type = event["execType"]
        type_counts[exec_type] += 1
        join_counts[(exec_type, event["order_join_status"])] += 1
        if not event["orderID"]:
            missing_order_by_type[exec_type] += 1

        qty = event["lastQty"]
        side = event["side"]
        if exec_type == "Funding":
            event.update(
                position_effect="CASHFLOW_ONLY",
                normalization_status="OK",
                normalization_reason="Funding is retained but does not change contract quantity.",
                signed_qty=0,
            )
        elif exec_type in {"Trade", "Settlement"}:
            if side not in {"Buy", "Sell"}:
                event.update(normalization_status="ERROR", normalization_reason="side must be Buy or Sell.")
            elif qty is None or qty <= 0:
                event.update(normalization_status="ERROR", normalization_reason="lastQty must be a positive integer.")
            elif exec_type == "Trade":
                sign = 1 if side == "Buy" else -1
                event.update(
                    position_effect="POSITION_DELTA",
                    normalization_status=_status_for_order_join(event["order_join_status"]),
                    normalization_reason="Trade quantity signed from side; order join status is preserved.",
                    signed_qty=sign * qty,
                )
            else:
                instrument = instruments.get(event["symbol"])
                is_expiring_instrument = bool(instrument and (instrument.get("expiry") or instrument.get("settle")))
                if not is_expiring_instrument:
                    event.update(
                        normalization_status="UNRESOLVED",
                        normalization_reason="Settlement row lacks a verifiable expiring instrument record.",
                        settlement_status="UNRESOLVED",
                        settlement_reason="Instrument metadata does not confirm an expiring contract.",
                    )
                else:
                    sign = 1 if side == "Buy" else -1
                    event.update(
                        position_effect="POSITION_DELTA",
                        normalization_status=_status_for_order_join(event["order_join_status"]),
                        normalization_reason="Settlement closes the expiring contract using the row's side and lastQty; no PnL is calculated.",
                        signed_qty=sign * qty,
                        settlement_status="APPLIED_POSITION_DELTA",
                        settlement_reason="Expiring instrument metadata and positive side/lastQty support a contract-quantity close.",
                    )
        else:
            event.update(normalization_status="UNRESOLVED", normalization_reason=f"Unsupported execType={exec_type!r}.")

        if event["normalization_status"] in {"ERROR", "UNRESOLVED"}:
            unresolved.append(
                {
                    key: event.get(key)
                    for key in ("source_row_number", "execID", "execType", "symbol", "side", "lastQty", "orderID", "normalization_status", "normalization_reason")
                }
            )
        status_counts[event["normalization_status"]] += 1
        if exec_type == "Settlement":
            settlement_events.append(event)
        events.append(event)

    events.sort(
        key=lambda event: (
            event["_event_dt"] or parse_datetime("9999-12-31T23:59:59.999999Z"),
            event["_timestamp_dt"] or parse_datetime("9999-12-31T23:59:59.999999Z"),
            event["source_row_number"],
            event["execID"],
        )
    )
    return {
        "events": events,
        "settlement_events": settlement_events,
        "columns": columns,
        "raw_rows": len(events),
        "exec_ids": exec_ids,
        "duplicate_exec_ids": duplicate_exec_ids,
        "type_counts": dict(type_counts),
        "join_counts": {f"{exec_type}|{status}": count for (exec_type, status), count in sorted(join_counts.items())},
        "missing_order_by_type": dict(missing_order_by_type),
        "normalization_status_counts": dict(status_counts),
        "unresolved": unresolved,
    }


def assert_unique_exec_ids(normalized: dict[str, Any]) -> None:
    duplicates = normalized.get("duplicate_exec_ids", [])
    if duplicates:
        raise AssertionError(f"Duplicate execID values: {duplicates[:10]}")
