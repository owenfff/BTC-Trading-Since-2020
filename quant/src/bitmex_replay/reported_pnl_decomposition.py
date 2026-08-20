from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _decimal(value: Any) -> Decimal | None:
    raw = _text(value)
    if not raw:
        return None
    try:
        value = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return value if value.is_finite() else None


def _format(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def decompose_reported_pnl(
    row: dict[str, Any],
    *,
    action: str | None = None,
    reconstructed_gross_realised_pnl_raw: Any = "0",
) -> dict[str, Any]:
    """Compare reported PnL after separating the reported fee component.

    BitMEX's transaction-history realised PnL includes fees/funding.  The
    position replay keeps state independent; this function only diagnoses the
    reported fields and never mutates a position.
    """
    reported = _decimal(row.get("reported_realisedPnl_raw", row.get("realisedPnl_raw")))
    exec_comm = _decimal(row.get("execComm_raw"))
    broker = _decimal(row.get("brokerExecComm_raw", row.get("brokerExecComm")))
    gross = _decimal(reconstructed_gross_realised_pnl_raw) or Decimal(0)
    result: dict[str, Any] = {
        "reported_realised_pnl_raw": _format(reported),
        "exec_comm_raw": _format(exec_comm),
        "broker_exec_comm_raw": _format(broker),
        "reported_fee_component_raw": _format(exec_comm),
        "reported_gross_candidate_raw": None,
        "reconstructed_gross_realised_pnl_raw": _format(gross),
        "reported_gross_difference_raw": None,
        "decomposition_status": "MISSING",
        "decomposition_reason": "reported realisedPnl or execComm is missing",
        "decomposition_eligible": False,
    }
    if reported is None or exec_comm is None:
        return result
    candidate = reported + exec_comm
    result["reported_gross_candidate_raw"] = _format(candidate)
    result["decomposition_eligible"] = True
    if broker not in (None, Decimal(0)):
        result["decomposition_status"] = "BROKER_COMPONENT_UNRESOLVED"
        result["decomposition_reason"] = "brokerExecComm is non-zero; candidate excludes it until broker semantics are confirmed"
        result["reported_gross_difference_raw"] = _format(candidate - gross)
        return result
    event_type = _text(row.get("execType"))
    action = _text(action or row.get("action"))
    non_closing = event_type == "Funding" or action.startswith(("OPEN_", "ADD_")) or action == "NO_POSITION_CHANGE"
    if non_closing:
        difference = candidate
        reason = "non-closing event candidate is expected to be zero"
    else:
        difference = candidate - gross
        reason = "candidate compared with reconstructed gross realised PnL"
    result["reported_gross_difference_raw"] = _format(difference)
    result["decomposition_status"] = "EXACT" if difference == 0 else "MISMATCH"
    result["decomposition_reason"] = reason
    return result


def summarize_reported_pnl_decomposition(rows: list[dict[str, Any]]) -> dict[str, Any]:
    status_counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("decomposition_status", "MISSING"))
        status_counts[status] = status_counts.get(status, 0) + 1
    eligible = sum(bool(row.get("decomposition_eligible")) for row in rows)
    exact = status_counts.get("EXACT", 0)
    mismatch = status_counts.get("MISMATCH", 0)
    unresolved = status_counts.get("BROKER_COMPONENT_UNRESOLVED", 0)
    missing = status_counts.get("MISSING", 0)
    if unresolved:
        status = "BLOCKED"
    elif mismatch:
        status = "READY_WITH_WARNINGS"
    else:
        status = "PASS"
    return {
        "status": status,
        "eligible": eligible,
        "exact": exact,
        "mismatch": mismatch,
        "missing": missing,
        "broker_unresolved": unresolved,
        "status_counts": status_counts,
    }


__all__ = ["decompose_reported_pnl", "summarize_reported_pnl_decomposition"]
