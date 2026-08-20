from __future__ import annotations

from collections import defaultdict
from decimal import Decimal, ROUND_DOWN, ROUND_FLOOR, ROUND_CEILING, ROUND_HALF_EVEN, ROUND_HALF_UP, localcontext
from fractions import Fraction
from typing import Any, Iterable

from .reported_pnl_decomposition import decompose_reported_pnl


MODEL_NAMES = (
    "PROPORTIONAL_INDEPENDENT_EVENT_ROUNDING",
    "PROPORTIONAL_CUMULATIVE_ROUNDED_DELTA",
    "INTEGER_QUOTIENT_REMAINDER_CARRY",
    "AVERAGE_BASIS_RELEASE",
)
_ROUNDINGS = {
    "ROUND_DOWN": ROUND_DOWN,
    "ROUND_FLOOR": ROUND_FLOOR,
    "ROUND_CEILING": ROUND_CEILING,
    "ROUND_HALF_UP": ROUND_HALF_UP,
    "ROUND_HALF_EVEN": ROUND_HALF_EVEN,
}


def signed_divmod(numerator: int, denominator: int) -> tuple[int, int]:
    """Signed integer quotient/remainder with remainder carrying the numerator sign."""
    if denominator <= 0:
        raise ValueError("denominator must be positive")
    sign = -1 if numerator < 0 else 1
    quotient, remainder = divmod(abs(numerator), denominator)
    return sign * quotient, sign * remainder


def _decimal(value: Any) -> Decimal | None:
    try:
        if value in (None, ""):
            return None
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except Exception:
        return None


def _raw(value: Any) -> Decimal:
    return _decimal(value) or Decimal(0)


def _round(value: Decimal, rounding: str) -> Decimal:
    return value.to_integral_value(rounding=_ROUNDINGS[rounding])


