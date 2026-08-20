from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from bitmex_replay.io_utils import parse_datetime

from .confidence import (
    accounting_confidence,
    combine_confidences,
    ordering_confidence,
    overall_confidence,
    price_confidence,
    wallet_confidence,
)


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


def _format(value: Decimal | None) -> str:
    return format(value or Decimal(0), "f")


def _time_key(row: dict[str, Any]) -> tuple[Any, Any, int, str]:
    return (
        parse_datetime(row.get("event_time")) or parse_datetime("9999-12-31T23:59:59.999999Z"),
        parse_datetime(row.get("timestamp")) or parse_datetime("9999-12-31T23:59:59.999999Z"),
        _int(row.get("source_row_number")),
        str(row.get("execID", "")),
    )


def _new_cycle(symbol: str, sequence: int, event: dict[str, Any], initial_qty: int, flip_origin: str = "NONE") -> dict[str, Any]:
    direction = "LONG" if initial_qty > 0 else "SHORT"
    return {
        "cycle_id": f"{symbol}-C{sequence:04d}",
        "symbol": symbol,
        "is_btc_first_scope": symbol == "XBTUSD",
        "direction": direction,
        "open_time": event.get("event_time", ""),
        "close_time": "",
        "duration_seconds": "",
        "initial_qty": initial_qty,
        "maximum_abs_qty": abs(initial_qty),
        "terminal_qty": initial_qty,
        "opening_exec_count": 1,
        "add_count": 0,
        "reduce_count": 0,
        "flip_origin": flip_origin,
        "close_type": "",
        "opening_execID": event.get("execID", ""),
        "closing_execID": "",
        "cycle_event_count": 0,
        "funding_event_count": 0,
        "gross_pnl_analytical": Decimal(0),
        "reported_pnl_total": Decimal(0),
        "reported_pnl_count": 0,
        "fee": Decimal(0),
        "funding": Decimal(0),
        "wallet_net_candidate": None,
        "wallet_net_status": "AGGREGATE_ONLY_NOT_ALIGNED",
        "ordering_values": [],
        "action_values": [],
        "accounting_values": [],
        "price_values": [],
        "wallet_values": [wallet_confidence()],
        "pnl_currency": "",
        "accounting_position_cycle_ids": set(),
    }


def _assign_event(
    cycle: dict[str, Any],
    event: dict[str, Any],
    valuation: dict[str, Any],
    accounting: dict[str, Any],
    chain_status: str,
    *,
    include_financials: bool = True,
) -> None:
    cycle["cycle_event_count"] += 1
    cycle["terminal_qty"] = _int(event.get("position_after"), cycle["terminal_qty"])
    cycle["maximum_abs_qty"] = max(cycle["maximum_abs_qty"], abs(cycle["terminal_qty"]))
    action = str(event.get("action", ""))
    if action.startswith("ADD_"):
        cycle["add_count"] += 1
    if action.startswith("REDUCE_"):
        cycle["reduce_count"] += 1
    cycle["ordering_values"].append(ordering_confidence(chain_status))
    cycle["action_values"].append("HIGH" if action else "LOW")
    cycle["accounting_values"].append(accounting_confidence(str(accounting.get("accounting_status", "")), str(valuation.get("normalization_status", ""))))
    cycle["price_values"].append(price_confidence(str(valuation.get("canonical_price_status", ""))))
    cycle["accounting_position_cycle_ids"].add(str(accounting.get("position_cycle_id", "")))
    if valuation.get("settlement_currency"):
        cycle["pnl_currency"] = valuation.get("settlement_currency")
    if not include_financials:
        return
    cycle["fee"] += _decimal(valuation.get("execComm_raw")) or Decimal(0)
    reported = _decimal(accounting.get("reported_realisedPnl_raw", valuation.get("realisedPnl_raw")))
    if reported is not None:
        cycle["reported_pnl_total"] += reported
        cycle["reported_pnl_count"] += 1
    cycle["gross_pnl_analytical"] += _decimal(accounting.get("gross_realised_pnl_exact_raw")) or Decimal(0)


