from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from .instrument_metadata import (
    build_instrument_temporal_audit,
    instrument_distribution,
    load_instruments,
    select_instrument,
)
from .io_utils import clean, iter_csv_dicts, parse_datetime, parse_int, read_csv_header
from .order_dimension import OrderDimensionResult


def load_settlement_evidence(path: Path) -> dict[tuple[str, str], dict[str, Any]]:
    if not path.is_file():
        return {}
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {
        (clean(item.get("symbol")).strip(), clean(item.get("execID")).strip()): item
        for item in payload.get("settlements", [])
        if clean(item.get("symbol")).strip() and clean(item.get("execID")).strip()
    }


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


def _base_event(
    line_number: int,
    row: dict[str, str],
    order_dimension: OrderDimensionResult,
    instruments: dict[str, list[dict[str, str]]],
    settlement_evidence: dict[tuple[str, str], dict[str, Any]],
) -> dict[str, Any]:
    timestamp = clean(row.get("timestamp", ""))
    transact_time = clean(row.get("transactTime", ""))
    timestamp_dt = parse_datetime(timestamp)
    transact_dt = parse_datetime(transact_time)
    event_dt = transact_dt or timestamp_dt
    symbol = clean(row.get("symbol", "")).strip()
    exec_id = clean(row.get("execID", "")).strip()
    instrument = select_instrument(instruments.get(symbol, []), event_dt)
    evidence = settlement_evidence.get((symbol, exec_id), {})
    instrument_temporal_status = "METADATA_MISSING"
    requires_historical_spec = True
    if instrument:
        listing_dt = parse_datetime(instrument.get("listing", ""))
        if listing_dt is not None and event_dt is not None and event_dt < listing_dt:
            instrument_temporal_status = "EXECUTION_BEFORE_CURRENT_LISTING"
        else:
            instrument_temporal_status = "TEMPORALLY_COVERED"
        requires_historical_spec = instrument_temporal_status != "TEMPORALLY_COVERED"
    if evidence and instrument_temporal_status == "EXECUTION_BEFORE_CURRENT_LISTING":
        instrument_temporal_status = "SYMBOL_REUSE_SUSPECTED"

    event = {
        "source_row_number": line_number,
        "event_time": event_dt.isoformat().replace("+00:00", "Z") if event_dt else "",
        "timestamp": timestamp,
        "transactTime": transact_time,
        "execID": exec_id,
        "execType": clean(row.get("execType", "")).strip(),
        "symbol": symbol,
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
        "instrument_typ": instrument.get("typ", ""),
        "instrument_class": instrument.get("instrument_class", "UNKNOWN"),
        "instrument_metadata_listing": instrument.get("listing", ""),
        "instrument_metadata_expiry": instrument.get("expiry", ""),
        "instrument_metadata_settle": instrument.get("settle", ""),
        "instrument_metadata_status": instrument.get("state", ""),
        "instrument_temporal_status": instrument_temporal_status,
        "requires_historical_spec": requires_historical_spec,
        "order_join_status": _join_status(row, order_dimension),
        "position_effect": "UNRESOLVED",
        "normalization_status": "ERROR",
        "normalization_reason": "",
        "signed_qty": 0,
        "signed_contract_qty": 0,
        "spot_base_qty_raw": 0,
        "affects_derivative_position": instrument.get("instrument_class", "UNKNOWN") == "DERIVATIVE",
        "settlement_status": "NOT_APPLICABLE",
        "settlement_reason": "",
        "settlement_resolution_method": "",
        "evidence_status": "OFFICIAL_EARLY_SETTLEMENT" if evidence else "NONE",
        "evidence_source_title": evidence.get("source_title", ""),
        "evidence_source_url": evidence.get("source_url", ""),
        "_settlement_evidence": evidence,
        "_event_dt": event_dt,
        "_timestamp_dt": timestamp_dt,
    }
    return event


