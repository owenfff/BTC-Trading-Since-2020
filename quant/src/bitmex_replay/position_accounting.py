from __future__ import annotations

import hashlib
import json
from collections import Counter, defaultdict
from decimal import (
    Decimal,
    InvalidOperation,
    ROUND_CEILING,
    ROUND_DOWN,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    ROUND_HALF_UP,
    localcontext,
)
from fractions import Fraction
from pathlib import Path
from typing import Any, Iterable

from .execution_valuation import parse_raw_integer_decimal
from .position_replayer import classify_action
from .reported_pnl_decomposition import decompose_reported_pnl


ROUNDING_MODES = {
    "ROUND_DOWN": ROUND_DOWN,
    "ROUND_FLOOR": ROUND_FLOOR,
    "ROUND_CEILING": ROUND_CEILING,
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
}
PAYOUT_MODELS = {"INVERSE", "LINEAR", "QUANTO"}
ACCOUNTING_ELIGIBLE = "ACCOUNTING_ELIGIBLE"
ACCOUNTING_ELIGIBLE_WITH_WARNING = "ACCOUNTING_ELIGIBLE_WITH_WARNING"
ACCOUNTING_BLOCKED = "ACCOUNTING_BLOCKED"
PASS = "PASS"
WARNING = "WARNING"
BLOCKED = "BLOCKED"
NOT_APPLICABLE = "NOT_APPLICABLE"


class PositionAccountingError(ValueError):
    """A deterministic accounting policy or input invariant is invalid."""


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _decimal(value: Any) -> Decimal | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        number = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _raw_int(value: Any) -> Decimal | None:
    return parse_raw_integer_decimal(value)


def _raw_int_text(value: Decimal | int | None) -> str | None:
    if value is None:
        return None
    number = Decimal(value)
    if number != number.to_integral_value():
        raise PositionAccountingError(f"API raw projection is not an integer: {value!r}")
    return format(number.to_integral_value(), "f")


def _fraction_raw(value: Any) -> Fraction | None:
    raw = _raw_int(value)
    return Fraction(raw) if raw is not None else None


def _fraction_decimal(value: Fraction | None) -> Decimal | None:
    if value is None:
        return None
    with localcontext() as context:
        context.prec = 200
        return Decimal(value.numerator) / Decimal(value.denominator)


def _fraction_text(value: Fraction | None) -> str | None:
    decimal_value = _fraction_decimal(value)
    return _decimal_text(decimal_value)


def _round_raw(value: Decimal, mode: str) -> Decimal:
    if mode not in ROUNDING_MODES:
        raise PositionAccountingError(f"unsupported rounding mode: {mode!r}")
    return value.to_integral_value(rounding=ROUNDING_MODES[mode])