def _finalize(cycle: dict[str, Any], event: dict[str, Any], close_type: str) -> dict[str, Any]:
    cycle["close_time"] = event.get("event_time", "")
    cycle["closing_execID"] = event.get("execID", "")
    cycle["close_type"] = close_type
    opened = parse_datetime(cycle.get("open_time"))
    closed = parse_datetime(cycle.get("close_time"))
    if opened and closed:
        cycle["duration_seconds"] = (closed - opened).total_seconds()
    cycle["gross_pnl_analytical"] = _format(cycle["gross_pnl_analytical"])
    cycle["reported_pnl_available"] = _format(cycle["reported_pnl_total"]) if cycle["reported_pnl_count"] else None
    cycle["fee"] = _format(cycle["fee"])
    cycle["funding"] = _format(cycle["funding"])
    cycle["ordering_confidence"] = combine_confidences(cycle.pop("ordering_values"))
    cycle["action_confidence"] = combine_confidences(cycle.pop("action_values"))
    cycle["accounting_confidence"] = combine_confidences(cycle.pop("accounting_values"))
    cycle["price_confidence"] = combine_confidences(cycle.pop("price_values"))
    cycle["wallet_confidence"] = combine_confidences("MEDIUM" if value == "AGGREGATE_ONLY" else value for value in cycle.pop("wallet_values"))
    cycle["overall_confidence"] = overall_confidence(
        cycle["ordering_confidence"], cycle["action_confidence"], cycle["accounting_confidence"], cycle["price_confidence"], cycle["wallet_confidence"]
    )
    cycle["confidence_status"] = cycle["overall_confidence"]
    cycle["accounting_position_cycle_ids"] = ",".join(sorted(cycle.pop("accounting_position_cycle_ids")))
    cycle["strategy_fidelity"] = "BEHAVIORAL_APPROXIMATION"
    return cycle


def build_trade_cycles(
    events: Iterable[dict[str, Any]],
    valuation_by_exec: dict[str, dict[str, Any]],
    accounting_by_exec: dict[str, dict[str, Any]],
    chain_status_by_exec: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Reconstruct zero-to-zero position cycles per symbol, including flips."""

    chain_status_by_exec = chain_status_by_exec or {}
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("instrument_class") == "DERIVATIVE":
            by_symbol[str(event.get("symbol", ""))].append(event)
    output: list[dict[str, Any]] = []
    for symbol, symbol_events in sorted(by_symbol.items()):
        symbol_events.sort(key=_time_key)
        active: dict[str, Any] | None = None
        sequence = 0

        def start(event: dict[str, Any], initial_qty: int, origin: str = "NONE") -> dict[str, Any]:
            nonlocal sequence
            sequence += 1
            return _new_cycle(symbol, sequence, event, initial_qty, origin)

        for event in symbol_events:
            exec_id = str(event.get("execID", ""))
            valuation = valuation_by_exec.get(exec_id, {})
            accounting = accounting_by_exec.get(exec_id, {})
            chain_status = chain_status_by_exec.get(exec_id, "NOT_IN_MULTI_TRADE_GROUP")
            exec_type = str(event.get("execType", ""))
            if exec_type == "Funding":
                if active is not None:
                    active["funding_event_count"] += 1
                    active["funding"] += _decimal(valuation.get("execComm_raw")) or Decimal(0)
                continue
            if exec_type not in {"Trade", "Settlement"}:
                continue
            before = _int(event.get("position_before"))
            after = _int(event.get("position_after"))
            if active is None and before != 0:
                active = start(event, before, "PREEXISTING_POSITION")
            if active is None and after != 0:
                active = start(event, after)
            if active is None:
                continue
            if before != 0 and after != 0 and (before > 0) != (after > 0):
                _assign_event(active, event, valuation, accounting, chain_status)
                old = active
                output.append(_finalize(old, event, "FLIP"))
                active = start(event, after, old["cycle_id"])
                # The flip fill is an opening observation for the new cycle, but
                # its fee/PnL is retained on the closing cycle to avoid double sum.
                _assign_event(active, event, valuation, accounting, chain_status, include_financials=False)
                continue
            _assign_event(active, event, valuation, accounting, chain_status)
            if before == 0 and after != 0:
                active["initial_qty"] = after
            if after == 0:
                close_type = "SETTLEMENT" if exec_type == "Settlement" else "FULL_CLOSE"
                output.append(_finalize(active, event, close_type))
                active = None
        if active is not None:
            last_event = symbol_events[-1]
            output.append(_finalize(active, last_event, "OPEN_AT_DATA_END"))
    output.sort(key=lambda row: (parse_datetime(row.get("open_time")) or parse_datetime("9999-12-31T23:59:59.999999Z"), row.get("cycle_id", "")))
    return output


__all__ = ["build_trade_cycles"]
