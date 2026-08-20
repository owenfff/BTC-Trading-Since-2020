from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from bitmex_replay.io_utils import parse_datetime
from bitmex_replay.position_replayer import classify_action

from .confidence import (
    accounting_confidence,
    action_confidence,
    combine_confidences,
    ordering_confidence,
    overall_confidence,
    price_confidence,
    wallet_confidence,
)


def _decimal(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return result if result.is_finite() else None


def _int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _time_key(row: dict[str, Any]) -> tuple[Any, Any, int, str]:
    return (
        parse_datetime(row.get("event_time")) or parse_datetime("9999-12-31T23:59:59.999999Z"),
        parse_datetime(row.get("timestamp")) or parse_datetime("9999-12-31T23:59:59.999999Z"),
        _int(row.get("source_row_number")),
        str(row.get("execID", "")),
    )


def _first_nonempty(rows: list[dict[str, Any]], field: str, default: str = "") -> str:
    for row in rows:
        value = row.get(field)
        if value not in (None, ""):
            return str(value)
    return default


def _join_values(rows: list[dict[str, Any]], field: str) -> str:
    return ",".join(sorted({str(row.get(field, "")) for row in rows if row.get(field) not in (None, "")}))


def _selected_aux(
    event: dict[str, Any],
    valuation_by_exec: dict[str, dict[str, Any]],
    accounting_by_exec: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], dict[str, Any]]:
    exec_id = str(event.get("execID", ""))
    return valuation_by_exec.get(exec_id, {}), accounting_by_exec.get(exec_id, {})


def _event_confidences(
    event: dict[str, Any],
    valuation: dict[str, Any],
    accounting: dict[str, Any],
    chain_status: str,
) -> dict[str, str]:
    action = str(event.get("action", "UNRESOLVED"))
    ordering = ordering_confidence(chain_status)
    action_value = action_confidence(
        str(event.get("normalization_status", "")),
        str(event.get("order_join_status", "")),
        action,
    )
    accounting_value = accounting_confidence(
        str(accounting.get("accounting_status", "")),
        str(valuation.get("normalization_status", event.get("normalization_status", ""))),
    )
    price_value = price_confidence(str(valuation.get("canonical_price_status", "")))
    wallet_value = wallet_confidence()
    return {
        "ordering_confidence": ordering,
        "action_confidence": action_value,
        "accounting_confidence": accounting_value,
        "price_confidence": price_value,
        "wallet_confidence": wallet_value,
        "overall_confidence": overall_confidence(ordering, action_value, accounting_value, price_value, wallet_value),
    }


