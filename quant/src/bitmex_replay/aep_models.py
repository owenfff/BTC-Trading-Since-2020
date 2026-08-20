from __future__ import annotations

from collections import Counter
from decimal import Decimal, ROUND_FLOOR, ROUND_HALF_UP
from typing import Any, Iterable


AEP_MODELS = (
    "PUBLISHED_FILL_WEIGHTED_BASIS",
    "RUNNING_BASIS_QUANTIZED_EACH_EXECUTION",
    "RUNNING_BASIS_QUANTIZED_EACH_ORDER",
    "RECOMPUTE_FROM_OPEN_FILL_LOTS",
    "COST_IMPLIED_BASIS",
)


def quantize_inverse_basis(value: Decimal, direction: int, decimal_places: int = 8) -> Decimal:
    quantum = Decimal(1) / (Decimal(10) ** decimal_places)
    return value.quantize(quantum, rounding=ROUND_FLOOR if direction > 0 else ROUND_HALF_UP)


def cost_implied_basis(current_cost_raw: Any, position_qty: Any, lot_size: Any) -> Decimal | None:
    try:
        cost = Decimal(str(current_cost_raw))
        qty = abs(Decimal(str(position_qty)))
        lot = Decimal(str(lot_size))
        if qty == 0 or lot <= 0 or cost == 0:
            return None
        return abs(cost) / qty
    except Exception:
        return None


def audit_aep_models(
    rows: Iterable[dict[str, Any]],
    *,
    symbol: str = "XBTUSD",
    snapshot_aep: Any = None,
    snapshot_avg_cost: Any = None,
) -> list[dict[str, Any]]:
    rows = [row for row in rows if row.get("symbol") == symbol]
    last = rows[-1] if rows else {}
    published = last.get("average_entry_price_after")
    displayed = None
    if published not in (None, ""):
        try:
            displayed = Decimal(str(published)).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        except Exception:
            displayed = None
    results: list[dict[str, Any]] = []
    for model in AEP_MODELS:
        if model == "COST_IMPLIED_BASIS":
            exact = cost_implied_basis(last.get("current_cost_after_api_raw"), last.get("position_after"), last.get("resolved_lot_size") or 100)
            price = str(exact) if exact is not None else None
            evidence = "DIAGNOSTIC_ONLY_NOT_A_STATE_DRIVER"
        else:
            price = published
            exact = Decimal(str(price)) if price not in (None, "") else None
            evidence = "PUBLISHED_MODEL" if model == "PUBLISHED_FILL_WEIGHTED_BASIS" else "DIAGNOSTIC_REPLAY_GRANULARITY_MODEL"
        difference = None
        if snapshot_aep not in (None, "") and displayed is not None:
            difference = str(displayed - Decimal(str(snapshot_aep)))
        results.append({
            "model": model,
            "state_semantics": evidence,
            "cycle_symbol": symbol,
            "current_aep_exact": str(exact) if exact is not None else None,
            "current_aep_displayed": str(displayed) if displayed is not None else None,
            "snapshot_avgEntryPrice": str(snapshot_aep) if snapshot_aep not in (None, "") else None,
            "snapshot_avgCostPrice": str(snapshot_avg_cost) if snapshot_avg_cost not in (None, "") else None,
            "snapshot_display_difference": difference,
            "status": "PASS" if model == "PUBLISHED_FILL_WEIGHTED_BASIS" else "DIAGNOSTIC_ONLY",
        })
    return results


def current_cycle_summary(rows: Iterable[dict[str, Any]], symbol: str = "XBTUSD") -> dict[str, Any]:
    rows = [row for row in rows if row.get("symbol") == symbol]
    nonzero = [row for row in rows if int(row.get("position_after") or 0) != 0]
    if not nonzero:
        return {"symbol": symbol, "cycle_id": "", "cycle_open_time": "", "cycle_open_execID": "", "execution_count": 0}
    cycle_id = nonzero[-1].get("position_cycle_id", "")
    cycle_rows = [row for row in nonzero if row.get("position_cycle_id") == cycle_id]
    opening = next((row for row in cycle_rows if row.get("opening_cycle_id") == cycle_id), cycle_rows[0])
    return {
        "symbol": symbol,
        "cycle_id": cycle_id,
        "cycle_open_time": opening.get("event_time", ""),
        "cycle_open_execID": opening.get("execID", ""),
        "execution_count": len(cycle_rows),
        "first_event_time": cycle_rows[0].get("event_time", ""),
        "last_event_time": cycle_rows[-1].get("event_time", ""),
        "lot_size_versions": ",".join(sorted({str(row.get("resolved_lot_size", "")) for row in cycle_rows if row.get("resolved_lot_size") not in (None, "")})),
        "order_tie_count": sum(row.get("execution_order_chain_status") not in (None, "", "NOT_IN_MULTI_TRADE_GROUP") for row in cycle_rows),
        "price_provenance_counts": dict(Counter(str(row.get("canonical_price_status", "")) for row in cycle_rows)),
        "terminal_position": cycle_rows[-1].get("position_after", ""),
        "terminal_current_cost_api_raw": cycle_rows[-1].get("current_cost_after_api_raw", ""),
        "terminal_aep": cycle_rows[-1].get("average_entry_price_after", ""),
    }


__all__ = ["AEP_MODELS", "audit_aep_models", "cost_implied_basis", "current_cycle_summary", "quantize_inverse_basis"]