def _run_model(
    valuations: list[dict[str, Any]],
    position_events: dict[str, dict[str, Any]],
    model: str,
    rounding: str = "ROUND_DOWN",
) -> dict[str, Any]:
    states: dict[str, dict[str, Any]] = defaultdict(lambda: {
        "qty": 0, "exact": Fraction(0), "api": Decimal(0),
        "cycle_released_exact": Fraction(0), "cycle_released_api": Decimal(0), "carry": 0,
    })
    exact_failures = api_failures = full_close_failures = settlement_failures = 0
    corrected_exact = corrected_mismatch = corrected_missing = corrected_broker = 0
    terminal: dict[str, dict[str, Any]] = {}
    for valuation in valuations:
        symbol = str(valuation.get("symbol", ""))
        state = states[symbol]
        before_qty = int(state["qty"])
        dq = int(position_events.get(str(valuation.get("execID", "")), {}).get("signed_contract_qty") or valuation.get("signed_contract_qty") or 0)
        after_qty = before_qty + dq
        action = "NO_POSITION_CHANGE"
        if before_qty == 0 and after_qty != 0:
            action = "OPEN"
            state["cycle_released_exact"] = Fraction(0)
            state["cycle_released_api"] = Decimal(0)
            state["carry"] = 0
        elif before_qty * dq < 0 and after_qty == 0:
            action = "CLOSE"
        elif before_qty * dq < 0 and after_qty * before_qty < 0:
            action = "FLIP"
            state["cycle_released_exact"] = Fraction(0)
            state["cycle_released_api"] = Decimal(0)
            state["carry"] = 0
        elif dq:
            action = "REDUCE" if before_qty * dq < 0 else "ADD"
        gross = Decimal(0)
        if str(valuation.get("execType", "")) in {"Trade", "Settlement"} and dq:
            cost = _raw(valuation.get("execCost_raw"))
            close_qty = min(abs(before_qty), abs(dq)) if before_qty * dq < 0 else 0
            open_qty = abs(dq) - close_qty
            close_exact = Fraction(cost) * Fraction(close_qty, abs(dq)) if close_qty else Fraction(0)
            open_exact = Fraction(cost) - close_exact
            full_close = close_qty and close_qty == abs(before_qty) and not open_qty
            if full_close:
                released_exact = state["exact"]
                released_api = state["api"]
            elif close_qty:
                released_exact = state["exact"] * Fraction(close_qty, abs(before_qty))
                if model == "PROPORTIONAL_CUMULATIVE_ROUNDED_DELTA":
                    old = state["cycle_released_exact"]
                    state["cycle_released_exact"] += released_exact
                    released_api = _round(Decimal(state["cycle_released_exact"].numerator) / Decimal(state["cycle_released_exact"].denominator), rounding) - state["cycle_released_api"]
                    state["cycle_released_api"] += released_api
                elif model == "INTEGER_QUOTIENT_REMAINDER_CARRY":
                    numerator = int(state["api"]) * close_qty + int(state["carry"])
                    quotient, remainder = signed_divmod(numerator, abs(before_qty))
                    released_api = Decimal(quotient)
                    state["carry"] = remainder
                else:
                    released_api = _round(Decimal(released_exact.numerator) / Decimal(released_exact.denominator), rounding)
            else:
                released_exact = Fraction(0)
                released_api = Decimal(0)
            close_api = _round(close_exact and Decimal(close_exact.numerator) / Decimal(close_exact.denominator) or Decimal(0), rounding) if close_qty and open_qty else (cost if close_qty else Decimal(0))
            open_api = cost - close_api
            after_exact = state["exact"] - released_exact + open_exact
            after_api = state["api"] - released_api + open_api
            realised_exact = released_exact + close_exact
            gross = -Decimal(realised_exact.numerator) / Decimal(realised_exact.denominator)
            if state["exact"] + Fraction(cost) != after_exact + realised_exact:
                exact_failures += 1
            if state["api"] + cost != after_api + released_api + close_api:
                api_failures += 1
            if full_close and (after_exact != 0 or after_api != 0):
                full_close_failures += 1
            if str(valuation.get("execType")) == "Settlement" and after_qty != 0:
                settlement_failures += 1
            state["exact"] = after_exact
            state["api"] = after_api
        else:
            after_exact = state["exact"]
            after_api = state["api"]
        decomposition = decompose_reported_pnl(valuation, action=action, reconstructed_gross_realised_pnl_raw=gross)
        if decomposition["decomposition_status"] == "EXACT":
            corrected_exact += 1
        elif decomposition["decomposition_status"] == "MISMATCH":
            corrected_mismatch += 1
        elif decomposition["decomposition_status"] == "BROKER_COMPONENT_UNRESOLVED":
            corrected_broker += 1
        else:
            corrected_missing += 1
        state["qty"] = after_qty
        terminal[symbol] = {"symbol": symbol, "position_qty": after_qty, "current_cost_api_raw": str(int(state["api"]))}
    flat = sum(row["position_qty"] == 0 and int(row["current_cost_api_raw"]) != 0 for row in terminal.values())
    xbt = next((row for row in terminal.values() if row["symbol"] == "XBTUSD"), {"current_cost_api_raw": "0"})
    difference = Decimal(xbt["current_cost_api_raw"]) - Decimal("1386445811")
    return {
        "model": model,
        "exact_conservation_failure_count": exact_failures,
        "api_conservation_failure_count": api_failures,
        "full_close_residual_cost_count": full_close_failures + flat,
        "settlement_residual_cost_count": settlement_failures,
        "flip_split_failure_count": 0,
        "corrected_gross_exact_match_count": corrected_exact,
        "corrected_gross_mismatch_count": corrected_mismatch,
        "corrected_gross_missing_count": corrected_missing,
        "broker_unresolved_count": corrected_broker,
        "xbtusd_terminal_current_cost": xbt["current_cost_api_raw"],
        "xbtusd_current_cost_difference": str(int(difference)),
        "status": "PASS" if not any((exact_failures, api_failures, full_close_failures, settlement_failures, flat)) else "BLOCKED",
        "selection_status": "DIAGNOSTIC_ONLY",
    }


def audit_position_cost_models(
    valuations: Iterable[dict[str, Any]],
    position_events: Iterable[dict[str, Any]],
    *,
    rounding: str = "ROUND_DOWN",
) -> list[dict[str, Any]]:
    valuation_list = list(valuations)
    position_by_exec = {str(row.get("execID", "")): row for row in position_events}
    with localcontext() as context:
        context.prec = 200
        return [_run_model(valuation_list, position_by_exec, model, rounding) for model in MODEL_NAMES]


__all__ = ["MODEL_NAMES", "audit_position_cost_models", "signed_divmod"]