def build_trade_actions(
    events: Iterable[dict[str, Any]],
    valuation_by_exec: dict[str, dict[str, Any]],
    accounting_by_exec: dict[str, dict[str, Any]],
    chain_status_by_exec: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Build one compact action row per derivative Trade without changing raw events."""

    chain_status_by_exec = chain_status_by_exec or {}
    actions: list[dict[str, Any]] = []
    for event in events:
        if event.get("execType") != "Trade" or event.get("instrument_class") != "DERIVATIVE":
            continue
        valuation, accounting = _selected_aux(event, valuation_by_exec, accounting_by_exec)
        exec_id = str(event.get("execID", ""))
        chain_status = chain_status_by_exec.get(exec_id, "NOT_IN_MULTI_TRADE_GROUP")
        confidence = _event_confidences(event, valuation, accounting, chain_status)
        row = {
            "trade_action_id": exec_id,
            "event_time": event.get("event_time", ""),
            "symbol": event.get("symbol", ""),
            "is_btc_first_scope": event.get("symbol") == "XBTUSD",
            "execID": exec_id,
            "orderID": event.get("orderID", ""),
            "side": event.get("side", ""),
            "lastQty": event.get("lastQty"),
            "signed_contract_qty": event.get("signed_contract_qty", event.get("signed_qty", 0)),
            "position_before": event.get("position_before", 0),
            "position_after": event.get("position_after", 0),
            "action": event.get("action", "UNRESOLVED"),
            "crossed_zero": bool(event.get("crossed_zero")),
            "position_cycle_id": accounting.get("position_cycle_id", ""),
            "canonical_execution_price": valuation.get("canonical_execution_price", event.get("lastPx", "")),
            "canonical_price_status": valuation.get("canonical_price_status", ""),
            "execCost_raw": valuation.get("execCost_raw", ""),
            "execComm_raw": valuation.get("execComm_raw", ""),
            "reported_realisedPnl_raw": valuation.get("realisedPnl_raw", accounting.get("reported_realisedPnl_raw", "")),
            "gross_realised_pnl_exact_raw": accounting.get("gross_realised_pnl_exact_raw", ""),
            "normalization_status": valuation.get("normalization_status", event.get("normalization_status", "")),
            "order_join_status": event.get("order_join_status", ""),
            "execution_order_chain_status": chain_status,
            "execution_order_rank": event.get("execution_order_rank", 0),
            "accounting_eligibility": accounting.get("accounting_eligibility", ""),
            "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
            **confidence,
        }
        actions.append(row)
    return sorted(actions, key=lambda row: (parse_datetime(row.get("event_time")) or parse_datetime("9999-12-31T23:59:59.999999Z"), _int(row.get("source_row_number")), str(row.get("execID", ""))))


def build_order_episodes(
    events: Iterable[dict[str, Any]],
    order_dimension: Any,
    valuation_by_exec: dict[str, dict[str, Any]],
    accounting_by_exec: dict[str, dict[str, Any]],
    chain_status_by_exec: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Aggregate raw derivative fills into one row per symbol/order lifecycle."""

    chain_status_by_exec = chain_status_by_exec or {}
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for event in events:
        if event.get("execType") != "Trade" or event.get("instrument_class") != "DERIVATIVE":
            continue
        symbol = str(event.get("symbol", ""))
        order_id = str(event.get("orderID", ""))
        key = (symbol, order_id or f"UNMATCHED:{event.get('execID', '')}")
        groups[key].append(event)

    result: list[dict[str, Any]] = []
    dimensions = getattr(order_dimension, "dimension", {})
    for (symbol, episode_key), members in sorted(groups.items()):
        members.sort(key=_time_key)
        first = members[0]
        last = members[-1]
        order_id = str(first.get("orderID", ""))
        representative = dimensions.get(order_id, {}) if order_id else {}
        signed_total = sum(_int(row.get("signed_contract_qty", row.get("signed_qty"))) for row in members)
        first_before = _int(first.get("position_before"))
        local_after = first_before + signed_total
        action = classify_action(first_before, signed_total, local_after)
        chain_statuses = [chain_status_by_exec.get(str(row.get("execID", "")), "NOT_IN_MULTI_TRADE_GROUP") for row in members]
        chain_status = "AMBIGUOUS" if "AMBIGUOUS" in chain_statuses else ("UNIQUE_CUMQTY_CHAIN" if "UNIQUE_CUMQTY_CHAIN" in chain_statuses else "NOT_IN_MULTI_TRADE_GROUP")
        valuations = [valuation_by_exec.get(str(row.get("execID", "")), {}) for row in members]
        accountings = [accounting_by_exec.get(str(row.get("execID", "")), {}) for row in members]
        prices = [str(value.get("canonical_price_status", "")) for value in valuations]
        order_confidence = ordering_confidence(chain_status)
        action_value = action_confidence(
            str(first.get("normalization_status", "")),
            "MATCHED" if order_id and representative else str(first.get("order_join_status", "")),
            action,
        )
        accounting_value = combine_confidences(
            accounting_confidence(str(row.get("accounting_status", "")), str(row.get("normalization_status", ""))) for row in accountings
        )
        price_value = combine_confidences(price_confidence(value) for value in prices)
        wallet_value = wallet_confidence()
        weighted_num = Decimal(0)
        weighted_qty = Decimal(0)
        for row, valuation in zip(members, valuations):
            price = _decimal(valuation.get("canonical_execution_price", row.get("lastPx")))
            qty = abs(_decimal(row.get("lastQty")) or Decimal(0))
            if price is not None and qty:
                weighted_num += price * qty
                weighted_qty += qty
        weighted_price = format(weighted_num / weighted_qty, "f") if weighted_qty else _first_nonempty(valuations, "canonical_execution_price", _first_nonempty(members, "lastPx"))
        fee_total = sum((_decimal(value.get("execComm_raw")) or Decimal(0) for value in valuations), Decimal(0))
        overall = overall_confidence(order_confidence, action_value, accounting_value, price_value, wallet_value)
        result.append({
            "order_episode_id": f"{symbol}-{episode_key}",
            "symbol": symbol,
            "is_btc_first_scope": symbol == "XBTUSD",
            "orderID": order_id,
            "order_join_status": first.get("order_join_status", ""),
            "first_event_time": first.get("event_time", ""),
            "last_event_time": last.get("event_time", ""),
            "side": _first_nonempty(members, "side"),
            "orderQty": representative.get("orderQty", _first_nonempty(members, "orderQty")),
            "filled_qty": sum(_int(row.get("lastQty")) for row in members),
            "signed_contract_qty": signed_total,
            "leavesQty_last": representative.get("leavesQty", last.get("leavesQty", "")),
            "execution_count": len(members),
            "execution_ids": ",".join(str(row.get("execID", "")) for row in members),
            "order_lifecycle_version_count": representative.get("_version_count", ""),
            "order_lifecycle_statuses": _join_values([representative] if representative else members, "ordStatus"),
            "ordStatus": representative.get("ordStatus", last.get("ordStatus", "")),
            "ordType": representative.get("ordType", first.get("ordType", "")),
            "limit_price": representative.get("price", first.get("price", "")),
            "weighted_execution_price": weighted_price,
            "timeInForce": representative.get("timeInForce", first.get("timeInForce", "")),
            "execInst": representative.get("execInst", first.get("execInst", "")),
            "strategy": representative.get("strategy", first.get("strategy", "")),
            "position_before": first_before,
            "position_after": _int(last.get("position_after")),
            "local_position_after": local_after,
            "action": action,
            "crossed_zero": any(bool(row.get("crossed_zero")) for row in members),
            "execution_batch_count": "",
            "fee_raw": format(fee_total, "f"),
            "execution_order_chain_status": chain_status,
            "ordering_confidence": order_confidence,
            "action_confidence": action_value,
            "accounting_confidence": accounting_value,
            "price_confidence": price_value,
            "wallet_confidence": wallet_value,
            "overall_confidence": overall,
            "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        })
    return result


__all__ = ["build_order_episodes", "build_trade_actions"]