def load_accounting_policy(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise PositionAccountingError("position accounting policy must be a JSON object")
    modes = payload.get("candidate_rounding_modes")
    if not isinstance(modes, list) or not modes:
        raise PositionAccountingError("candidate_rounding_modes must be non-empty")
    if any(mode not in ROUNDING_MODES for mode in modes):
        raise PositionAccountingError("candidate_rounding_modes contains an unsupported mode")
    tiebreak = payload.get("canonical_tiebreak") or {}
    for operation in ("average_cost_release", "flip_exec_cost_split"):
        if tiebreak.get(operation) not in ROUNDING_MODES:
            raise PositionAccountingError(f"missing canonical tiebreak for {operation}")
    inverse = payload.get("inverse_basis") or {}
    if int(inverse.get("decimal_places", -1)) != 8:
        raise PositionAccountingError("inverse basis decimal_places must be 8")
    if inverse.get("long_rounding") not in ROUNDING_MODES or inverse.get("short_rounding") not in ROUNDING_MODES:
        raise PositionAccountingError("invalid inverse basis rounding policy")
    snapshot = payload.get("snapshot_display") or {}
    if _decimal(snapshot.get("quantum")) is None or snapshot.get("rounding") not in ROUNDING_MODES:
        raise PositionAccountingError("invalid snapshot display policy")
    if payload.get("scope", {}).get("symbol_overrides") or payload.get("scope", {}).get("execid_overrides"):
        raise PositionAccountingError("symbol and execID policy overrides are forbidden")
    return payload


def accounting_eligibility(normalization_status: str) -> str:
    status = _text(normalization_status)
    if status == PASS:
        return ACCOUNTING_ELIGIBLE
    if status == WARNING:
        return ACCOUNTING_ELIGIBLE_WITH_WARNING
    if status == BLOCKED:
        return ACCOUNTING_BLOCKED
    raise PositionAccountingError(f"unknown valuation normalization status: {status!r}")


def split_signed_exec_cost(
    exec_cost_raw: Any,
    close_qty_abs: int,
    open_qty_abs: int,
    signed_qty: int,
    flip_rounding: str,
) -> dict[str, Decimal]:
    """Split one signed cost exactly once, with a fixed policy for flip projection."""

    cost = _raw_int(exec_cost_raw)
    if cost is None:
        raise PositionAccountingError("execCost_raw is missing")
    if close_qty_abs < 0 or open_qty_abs < 0 or abs(signed_qty) == 0:
        raise PositionAccountingError("invalid quantity for execution-cost split")
    if close_qty_abs + open_qty_abs != abs(signed_qty):
        raise PositionAccountingError("close_qty_abs + open_qty_abs must equal abs(signed_qty)")
    if open_qty_abs == 0:
        return {"close_exact": cost, "open_exact": Decimal(0), "close_api": cost, "open_api": Decimal(0)}
    if close_qty_abs == 0:
        return {"close_exact": Decimal(0), "open_exact": cost, "close_api": Decimal(0), "open_api": cost}
    close_exact = cost * Decimal(close_qty_abs) / Decimal(abs(signed_qty))
    open_exact = cost - close_exact
    close_api = _round_raw(close_exact, flip_rounding)
    open_api = cost - close_api
    if close_api + open_api != cost:
        raise PositionAccountingError("flip API cost split does not conserve original execCost")
    return {
        "close_exact": close_exact,
        "open_exact": open_exact,
        "close_api": close_api,
        "open_api": open_api,
    }


def _split_signed_exec_cost_fraction(
    exec_cost_raw: Any,
    close_qty_abs: int,
    open_qty_abs: int,
    signed_qty: int,
) -> dict[str, Fraction]:
    """Split the signed execution cost as exact rational values."""

    cost = _fraction_raw(exec_cost_raw)
    if cost is None:
        raise PositionAccountingError("execCost_raw is missing")
    if close_qty_abs < 0 or open_qty_abs < 0 or abs(signed_qty) == 0:
        raise PositionAccountingError("invalid quantity for execution-cost split")
    if close_qty_abs + open_qty_abs != abs(signed_qty):
        raise PositionAccountingError("close_qty_abs + open_qty_abs must equal abs(signed_qty)")
    if open_qty_abs == 0:
        return {"close_exact": cost, "open_exact": Fraction(0)}
    if close_qty_abs == 0:
        return {"close_exact": Fraction(0), "open_exact": cost}
    close_exact = cost * Fraction(close_qty_abs, abs(signed_qty))
    return {"close_exact": close_exact, "open_exact": cost - close_exact}


def _inverse_fill_basis(
    lot_size: Decimal,
    price: Decimal,
    direction: int,
    policy: dict[str, Any],
) -> Decimal:
    if price <= 0 or lot_size <= 0:
        raise PositionAccountingError("inverse AEP requires positive lot_size and price")
    inverse_policy = policy["inverse_basis"]
    rounding = inverse_policy["long_rounding"] if direction > 0 else inverse_policy["short_rounding"]
    quantum = Decimal("1") / (Decimal(10) ** int(inverse_policy["decimal_places"]))
    return (lot_size / price).quantize(quantum, rounding=ROUNDING_MODES[rounding])


def update_average_entry(
    *,
    before_price: Decimal | None,
    before_basis: Decimal | None,
    position_before: int,
    position_after: int,
    open_qty_abs: int,
    fill_price: Decimal | None,
    payout_model: str,
    spec: dict[str, Any],
    policy: dict[str, Any],
    reset_on_flip: bool,
) -> tuple[Decimal | None, Decimal | None]:
    """Update AEP independently from currentCost."""

    if position_after == 0:
        return None, None
    if open_qty_abs == 0:
        return before_price, before_basis
    if fill_price is None or fill_price <= 0:
        raise PositionAccountingError("opening or adding fill has no positive canonical price")
    direction = 1 if position_after > 0 else -1
    if payout_model == "INVERSE":
        lot_size = _decimal(spec.get("lot_size"))
        if lot_size is None:
            raise PositionAccountingError(f"inverse specification {spec.get('spec_id', '')} has no lot_size")
        fill_basis = _inverse_fill_basis(lot_size, fill_price, direction, policy)
        if reset_on_flip or before_basis is None or position_before == 0:
            basis = fill_basis
        else:
            basis = (
                before_basis * Decimal(abs(position_before))
                + fill_basis * Decimal(open_qty_abs)
            ) / Decimal(abs(position_before) + open_qty_abs)
        return lot_size / basis, basis
    if payout_model not in {"QUANTO", "LINEAR"}:
        raise PositionAccountingError(f"unsupported payout_model: {payout_model!r}")
    if reset_on_flip or before_price is None or position_before == 0:
        return fill_price, None
    price = (
        before_price * Decimal(abs(position_before))
        + fill_price * Decimal(open_qty_abs)
    ) / Decimal(abs(position_before) + open_qty_abs)
    return price, None


def _empty_state() -> dict[str, Any]:
    return {
        "qty": 0,
        "cost_exact": Fraction(0),
        "cost_api": Decimal(0),
        "aep": None,
        "basis": None,
        "cycle_id": "",
        "cycle_direction": 0,
        "cycle_open_time": "",
        "cycle_open_execID": "",
        "cycle_counter": 0,
        "cumulative_gross_exact": Fraction(0),
        "cumulative_gross_api": Decimal(0),
    }


def _conservation_status(before: Any, cost: Any, after: Any, realised: Any) -> str:
    return PASS if before + cost == after + realised else BLOCKED


def _trace_digest_update(digest: Any, row: dict[str, Any]) -> None:
    digest.update(
        "|".join(
            [
                _text(row.get("symbol")),
                _text(row.get("execID")),
                _text(row.get("current_cost_after_api_raw")),
                _text(row.get("position_after")),
            ]
        ).encode("utf-8")
    )


def _replay_position_accounting_impl(
    valuations: Iterable[dict[str, Any]],
    position_events: dict[str, dict[str, Any]],
    specs: dict[str, dict[str, Any]],
    policy: dict[str, Any],
    average_cost_release_rounding: str,
    flip_exec_cost_split_rounding: str,
    *,
    collect_rows: bool = True,
) -> dict[str, Any]:
    """Replay derivative events under one fixed pair of rounding policies."""

    if average_cost_release_rounding not in ROUNDING_MODES or flip_exec_cost_split_rounding not in ROUNDING_MODES:
        raise PositionAccountingError("invalid accounting rounding candidate")
    states: dict[str, dict[str, Any]] = defaultdict(_empty_state)
    rows: list[dict[str, Any]] = []
    action_counts: Counter[str] = Counter()
    cycle_count = 0
    flip_count = 0
    full_close_count = 0
    exact_conservation_failures = 0
    api_conservation_failures = 0
    flip_split_failures = 0
    full_close_residuals = 0
    settlement_residuals = 0
    anomalies: list[dict[str, Any]] = []
    digest = hashlib.sha256()
    terminal: dict[str, dict[str, Any]] = {}
    reported_stats = {
        "non_null": 0,
        "eligible": 0,
        "exact": 0,
        "mismatch": 0,
        "missing": 0,
        "broker_unresolved": 0,
    }
    blocked_count = 0

    for valuation in valuations:
        exec_id = _text(valuation.get("execID"))
        symbol = _text(valuation.get("symbol"))
        event_type = _text(valuation.get("execType"))
        state = states[symbol]
        before_qty = int(state["qty"])
        before_exact = state["cost_exact"]
        before_api = state["cost_api"]
        before_aep = state["aep"]
        before_basis = state["basis"]
        position_event = position_events.get(exec_id, {})
        dq = int(position_event.get("signed_contract_qty") or valuation.get("signed_contract_qty") or 0)
        after_qty = before_qty + dq
        action = classify_action(before_qty, dq, after_qty)
        valuation_status = _text(valuation.get("normalization_status"))
        eligibility = accounting_eligibility(valuation_status)
        spec_id = _text(valuation.get("spec_id"))
        spec = specs.get(spec_id, {})
        if valuation.get("resolved_lot_size") not in (None, ""):
            spec = dict(spec)
            spec["lot_size"] = valuation.get("resolved_lot_size")
        payout_model = _text(valuation.get("payout_model") or spec.get("payout_model")).upper()
        settlement_currency = _text(valuation.get("settlement_currency") or spec.get("settlement_currency"))
        row: dict[str, Any] = {
            "event_time": valuation.get("event_time", ""),
            "source_row_number": valuation.get("source_row_number"),
            "execID": exec_id,
            "execType": event_type,
            "symbol": symbol,
            "spec_id": spec_id,
            "resolved_lot_size": valuation.get("resolved_lot_size"),
            "terms_id": valuation.get("terms_id", ""),
            "terms_resolution_status": valuation.get("terms_resolution_status", ""),
            "payout_model": payout_model,
            "settlement_currency": settlement_currency,
            "accounting_eligibility": eligibility,
            "valuation_status": valuation_status,
            "side": valuation.get("side", ""),
            "orderID": valuation.get("orderID", ""),
            "execution_order_policy": valuation.get("execution_order_policy", "SOURCE_ROW_STABLE"),
            "execution_order_chain_status": valuation.get("execution_order_chain_status", ""),
            "execution_order_rank": valuation.get("execution_order_rank", 0),
            "canonical_execution_price": valuation.get("canonical_execution_price"),
            "canonical_price_status": valuation.get("canonical_price_status", ""),
            "action": action,
            "signed_contract_qty": str(dq),
            "position_before": before_qty,
            "position_after": after_qty,
            "close_qty_abs": 0,
            "open_qty_abs": 0,
            "execCost_raw": valuation.get("execCost_raw"),
            "close_exec_cost_exact_raw": "0",
            "close_exec_cost_api_raw": "0",
            "open_exec_cost_exact_raw": "0",
            "open_exec_cost_api_raw": "0",
            "current_cost_before_exact_raw": _fraction_text(before_exact),
            "current_cost_before_api_raw": _raw_int_text(before_api),
            "released_open_cost_exact_raw": "0",
            "released_open_cost_api_raw": "0",
            "realised_cost_delta_exact_raw": "0",
            "realised_cost_delta_api_raw": "0",
            "gross_realised_pnl_exact_raw": "0",
            "gross_realised_pnl_api_raw": "0",
            "current_cost_after_exact_raw": _fraction_text(before_exact),
            "current_cost_after_api_raw": _raw_int_text(before_api),
            "average_entry_basis_before": _decimal_text(before_basis),
            "average_entry_basis_after": _decimal_text(before_basis),
            "average_entry_price_before": _decimal_text(before_aep),
            "average_entry_price_after": _decimal_text(before_aep),
            "reported_realisedPnl_raw": valuation.get("realisedPnl_raw"),
            "execComm_raw": valuation.get("execComm_raw"),
            "brokerExecComm_raw": valuation.get("brokerExecComm_raw"),
            "reported_realised_pnl_raw": valuation.get("realisedPnl_raw"),
            "exec_comm_raw": valuation.get("execComm_raw"),
            "broker_exec_comm_raw": valuation.get("brokerExecComm_raw"),
            "reported_fee_component_raw": valuation.get("execComm_raw"),
            "reported_gross_candidate_raw": None,
            "reconstructed_gross_realised_pnl_raw": "0",
            "reported_gross_difference_raw": None,
            "decomposition_status": "MISSING",
            "decomposition_reason": "",
            "reported_pnl_difference_raw": None,
            "position_cycle_id": state["cycle_id"],
            "closing_cycle_id": "",
            "opening_cycle_id": "",
            "accounting_policy_id": f"average_cost_release={average_cost_release_rounding};flip_exec_cost_split={flip_exec_cost_split_rounding}",
            "exact_conservation_status": NOT_APPLICABLE,
            "api_conservation_status": NOT_APPLICABLE,
            "accounting_status": eligibility,
            "accounting_reason": "",
            "cumulative_gross_realised_pnl_exact_raw": _fraction_text(state["cumulative_gross_exact"]),
            "cumulative_gross_realised_pnl_api_raw": _raw_int_text(state["cumulative_gross_api"]),
        }
        row_blocked = False
        try:
            if eligibility == ACCOUNTING_BLOCKED:
                raise PositionAccountingError("valuation is BLOCKED")
            if event_type not in {"Trade", "Funding", "Settlement"}:
                raise PositionAccountingError(f"unsupported accounting execType={event_type!r}")
            if event_type in {"Trade", "Settlement"} and dq == 0:
                raise PositionAccountingError("Trade/Settlement has zero signed contract quantity")
            if event_type == "Settlement" and after_qty != 0:
                raise PositionAccountingError("Settlement must close the full derivative position")
            if event_type in {"Trade", "Settlement"}:
                close_qty = min(abs(before_qty), abs(dq)) if before_qty and before_qty * dq < 0 else 0
                open_qty = abs(dq) - close_qty
                cost_split_exact = _split_signed_exec_cost_fraction(
                    valuation.get("execCost_raw"), close_qty, open_qty, dq
                )
                cost_split = split_signed_exec_cost(
                    valuation.get("execCost_raw"),
                    close_qty,
                    open_qty,
                    dq,
                    flip_exec_cost_split_rounding,
                )
                full_close = close_qty > 0 and close_qty == abs(before_qty) and open_qty == 0
                if full_close:
                    released_exact = before_exact
                    released_api = before_api
                elif close_qty:
                    released_exact = before_exact * Fraction(close_qty, abs(before_qty))
                    released_api = _round_raw(
                        _fraction_decimal(released_exact) or Decimal(0),
                        average_cost_release_rounding,
                    )
                else:
                    released_exact = Fraction(0)
                    released_api = Decimal(0)
                after_exact = before_exact - released_exact + cost_split_exact["open_exact"]
                after_api = before_api - released_api + cost_split["open_api"]
                realised_exact = released_exact + cost_split_exact["close_exact"]
                realised_api = released_api + cost_split["close_api"]
                gross_exact = -realised_exact
                gross_api = -realised_api
                exact_status = _conservation_status(
                    before_exact,
                    _fraction_raw(valuation.get("execCost_raw")) or Fraction(0),
                    after_exact,
                    realised_exact,
                )
                api_status = _conservation_status(before_api, _raw_int(valuation.get("execCost_raw")) or Decimal(0), after_api, realised_api)
                if exact_status != PASS:
                    exact_conservation_failures += 1
                if api_status != PASS:
                    api_conservation_failures += 1
                if close_qty and open_qty and cost_split["close_api"] + cost_split["open_api"] != _raw_int(valuation.get("execCost_raw")):
                    flip_split_failures += 1
                if full_close:
                    full_close_count += 1
                if event_type == "Settlement" and after_api != 0:
                    settlement_residuals += 1
                fill_price = _decimal(valuation.get("canonical_execution_price"))
                reset_on_flip = before_qty and dq and before_qty * dq < 0 and after_qty * before_qty < 0
                after_aep, after_basis = update_average_entry(
                    before_price=before_aep,
                    before_basis=before_basis,
                    position_before=before_qty,
                    position_after=after_qty,
                    open_qty_abs=open_qty,
                    fill_price=fill_price,
                    payout_model=payout_model,
                    spec=spec,
                    policy=policy,
                    reset_on_flip=bool(reset_on_flip),
                )
                row.update({
                    "close_qty_abs": close_qty,
                    "open_qty_abs": open_qty,
                    "close_exec_cost_exact_raw": _fraction_text(cost_split_exact["close_exact"]),
                    "close_exec_cost_api_raw": _raw_int_text(cost_split["close_api"]),
                    "open_exec_cost_exact_raw": _fraction_text(cost_split_exact["open_exact"]),
                    "open_exec_cost_api_raw": _raw_int_text(cost_split["open_api"]),
                    "released_open_cost_exact_raw": _fraction_text(released_exact),
                    "released_open_cost_api_raw": _raw_int_text(released_api),
                    "realised_cost_delta_exact_raw": _fraction_text(realised_exact),
                    "realised_cost_delta_api_raw": _raw_int_text(realised_api),
                    "gross_realised_pnl_exact_raw": _fraction_text(gross_exact),
                    "gross_realised_pnl_api_raw": _raw_int_text(gross_api),
                    "current_cost_after_exact_raw": _fraction_text(after_exact),
                    "current_cost_after_api_raw": _raw_int_text(after_api),
                    "average_entry_basis_after": _decimal_text(after_basis),
                    "average_entry_price_after": _decimal_text(after_aep),
                    "exact_conservation_status": exact_status,
                    "api_conservation_status": api_status,
                })
                if exact_status != PASS or api_status != PASS:
                    raise PositionAccountingError("cost conservation identity failed")
                if full_close and (after_exact != 0 or after_api != 0):
                    full_close_residuals += 1
                    raise PositionAccountingError("full close left residual cost")
                state["cost_exact"] = after_exact
                state["cost_api"] = after_api
                state["aep"] = after_aep
                state["basis"] = after_basis
                state["qty"] = after_qty
                state["cumulative_gross_exact"] += gross_exact
                state["cumulative_gross_api"] += gross_api
            else:
                after_exact = before_exact
                after_api = before_api
                after_aep = before_aep
                after_basis = before_basis
                state["qty"] = after_qty
            old_cycle = state["cycle_id"]
            if not row_blocked and before_qty == 0 and after_qty != 0:
                state["cycle_counter"] += 1
                cycle_count += 1
                new_cycle = f"{symbol}-C{state['cycle_counter']:04d}"
                state["cycle_id"] = new_cycle
                state["cycle_direction"] = 1 if after_qty > 0 else -1
                state["cycle_open_time"] = _text(valuation.get("event_time"))
                state["cycle_open_execID"] = exec_id
                row["opening_cycle_id"] = new_cycle
            elif not row_blocked and before_qty != 0 and after_qty == 0:
                row["closing_cycle_id"] = old_cycle
                state["cycle_id"] = ""
                state["cycle_direction"] = 0
                state["cycle_open_time"] = ""
                state["cycle_open_execID"] = ""
            elif not row_blocked and before_qty != 0 and after_qty != 0 and before_qty * after_qty < 0:
                flip_count += 1
                row["closing_cycle_id"] = old_cycle
                state["cycle_counter"] += 1
                cycle_count += 1
                new_cycle = f"{symbol}-C{state['cycle_counter']:04d}"
                state["cycle_id"] = new_cycle
                state["cycle_direction"] = 1 if after_qty > 0 else -1
                state["cycle_open_time"] = _text(valuation.get("event_time"))
                state["cycle_open_execID"] = exec_id
                row["opening_cycle_id"] = new_cycle
            row["position_cycle_id"] = state["cycle_id"] or row["closing_cycle_id"]
            row["current_cost_after_exact_raw"] = _fraction_text(state["cost_exact"])
            row["current_cost_after_api_raw"] = _raw_int_text(state["cost_api"])
            row["cumulative_gross_realised_pnl_exact_raw"] = _fraction_text(state["cumulative_gross_exact"])
            row["cumulative_gross_realised_pnl_api_raw"] = _raw_int_text(state["cumulative_gross_api"])
            row["accounting_status"] = eligibility
            row["accounting_reason"] = "valuation warning retained as accounting-eligible" if eligibility == ACCOUNTING_ELIGIBLE_WITH_WARNING else ""
        except (PositionAccountingError, ValueError, ArithmeticError) as exc:
            row_blocked = True
            blocked_count += 1
            row["accounting_status"] = ACCOUNTING_BLOCKED
            row["accounting_reason"] = str(exc)
            row["position_after"] = before_qty
            row["current_cost_after_exact_raw"] = _fraction_text(before_exact)
            row["current_cost_after_api_raw"] = _raw_int_text(before_api)
            if len(anomalies) < 200:
                anomalies.append({
                    "execID": exec_id,
                    "event_time": valuation.get("event_time", ""),
                    "symbol": symbol,
                    "execType": event_type,
                    "anomaly_type": "ACCOUNTING_BLOCKED",
                    "reason": str(exc),
                })
        action_counts[action] += 1
        decomposition = decompose_reported_pnl(
            row,
            action=action,
            reconstructed_gross_realised_pnl_raw=row.get("gross_realised_pnl_exact_raw"),
        )
        row.update(decomposition)
        row["reported_pnl_difference_raw"] = decomposition.get("reported_gross_difference_raw")
        if decomposition.get("decomposition_eligible"):
            reported_stats["eligible"] += 1
        if decomposition.get("reported_realised_pnl_raw") is None:
            reported_stats["missing"] += 1
        else:
            reported_stats["non_null"] += 1
        status = decomposition.get("decomposition_status")
        if status == "EXACT":
            reported_stats["exact"] += 1
        elif status == "BROKER_COMPONENT_UNRESOLVED":
            reported_stats["broker_unresolved"] += 1
        elif status == "MISMATCH":
            reported_stats["mismatch"] += 1
        _trace_digest_update(digest, row)
        terminal[symbol] = {
            "symbol": symbol,
            "payout_model": payout_model,
            "settlement_currency": settlement_currency,
            "position_qty": state["qty"],
            "current_cost_exact_raw": _fraction_text(state["cost_exact"]),
            "current_cost_api_raw": _raw_int_text(state["cost_api"]),
            "average_entry_basis": _decimal_text(state["basis"]),
            "average_entry_price": _decimal_text(state["aep"]),
            "position_cycle_id": state["cycle_id"],
            "cycle_count": state["cycle_counter"],
            "cycle_open_time": state["cycle_open_time"],
            "cycle_open_execID": state["cycle_open_execID"],
        }
        if collect_rows:
            rows.append(row)

    for symbol, state in states.items():
        if state["qty"] == 0 and state["cost_api"] != 0:
            full_close_residuals += 1
    terminal_nonzero = sorted(symbol for symbol, item in terminal.items() if item["position_qty"] != 0)
    return {
        "rows": rows,
        "terminal": [terminal[symbol] for symbol in sorted(terminal)],
        "terminal_nonzero_symbols": terminal_nonzero,
        "action_counts": dict(action_counts),
        "cycle_count": cycle_count,
        "flip_count": flip_count,
        "full_close_count": full_close_count,
        "exact_conservation_failure_count": exact_conservation_failures,
        "api_conservation_failure_count": api_conservation_failures,
        "flip_exec_cost_split_failure_count": flip_split_failures,
        "full_close_residual_cost_count": full_close_residuals,
        "settlement_residual_cost_count": settlement_residuals,
        "reported_pnl": reported_stats,
        "accounting_blocked_count": blocked_count,
        "api_trace_digest": digest.hexdigest(),
        "states": states,
        "anomalies": anomalies,
    }


def replay_position_accounting(
    valuations: Iterable[dict[str, Any]],
    position_events: dict[str, dict[str, Any]],
    specs: dict[str, dict[str, Any]],
    policy: dict[str, Any],
    average_cost_release_rounding: str,
    flip_exec_cost_split_rounding: str,
    *,
    collect_rows: bool = True,
) -> dict[str, Any]:
    """Replay with enough Decimal precision for exact long-run cost identities."""

    with localcontext() as context:
        context.prec = 200
        return _replay_position_accounting_impl(
            valuations,
            position_events,
            specs,
            policy,
            average_cost_release_rounding,
            flip_exec_cost_split_rounding,
            collect_rows=collect_rows,
        )


def _replay_cost_policy_fast_impl(
    valuations: list[dict[str, Any]],
    position_events: dict[str, dict[str, Any]],
    average_cost_release_rounding: str,
    flip_exec_cost_split_rounding: str,
) -> dict[str, Any]:
    """Fast policy-audit replay without AEP or per-row output dictionaries."""

    states: dict[str, dict[str, Fraction | Decimal | int]] = defaultdict(lambda: {"qty": 0, "exact": Fraction(0), "api": Decimal(0)})
    digest = hashlib.sha256()
    terminal: dict[str, dict[str, Any]] = {}
    exact_failures = 0
    api_failures = 0
    split_failures = 0
    flat_residuals = 0
    settlement_residuals = 0
    blocked = 0
    reported = {"non_null": 0, "exact": 0, "mismatch": 0, "missing": 0}
    for valuation in valuations:
        symbol = _text(valuation.get("symbol"))
        exec_id = _text(valuation.get("execID"))
        event_type = _text(valuation.get("execType"))
        state = states[symbol]
        before_qty = int(state["qty"])
        before_exact = state["exact"]
        before_api = state["api"]
        position_event = position_events.get(exec_id, {})
        dq = int(position_event.get("signed_contract_qty") or valuation.get("signed_contract_qty") or 0)
        after_qty = before_qty + dq
        gross = Decimal(0)
        if _text(valuation.get("normalization_status")) == BLOCKED:
            blocked += 1
        elif event_type in {"Trade", "Settlement"}:
            try:
                if dq == 0:
                    raise PositionAccountingError("Trade/Settlement has zero signed contract quantity")
                close_qty = min(abs(before_qty), abs(dq)) if before_qty and before_qty * dq < 0 else 0
                open_qty = abs(dq) - close_qty
                split_exact = _split_signed_exec_cost_fraction(
                    valuation.get("execCost_raw"), close_qty, open_qty, dq
                )
                split = split_signed_exec_cost(valuation.get("execCost_raw"), close_qty, open_qty, dq, flip_exec_cost_split_rounding)
                if close_qty == abs(before_qty) and open_qty == 0:
                    release_exact = before_exact
                    release_api = before_api
                elif close_qty:
                    release_exact = before_exact * Fraction(close_qty, abs(before_qty))
                    release_api = _round_raw(_fraction_decimal(release_exact) or Decimal(0), average_cost_release_rounding)
                else:
                    release_exact = Fraction(0)
                    release_api = Decimal(0)
                after_exact = before_exact - release_exact + split_exact["open_exact"]
                after_api = before_api - release_api + split["open_api"]
                realised_exact = release_exact + split_exact["close_exact"]
                realised_api = release_api + split["close_api"]
                gross = -realised_exact
                if _conservation_status(before_exact, _fraction_raw(valuation.get("execCost_raw")) or Fraction(0), after_exact, realised_exact) != PASS:
                    exact_failures += 1
                if _conservation_status(before_api, _raw_int(valuation.get("execCost_raw")) or Decimal(0), after_api, realised_api) != PASS:
                    api_failures += 1
                if close_qty and open_qty and split["close_api"] + split["open_api"] != _raw_int(valuation.get("execCost_raw")):
                    split_failures += 1
                if close_qty == abs(before_qty) and open_qty == 0 and (after_exact != 0 or after_api != 0):
                    flat_residuals += 1
                if event_type == "Settlement" and after_qty != 0:
                    settlement_residuals += 1
                state["exact"] = after_exact
                state["api"] = after_api
            except (PositionAccountingError, ValueError, ArithmeticError):
                blocked += 1
        else:
            after_exact = before_exact
            after_api = before_api
        state["qty"] = after_qty
        reported_value = _raw_int(valuation.get("realisedPnl_raw"))
        if reported_value is None:
            reported["missing"] += 1
        else:
            reported["non_null"] += 1
            if reported_value == gross:
                reported["exact"] += 1
            else:
                reported["mismatch"] += 1
        digest.update(f"{symbol}|{exec_id}|{_raw_int_text(state['api'])}|{state['qty']}".encode("utf-8"))
        terminal[symbol] = {
            "symbol": symbol,
            "position_qty": int(state["qty"]),
            "current_cost_api_raw": _raw_int_text(state["api"]),
        }
    for state in states.values():
        if int(state["qty"]) == 0 and state["api"] != 0:
            flat_residuals += 1
    return {
        "accounting_blocked_count": blocked,
        "exact_conservation_failure_count": exact_failures,
        "api_conservation_failure_count": api_failures,
        "flip_exec_cost_split_failure_count": split_failures,
        "full_close_residual_cost_count": flat_residuals,
        "settlement_residual_cost_count": settlement_residuals,
        "reported_pnl": reported,
        "api_trace_digest": digest.hexdigest(),
        "terminal": [terminal[symbol] for symbol in sorted(terminal)],
    }


def _replay_cost_policy_fast(
    valuations: list[dict[str, Any]],
    position_events: dict[str, dict[str, Any]],
    average_cost_release_rounding: str,
    flip_exec_cost_split_rounding: str,
) -> dict[str, Any]:
    """Run the policy-audit replay with high-precision Decimal arithmetic."""

    with localcontext() as context:
        context.prec = 200
        return _replay_cost_policy_fast_impl(
            valuations,
            position_events,
            average_cost_release_rounding,
            flip_exec_cost_split_rounding,
        )


def audit_rounding_policies(
    valuations: list[dict[str, Any]],
    position_events: dict[str, dict[str, Any]],
    specs: dict[str, dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Evaluate all global operation-pair candidates before selecting one."""

    candidates = list(policy["candidate_rounding_modes"])
    combinations: list[dict[str, Any]] = []
    for average_mode in candidates:
        for flip_mode in candidates:
            result = _replay_cost_policy_fast(valuations, position_events, average_mode, flip_mode)
            xbt = next((row for row in result["terminal"] if row["symbol"] == "XBTUSD"), {})
            xbt_cost = _decimal(xbt.get("current_cost_api_raw")) or Decimal(0)
            xbt_difference = xbt_cost - Decimal("1386445811")
            status = PASS if (
                result["accounting_blocked_count"] == 0
                and result["exact_conservation_failure_count"] == 0
                and result["api_conservation_failure_count"] == 0
                and result["flip_exec_cost_split_failure_count"] == 0
                and result["full_close_residual_cost_count"] == 0
                and result["settlement_residual_cost_count"] == 0
                and xbt_difference == 0
            ) else BLOCKED
            combinations.append({
                "average_cost_release": average_mode,
                "flip_exec_cost_split": flip_mode,
                "status": status,
                "result": result,
                "xbtusd_terminal_current_cost": _raw_int_text(xbt_cost),
                "xbtusd_current_cost_difference": _raw_int_text(xbt_difference),
            })
    passing = [item for item in combinations if item["status"] == PASS]
    signatures = {(
        item["result"]["api_trace_digest"],
        item["xbtusd_terminal_current_cost"],
    ) for item in passing}
    ambiguity_count = len(signatures) if len(signatures) > 1 else 0
    canonical = policy["canonical_tiebreak"]
    canonical_item = next(
        item for item in combinations
        if item["average_cost_release"] == canonical["average_cost_release"]
        and item["flip_exec_cost_split"] == canonical["flip_exec_cost_split"]
    )
    selected: dict[str, Any] | None = None
    selection_status = PASS
    selection_reason = ""
    if not passing:
        selection_status = BLOCKED
        selection_reason = "no candidate policy satisfies conservation and terminal currentCost anchors"
    elif ambiguity_count:
        selection_status = BLOCKED
        selection_reason = "multiple passing policies produce different API current-cost traces"
    elif canonical_item["status"] == PASS:
        selected = canonical_item
        selection_reason = "canonical tiebreak is observationally equivalent to every passing candidate"
    else:
        selected = passing[0]
        selection_reason = "exactly one passing policy combination remains"
    rows: list[dict[str, Any]] = []
    for operation in ("average_cost_release", "flip_exec_cost_split"):
        fixed_other = canonical["flip_exec_cost_split"] if operation == "average_cost_release" else canonical["average_cost_release"]
        for mode in candidates:
            combo = next(
                item for item in combinations
                if item["average_cost_release"] == (mode if operation == "average_cost_release" else fixed_other)
                and item["flip_exec_cost_split"] == (fixed_other if operation == "average_cost_release" else mode)
            )
            row_status = combo["status"]
            if selected and combo is selected:
                row_status = "SELECTED"
            elif selection_status == BLOCKED and combo["status"] == PASS:
                row_status = "AMBIGUOUS"
            rows.append({
                "operation": operation,
                "payout_model": "ALL",
                "settlement_currency": "ALL",
                "candidate_policy": mode,
                "evaluated_event_count": len(valuations),
                "conservation_failure_count": combo["result"]["exact_conservation_failure_count"],
                "flat_cost_failure_count": combo["result"]["full_close_residual_cost_count"],
                "settlement_cost_failure_count": combo["result"]["settlement_residual_cost_count"],
                "xbtusd_terminal_current_cost": combo["xbtusd_terminal_current_cost"],
                "xbtusd_current_cost_difference": combo["xbtusd_current_cost_difference"],
                "reported_pnl_exact_match_count": combo["result"]["reported_pnl"]["exact"],
                "reported_pnl_mismatch_count": combo["result"]["reported_pnl"]["mismatch"],
                "status": row_status,
                "selection_reason": selection_reason,
            })
    return {
        "rows": rows,
        "combinations": combinations,
        "selection_status": selection_status,
        "selection_reason": selection_reason,
        "selected_average_cost_release": selected["average_cost_release"] if selected else None,
        "selected_flip_exec_cost_split": selected["flip_exec_cost_split"] if selected else None,
        "ambiguity_count": ambiguity_count,
        "selected_result": selected["result"] if selected else None,
    }


def reconcile_terminal_snapshot(
    terminal: list[dict[str, Any]],
    snapshot: dict[str, Any],
    *,
    snapshot_display_quantum: str,
    snapshot_display_rounding: str,
) -> dict[str, Any]:
    """Compare quantity, raw costs, and independently reconstructed AEP to one snapshot."""

    by_symbol = {row.get("symbol"): row for row in terminal}
    rows: list[dict[str, Any]] = []
    for symbol, snap in snapshot.items():
        reconstructed = by_symbol.get(symbol, {})
        reconstructed_aep = _decimal(reconstructed.get("average_entry_price"))
        quantum = _decimal(snapshot_display_quantum)
        if quantum is None or snapshot_display_rounding not in ROUNDING_MODES:
            raise PositionAccountingError("invalid snapshot display rounding configuration")
        displayed = reconstructed_aep.quantize(quantum, rounding=ROUNDING_MODES[snapshot_display_rounding]) if reconstructed_aep is not None else None
        expected_qty = int(_raw_int(snap.get("currentQty")) or 0)
        expected_cost = _raw_int(snap.get("currentCost"))
        expected_pos_cost = _raw_int(snap.get("posCost"))
        expected_aep = _decimal(snap.get("avgEntryPrice"))
        expected_avg_cost = _decimal(snap.get("avgCostPrice"))
        actual_qty = int(reconstructed.get("position_qty", 0))
        actual_cost = _raw_int(reconstructed.get("current_cost_api_raw"))
        qty_status = PASS if actual_qty == expected_qty else BLOCKED
        cost_status = PASS if actual_cost == expected_cost else BLOCKED
        pos_cost_status = PASS if actual_cost == expected_pos_cost else BLOCKED
        aep_status = PASS if displayed == expected_aep else BLOCKED
        avg_cost_status = PASS if displayed == expected_avg_cost else BLOCKED
        rows.append({
            "symbol": symbol,
            "snapshot_timestamp": snap.get("timestamp", ""),
            "reconstructed_currentQty": actual_qty,
            "snapshot_currentQty": expected_qty,
            "quantity_status": qty_status,
            "reconstructed_currentCost": _raw_int_text(actual_cost),
            "snapshot_currentCost": _raw_int_text(expected_cost),
            "current_cost_status": cost_status,
            "reconstructed_posCost": _raw_int_text(actual_cost),
            "snapshot_posCost": _raw_int_text(expected_pos_cost),
            "pos_cost_status": pos_cost_status,
            "reconstructed_aep_exact": _decimal_text(reconstructed_aep),
            "reconstructed_aep_display": _decimal_text(displayed),
            "snapshot_avgEntryPrice": _decimal_text(expected_aep),
            "avg_entry_price_status": aep_status,
            "snapshot_avgCostPrice": _decimal_text(expected_avg_cost),
            "avg_cost_price_status": avg_cost_status,
            "reconciliation_status": PASS if all(item == PASS for item in (qty_status, cost_status, pos_cost_status, aep_status, avg_cost_status)) else BLOCKED,
        })
    return {
        "rows": rows,
        "status": PASS if all(row["reconciliation_status"] == PASS for row in rows) else BLOCKED,
    }


def build_position_accounting(
    valuations: list[dict[str, Any]],
    position_events: Iterable[dict[str, Any]],
    specs: dict[str, dict[str, Any]],
    policy: dict[str, Any],
) -> dict[str, Any]:
    """Run policy audit, select a fixed policy, and emit the canonical replay."""

    position_by_exec = {_text(row.get("execID")): row for row in position_events}
    derivative_valuations = [row for row in valuations if _text(row.get("instrument_class")) == "DERIVATIVE"]
    blocked_valuation_ids = [
        _text(row.get("execID")) for row in derivative_valuations
        if _text(row.get("normalization_status")) == BLOCKED
    ]
    if blocked_valuation_ids:
        return {
            "status": BLOCKED,
            "readiness": "BLOCKED_BY_POSITION_ACCOUNTING",
            "blockers": [f"{len(blocked_valuation_ids)} valuation rows are BLOCKED"],
            "valuations": derivative_valuations,
            "events": [],
            "terminal": [],
            "policy_audit": {"rows": [], "selection_status": BLOCKED, "ambiguity_count": 0},
            "anomalies": [],
        }
    audit = audit_rounding_policies(derivative_valuations, position_by_exec, specs, policy)
    blockers: list[str] = []
    if audit["selection_status"] != PASS:
        blockers.append(audit["selection_reason"])
    replay_average_mode = audit["selected_average_cost_release"] or policy["canonical_tiebreak"]["average_cost_release"]
    replay_flip_mode = audit["selected_flip_exec_cost_split"] or policy["canonical_tiebreak"]["flip_exec_cost_split"]
    canonical = replay_position_accounting(
        derivative_valuations,
        position_by_exec,
        specs,
        policy,
        replay_average_mode,
        replay_flip_mode,
        collect_rows=True,
    )
    if canonical["accounting_blocked_count"]:
        blockers.append(f"{canonical['accounting_blocked_count']} accounting rows became BLOCKED")
    status = BLOCKED if blockers else ("READY_WITH_WARNINGS" if canonical["reported_pnl"]["mismatch"] else PASS)
    if audit["selection_status"] != PASS:
        readiness = "BLOCKED_BY_ACCOUNTING_ROUNDING_POLICY"
    else:
        readiness = "READY_FOR_POSITION_LIFECYCLE_REPLAY" if not blockers else "BLOCKED_BY_POSITION_ACCOUNTING"
    return {
        "status": status,
        "readiness": readiness,
        "blockers": blockers,
        "valuations": derivative_valuations,
        "events": canonical["rows"],
        "terminal": canonical["terminal"],
        "summary": canonical,
        "policy_audit": audit,
        "selected_average_cost_release": audit["selected_average_cost_release"],
        "selected_flip_exec_cost_split": audit["selected_flip_exec_cost_split"],
        "rounding_policy_ambiguity_count": audit["ambiguity_count"],
        "anomalies": canonical["anomalies"],
    }


__all__ = [
    "ACCOUNTING_BLOCKED",
    "ACCOUNTING_ELIGIBLE",
    "ACCOUNTING_ELIGIBLE_WITH_WARNING",
    "BLOCKED",
    "PASS",
    "PAYOUT_MODELS",
    "PositionAccountingError",
    "ROUNDING_MODES",
    "WARNING",
    "accounting_eligibility",
    "audit_rounding_policies",
    "build_position_accounting",
    "load_accounting_policy",
    "reconcile_terminal_snapshot",
    "replay_position_accounting",
    "split_signed_exec_cost",
    "update_average_entry",
]