def normalize_executions(
    execution_path: Path,
    order_dimension: OrderDimensionResult,
    instruments: dict[str, list[dict[str, str]]],
    settlement_evidence: dict[tuple[str, str], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    settlement_evidence = settlement_evidence or {}
    columns = read_csv_header(execution_path)
    events: list[dict[str, Any]] = []
    settlement_events: list[dict[str, Any]] = []
    exec_ids: set[str] = set()
    duplicate_exec_ids: list[str] = []
    type_counts: Counter[str] = Counter()
    join_counts: Counter[tuple[str, str]] = Counter()
    missing_order_by_type: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()
    instrument_typ_counts: Counter[str] = Counter()
    instrument_class_counts: Counter[str] = Counter()
    trade_class_counts: Counter[str] = Counter()
    unresolved: list[dict[str, Any]] = []

    for line_number, row in iter_csv_dicts(execution_path):
        event = _base_event(line_number, row, order_dimension, instruments, settlement_evidence)
        exec_id = event["execID"]
        if exec_id in exec_ids:
            duplicate_exec_ids.append(exec_id)
        exec_ids.add(exec_id)
        exec_type = event["execType"]
        type_counts[exec_type] += 1
        join_counts[(exec_type, event["order_join_status"])] += 1
        instrument_typ_counts[event["instrument_typ"] or "MISSING"] += 1
        instrument_class_counts[event["instrument_class"]] += 1
        if exec_type == "Trade":
            trade_class_counts[event["instrument_class"]] += 1
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
                signed_contract_qty=0,
                affects_derivative_position=event["instrument_class"] == "DERIVATIVE",
            )
        elif exec_type in {"Trade", "Settlement"}:
            if side not in {"Buy", "Sell"}:
                event.update(normalization_status="ERROR", normalization_reason="side must be Buy or Sell.", signed_qty=0, signed_contract_qty=0)
            elif qty is None or qty <= 0:
                event.update(normalization_status="ERROR", normalization_reason="lastQty must be a positive integer.", signed_qty=0, signed_contract_qty=0)
            elif exec_type == "Trade" and event["instrument_class"] == "SPOT":
                sign = 1 if side == "Buy" else -1
                event.update(
                    position_effect="SPOT_BALANCE_DELTA",
                    normalization_status="OK_SPOT_TRADE",
                    normalization_reason="Spot trade retained as a raw balance delta; it is excluded from derivative contract replay.",
                    signed_qty=0,
                    signed_contract_qty=0,
                    spot_base_qty_raw=sign * qty,
                    affects_derivative_position=False,
                )
            elif event["instrument_class"] != "DERIVATIVE":
                event.update(
                    position_effect="UNRESOLVED",
                    normalization_status="ERROR",
                    normalization_reason=f"Trade/Settlement instrument_class={event['instrument_class']!r} is not a derivative position.",
                    signed_qty=0,
                    signed_contract_qty=0,
                    affects_derivative_position=False,
                )
            elif exec_type == "Trade":
                sign = 1 if side == "Buy" else -1
                event.update(
                    position_effect="POSITION_DELTA",
                    normalization_status=_status_for_order_join(event["order_join_status"]),
                    normalization_reason="Derivative trade quantity signed from side; order join status is preserved.",
                    signed_qty=sign * qty,
                    signed_contract_qty=sign * qty,
                    affects_derivative_position=True,
                )
            else:
                has_expiry_evidence = bool(event["instrument_metadata_expiry"] or event["instrument_metadata_settle"] or event["_settlement_evidence"])
                if not has_expiry_evidence:
                    event.update(
                        normalization_status="UNRESOLVED",
                        normalization_reason="Settlement lacks expiry/settle metadata or configured historical evidence; position-close validation cannot start.",
                        settlement_status="UNRESOLVED",
                        settlement_reason="No current expiry/settle metadata or historical settlement evidence.",
                        signed_qty=0,
                        signed_contract_qty=0,
                    )
                else:
                    sign = 1 if side == "Buy" else -1
                    event.update(
                        position_effect="POSITION_DELTA",
                        normalization_status=_status_for_order_join(event["order_join_status"]),
                        normalization_reason="Settlement is pending position-close invariant validation; no PnL is calculated.",
                        signed_qty=sign * qty,
                        signed_contract_qty=sign * qty,
                        settlement_status="PENDING_POSITION_VALIDATION",
                        settlement_reason="Candidate settlement requires position_before/position_after validation during replay.",
                        affects_derivative_position=True,
                    )
        else:
            event.update(normalization_status="UNRESOLVED", normalization_reason=f"Unsupported execType={exec_type!r}.")

        if event["normalization_status"] in {"ERROR", "UNRESOLVED"}:
            unresolved.append(
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
        "instrument_typ_counts": dict(instrument_typ_counts),
        "instrument_class_counts": dict(instrument_class_counts),
        "trade_class_counts": dict(trade_class_counts),
        "instrument_distribution": instrument_distribution(events),
        "unresolved": unresolved,
    }


def assert_unique_exec_ids(normalized: dict[str, Any]) -> None:
    duplicates = normalized.get("duplicate_exec_ids", [])
    if duplicates:
        raise AssertionError(f"Duplicate execID values: {duplicates[:10]}")


__all__ = [
    "assert_unique_exec_ids",
    "build_instrument_temporal_audit",
    "load_instruments",
    "load_settlement_evidence",
    "normalize_executions",
]
