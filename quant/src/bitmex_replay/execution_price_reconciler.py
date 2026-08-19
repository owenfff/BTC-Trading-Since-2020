from __future__ import annotations

import json
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from .io_utils import clean
from .reconciliation import write_csv


EXACT = "EXACT"
RECOVERED = "RECOVERED"
UNRESOLVED = "UNRESOLVED"
OBSERVED_LAST_PX_EXACT = "OBSERVED_LAST_PX_EXACT"
RECOVERED_FROM_EXEC_COST_OFFICIAL_MULTIPLIER = "RECOVERED_FROM_EXEC_COST_OFFICIAL_MULTIPLIER"
OBSERVED_PRICE_COARSENED_BY_ONE_TICK = "OBSERVED_PRICE_COARSENED_BY_ONE_TICK"
OBSERVED_PRICE_COARSENED_BY_HALF_DISPLAY_QUANTUM = "OBSERVED_PRICE_COARSENED_BY_HALF_DISPLAY_QUANTUM"
OFF_TICK_GRID = "OFF_TICK_GRID"

EXECUTION_PRICE_FIELDS = [
    "event_time", "source_row_number", "execID", "symbol", "spec_id", "side",
    "signed_contract_qty", "price", "lastPx", "avgPx", "observed_price", "observed_last_px", "observed_avg_px",
    "execCost", "configured_multiplier_raw", "configured_tick_size", "cost_implied_price", "canonical_execution_price",
    "canonical_execCost_raw", "canonical_exec_cost_exact", "price_delta", "abs_price_delta", "delta_in_ticks",
    "cost_implied_price_on_tick_grid", "observed_last_px_on_tick_grid", "lastPx_expected_execCost_raw",
    "difference_raw", "difference_raw_per_signed_qty", "price_resolution_method", "price_precision_status",
    "reconciliation_status", "reconciliation_reason", "homeNotional", "foreignNotional", "candidate_foreign_over_home",
    "orderID", "trdMatchID", "cumQty", "lastQty",
]

PRECISION_SUMMARY_FIELDS = [
    "spec_id", "symbol", "tick_size", "trade_count", "observed_exact_count", "recovered_count", "unresolved_count",
    "exact_ratio", "recovered_ratio", "cost_implied_on_tick_count", "cost_implied_on_tick_ratio",
    "observed_last_px_on_tick_count", "observed_last_px_on_tick_ratio", "unique_price_deltas", "price_delta_frequency",
    "delta_in_ticks_distribution", "difference_raw_per_signed_qty_frequency", "observed_last_px_decimal_places",
    "cost_implied_price_decimal_places", "canonical_exec_cost_exact_count", "final_status",
]

UNRESOLVED_FIELDS = [
    "event_time", "source_row_number", "execID", "symbol", "side", "signed_contract_qty", "observed_last_px",
    "cost_implied_price", "configured_tick_size", "price_delta", "delta_in_ticks", "lastPx_expected_execCost_raw",
    "execCost", "reconciliation_reason",
]


def _decimal(value: Any) -> Decimal | None:
    if value is None or not clean(value).strip():
        return None
    try:
        number = Decimal(clean(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _decimal_text(value: Decimal | None) -> str | None:
    return format(value, "f") if value is not None else None


def _normalized_decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    if value == 0:
        return "0"
    normalized = value.normalize()
    return format(normalized, "f")


def _magnitude(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return value if value >= 0 else -value


def _decimal_places(value: Decimal | None) -> str | None:
    if value is None:
        return None
    exponent = value.as_tuple().exponent
    return str(-exponent) if exponent < 0 else "0"


def _event_mapping(mapping_rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        clean(row.get("execID")).strip(): row
        for row in mapping_rows
        if clean(row.get("execID")).strip()
    }


def _configured_spec_ids(registry: dict[str, Any]) -> set[str]:
    configured = registry.get("configured_specs")
    specs = configured if isinstance(configured, list) else registry.get("specs", [])
    return {clean(spec.get("spec_id")).strip() for spec in specs if clean(spec.get("spec_id")).strip()}


def derive_cost_implied_price(
    actual_exec_cost_raw: Any,
    signed_contract_qty: Any,
    multiplier_raw: Any,
    payout_model: str = "QUANTO",
) -> Decimal:
    """Derive the price used by the raw execution-cost identity with Decimal only."""

    actual = _decimal(actual_exec_cost_raw)
    quantity = _decimal(signed_contract_qty)
    multiplier = _decimal(multiplier_raw)
    if actual is None or quantity is None or quantity == 0 or multiplier is None or multiplier == 0:
        raise ValueError("execCost, signed quantity and non-zero multiplier are required")
    if clean(payout_model).strip().upper() == "INVERSE":
        if actual == 0:
            raise ValueError("inverse execution cost must be non-zero")
        return quantity * multiplier / actual
    return actual / (quantity * multiplier)


def _expected_exec_cost(price: Decimal, quantity: Decimal, multiplier: Decimal, payout_model: str) -> Decimal:
    if clean(payout_model).strip().upper() == "INVERSE":
        if price == 0:
            raise ValueError("inverse price must be non-zero")
        return quantity * multiplier / price
    return quantity * multiplier * price


def validate_price_tick_grid(price: Any, tick_size: Any) -> bool:
    """Return true only when the Decimal price is exactly on the configured grid."""

    parsed_price = _decimal(price)
    parsed_tick = _decimal(tick_size)
    return parsed_price is not None and parsed_tick is not None and parsed_tick > 0 and parsed_price % parsed_tick == 0


def classify_price_precision_difference(observed_last_px: Any, cost_implied_price: Any, tick_size: Any) -> str:
    """Classify only exact grid relationships; never use a tolerance or rounding choice."""

    observed = _decimal(observed_last_px)
    implied = _decimal(cost_implied_price)
    tick = _decimal(tick_size)
    if observed is None or implied is None:
        return UNRESOLVED
    if observed == implied:
        return EXACT
    if tick is None or tick <= 0:
        return UNRESOLVED
    delta = implied - observed
    if validate_price_tick_grid(implied, tick) and validate_price_tick_grid(observed, tick) and delta in {tick, -tick}:
        return RECOVERED
    if not validate_price_tick_grid(implied, tick) or not validate_price_tick_grid(observed, tick):
        return OFF_TICK_GRID
    return UNRESOLVED


def _candidate_foreign_over_home(event: dict[str, Any]) -> Decimal | None:
    foreign = _decimal(event.get("foreignNotional"))
    home = _decimal(event.get("homeNotional"))
    if foreign is None or home is None or home == 0:
        return None
    return foreign / home


def reconcile_execution_price(event: dict[str, Any], spec: dict[str, Any]) -> dict[str, Any]:
    """Reconcile one configured historical derivative Trade."""

    quantity = _decimal(event.get("signed_contract_qty"))
    observed_last = _decimal(event.get("lastPx"))
    actual_cost = _decimal(event.get("execCost"))
    multiplier = _decimal(spec.get("multiplier_raw"))
    tick = _decimal(spec.get("tick_size"))
    payout_model = clean(spec.get("payout_model")).strip()
    implied: Decimal | None = None
    canonical_cost: Decimal | None = None
    reason = ""
    if quantity is None or quantity == 0:
        reason = "signed_contract_qty missing or zero"
    elif actual_cost is None:
        reason = "execCost missing or not a finite Decimal"
    elif multiplier is None or multiplier == 0:
        reason = "configured multiplier_raw missing or zero"
    else:
        try:
            implied = derive_cost_implied_price(actual_cost, quantity, multiplier, payout_model)
            canonical_cost = _expected_exec_cost(implied, quantity, multiplier, payout_model)
        except (ArithmeticError, InvalidOperation, ValueError):
            reason = "cost_implied_price derivation failed"

    price_delta = implied - observed_last if implied is not None and observed_last is not None else None
    absolute_delta = _magnitude(price_delta)
    observed_expected_cost = None
    difference_raw = None
    difference_per_quantity = None
    if observed_last is not None and quantity is not None and multiplier is not None:
        try:
            observed_expected_cost = _expected_exec_cost(observed_last, quantity, multiplier, payout_model)
            difference_raw = actual_cost - observed_expected_cost if actual_cost is not None else None
            difference_per_quantity = difference_raw / quantity if difference_raw is not None and quantity != 0 else None
        except (ArithmeticError, InvalidOperation, ValueError):
            observed_expected_cost = None

    tick_grid_implied = validate_price_tick_grid(implied, tick) if tick is not None else False
    tick_grid_observed = validate_price_tick_grid(observed_last, tick) if tick is not None else False
    delta_ticks = price_delta / tick if price_delta is not None and tick is not None and price_delta % tick == 0 else None
    precision_status = classify_price_precision_difference(observed_last, implied, tick)
    official_recovery_allowed = (
        clean(spec.get("evidence_confidence")).strip() == "OFFICIAL_EXPLICIT"
        and clean(spec.get("tick_size_evidence_confidence")).strip() == "OFFICIAL_EXPLICIT"
        and tick is not None
    )
    if implied is None or canonical_cost != actual_cost:
        precision_status = UNRESOLVED
        reason = reason or "canonical price cannot exactly reproduce execCost"
    elif observed_last is None:
        precision_status = UNRESOLVED
        reason = "lastPx missing or not a finite Decimal"
    elif precision_status == EXACT:
        resolution_method = OBSERVED_LAST_PX_EXACT
    elif precision_status == RECOVERED and official_recovery_allowed:
        resolution_method = RECOVERED_FROM_EXEC_COST_OFFICIAL_MULTIPLIER
        precision_status = OBSERVED_PRICE_COARSENED_BY_ONE_TICK
    elif precision_status == OFF_TICK_GRID:
        resolution_method = UNRESOLVED
        reason = reason or "observed_last_px or cost_implied_price is off the configured tick grid"
    else:
        resolution_method = UNRESOLVED
        reason = reason or "price_delta is not exactly one official execution tick"
        precision_status = UNRESOLVED

    resolved = resolution_method in {OBSERVED_LAST_PX_EXACT, RECOVERED_FROM_EXEC_COST_OFFICIAL_MULTIPLIER}
    canonical = implied if resolved else None
    reconciliation_status = "PASS" if resolved and canonical_cost == actual_cost else UNRESOLVED
    return {
        "event_time": event.get("event_time", ""), "source_row_number": event.get("source_row_number"),
        "execID": event.get("execID", ""), "symbol": event.get("symbol", ""), "spec_id": spec.get("spec_id", ""),
        "side": event.get("side", ""), "signed_contract_qty": _decimal_text(quantity),
        "price": event.get("price", ""), "lastPx": event.get("lastPx", ""), "avgPx": event.get("avgPx", ""),
        "observed_price": event.get("price", ""), "observed_last_px": _decimal_text(observed_last),
        "observed_avg_px": event.get("avgPx", ""), "execCost": _decimal_text(actual_cost),
        "configured_multiplier_raw": _decimal_text(multiplier), "configured_tick_size": _decimal_text(tick),
        "cost_implied_price": _decimal_text(implied), "canonical_execution_price": _decimal_text(canonical),
        "canonical_execCost_raw": _decimal_text(canonical_cost), "canonical_exec_cost_exact": canonical_cost == actual_cost and canonical_cost is not None,
        "price_delta": _decimal_text(price_delta), "abs_price_delta": _decimal_text(absolute_delta),
        "delta_in_ticks": _decimal_text(delta_ticks), "cost_implied_price_on_tick_grid": tick_grid_implied,
        "observed_last_px_on_tick_grid": tick_grid_observed, "lastPx_expected_execCost_raw": _decimal_text(observed_expected_cost),
        "difference_raw": _decimal_text(difference_raw), "difference_raw_per_signed_qty": _decimal_text(difference_per_quantity),
        "price_resolution_method": resolution_method, "price_precision_status": precision_status,
        "reconciliation_status": reconciliation_status, "reconciliation_reason": reason,
        "homeNotional": event.get("homeNotional", ""), "foreignNotional": event.get("foreignNotional", ""),
        "candidate_foreign_over_home": _decimal_text(_candidate_foreign_over_home(event)),
        "orderID": event.get("orderID", ""), "trdMatchID": event.get("trdMatchID", ""),
        "cumQty": event.get("cumQty", ""), "lastQty": event.get("lastQty", ""),
    }


def reconcile_execution_prices(normalized_events: Iterable[dict[str, Any]], registry: dict[str, Any], mapping_rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """Reconcile every configured historical derivative Trade, excluding spot/funding/settlement."""

    mapping_by_exec = _event_mapping(mapping_rows)
    specs = {clean(spec.get("spec_id")).strip(): spec for spec in registry.get("specs", []) if clean(spec.get("spec_id")).strip()}
    configured_ids = _configured_spec_ids(registry)
    rows: list[dict[str, Any]] = []
    for event in normalized_events:
        if event.get("instrument_class") != "DERIVATIVE" or event.get("execType") != "Trade":
            continue
        mapping = mapping_by_exec.get(clean(event.get("execID")).strip()) or {}
        spec_id = clean(mapping.get("spec_id")).strip()
        if spec_id in configured_ids and spec_id in specs:
            rows.append(reconcile_execution_price(event, specs[spec_id]))

    by_spec: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_spec[row["spec_id"]].append(row)
    summary_by_spec: dict[str, dict[str, Any]] = {}
    candidate_diagnostics: dict[str, dict[str, Any]] = {}
    for spec_id, spec_rows in sorted(by_spec.items()):
        status_counts = Counter(row["price_precision_status"] for row in spec_rows)
        price_deltas = Counter(_normalized_decimal_text(_decimal(row["price_delta"])) for row in spec_rows if row["price_delta"] is not None)
        delta_ticks = Counter(_normalized_decimal_text(_decimal(row["delta_in_ticks"])) for row in spec_rows if row["delta_in_ticks"] is not None)
        difference_per_qty = Counter(_normalized_decimal_text(_decimal(row["difference_raw_per_signed_qty"])) for row in spec_rows if row["difference_raw_per_signed_qty"] is not None)
        observed_places = Counter(_decimal_places(_decimal(row["observed_last_px"])) for row in spec_rows)
        implied_places = Counter(_decimal_places(_decimal(row["cost_implied_price"])) for row in spec_rows)
        implied_on_tick = sum(row["cost_implied_price_on_tick_grid"] for row in spec_rows)
        observed_on_tick = sum(row["observed_last_px_on_tick_grid"] for row in spec_rows)
        exact = status_counts.get(EXACT, 0)
        recovered = status_counts.get(OBSERVED_PRICE_COARSENED_BY_ONE_TICK, 0)
        unresolved_count = len(spec_rows) - exact - recovered
        summary_by_spec[spec_id] = {
            "spec_id": spec_id, "symbol": spec_rows[0]["symbol"], "tick_size": spec_rows[0]["configured_tick_size"],
            "trade_count": len(spec_rows), "observed_exact_count": exact, "recovered_count": recovered, "unresolved_count": unresolved_count,
            "exact_ratio": f"{Decimal(exact) / Decimal(len(spec_rows)):.12f}" if spec_rows else "0",
            "recovered_ratio": f"{Decimal(recovered) / Decimal(len(spec_rows)):.12f}" if spec_rows else "0",
            "cost_implied_on_tick_count": implied_on_tick,
            "cost_implied_on_tick_ratio": f"{Decimal(implied_on_tick) / Decimal(len(spec_rows)):.12f}" if spec_rows else "0",
            "observed_last_px_on_tick_count": observed_on_tick,
            "observed_last_px_on_tick_ratio": f"{Decimal(observed_on_tick) / Decimal(len(spec_rows)):.12f}" if spec_rows else "0",
            "unique_price_deltas": sorted(price_deltas), "price_delta_frequency": dict(sorted(price_deltas.items())),
            "delta_in_ticks_distribution": dict(sorted(delta_ticks.items())),
            "difference_raw_per_signed_qty_frequency": dict(sorted(difference_per_qty.items())),
            "observed_last_px_decimal_places": dict(sorted(observed_places.items(), key=lambda item: str(item[0]))),
            "cost_implied_price_decimal_places": dict(sorted(implied_places.items(), key=lambda item: str(item[0]))),
            "canonical_exec_cost_exact_count": sum(row["canonical_exec_cost_exact"] for row in spec_rows),
            "final_status": "PASS" if unresolved_count == 0 else "UNRESOLVED",
        }
        candidate_diagnostics[spec_id] = _build_candidate_diagnostics(spec_rows)

    unresolved = [row for row in rows if row["reconciliation_status"] != "PASS"]
    status_counts = Counter(row["price_precision_status"] for row in rows)
    return {
        "report_version": "M0-02B-0.2/1.0",
        "formula": "Quanto: execCost / (signed_contract_qty * multiplier_raw); Inverse: signed_contract_qty * multiplier_raw / execCost",
        "comparison_policy": "EXACT equality; recovered only with official tick-grid equality and an exact signed one-tick delta; no tolerance or rounding selection",
        "rows": rows, "unresolved": unresolved,
        "summary": {
            "trade_count": len(rows), "exact_count": status_counts.get(EXACT, 0),
            "recovered_count": status_counts.get(OBSERVED_PRICE_COARSENED_BY_ONE_TICK, 0), "unresolved_count": len(unresolved),
            "raw_lastPx_mismatch_count": sum(_decimal(row["lastPx_expected_execCost_raw"]) != _decimal(row["execCost"]) for row in rows),
            "canonical_reproduction_fail_count": sum(not row["canonical_exec_cost_exact"] for row in rows if row["reconciliation_status"] == "PASS"),
            "status_counts": dict(status_counts), "by_spec": summary_by_spec, "candidate_diagnostics": candidate_diagnostics,
        },
    }


def _build_candidate_diagnostics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    mismatch_rows = [row for row in rows if row["lastPx_expected_execCost_raw"] != row["execCost"]]
    candidates = {
        "lastPx": ("observed_last_px", "public Execution price; may have display precision loss"),
        "avgPx": ("observed_avg_px", "execution-average field; not assumed to equal a single Trade price"),
        "price": ("observed_price", "order/execution price field; not promoted without exact semantic proof"),
        "cost_implied_price": ("cost_implied_price", "derived from account-cost identity; canonical only after official-price rules"),
        "foreignNotional_over_homeNotional": ("candidate_foreign_over_home", "not used unless quote/base semantics and sign are valid"),
    }
    result: dict[str, Any] = {}
    for name, (field, note) in candidates.items():
        available = [row for row in mismatch_rows if _decimal(row.get(field)) is not None]
        result[name] = {
            "available_count": len(available),
            "exact_match_to_cost_implied_count": sum(_decimal(row.get(field)) == _decimal(row.get("cost_implied_price")) for row in available),
            "semantic_note": note,
        }
    result["mismatch_count"] = len(mismatch_rows)
    return result


def build_price_precision_report(reconciliation: dict[str, Any]) -> dict[str, Any]:
    return build_execution_price_precision_report(reconciliation)


def build_execution_price_precision_report(reconciliation: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_version": reconciliation.get("report_version", "M0-02B-0.2/1.0"),
        "formula": reconciliation.get("formula", ""),
        "comparison_policy": reconciliation.get("comparison_policy", ""),
        "summary": reconciliation.get("summary", {}),
        "trades": reconciliation.get("rows", []),
        "unresolved": reconciliation.get("unresolved", []),
    }


def write_execution_price_reports(reconciliation: dict[str, Any], reports_dir: Path, *, source: dict[str, Any] | None = None) -> dict[str, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    rows = reconciliation.get("rows", [])
    unresolved = reconciliation.get("unresolved", [])
    summary_rows = list(reconciliation.get("summary", {}).get("by_spec", {}).values())
    csv_path = reports_dir / "execution_price_precision.csv"
    detail_path = reports_dir / "execution_price_precision_trades.csv"
    unresolved_path = reports_dir / "unresolved.csv"
    unresolved_compat_path = reports_dir / "execution_price_unresolved.csv"
    json_path = reports_dir / "execution_price_precision.json"
    md_path = reports_dir / "execution_price_precision.md"
    write_csv(summary_rows, csv_path, PRECISION_SUMMARY_FIELDS)
    write_csv(rows, detail_path, EXECUTION_PRICE_FIELDS)
    unresolved_sample = unresolved[:200]
    write_csv(unresolved_sample, unresolved_path, UNRESOLVED_FIELDS)
    write_csv(unresolved_sample, unresolved_compat_path, UNRESOLVED_FIELDS)
    report = build_execution_price_precision_report(reconciliation)
    if source:
        report["source"] = source
    json_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    summary = reconciliation.get("summary", {})
    lines = [
        "# M0-02B-0.2 Historical Execution Price Precision", "",
        f"- Formula: `{reconciliation.get('formula', '')}`",
        f"- Policy: {reconciliation.get('comparison_policy', '')}",
        f"- Configured historical Trade rows: **{summary.get('trade_count', 0)}**",
        f"- EXACT: **{summary.get('exact_count', 0)}**",
        f"- RECOVERED: **{summary.get('recovered_count', 0)}**",
        f"- UNRESOLVED: **{summary.get('unresolved_count', 0)}**",
        f"- Raw lastPx mismatches: **{summary.get('raw_lastPx_mismatch_count', 0)}**", "",
        "## Per-spec summary", "",
        "| Spec | Symbol | Trades | EXACT | RECOVERED | UNRESOLVED | Tick | Implied on grid | Canonical exact | Status |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    for item in summary_rows:
        lines.append(
            f"| {item['spec_id']} | {item['symbol']} | {item['trade_count']} | {item['observed_exact_count']} | {item['recovered_count']} | "
            f"{item['unresolved_count']} | {item.get('tick_size') or ''} | {item['cost_implied_on_tick_ratio']} | "
            f"{item['canonical_exec_cost_exact_count']} | {item['final_status']} |"
        )
    lines.extend(["", "## Candidate-field diagnostics", "", "The candidate fields are diagnostic only: `avgPx` is not assumed to equal a single Trade price; `price` is not automatically a fill price; notional ratios require instrument and sign semantics; `cost_implied_price` is derived from the account-cost identity.", ""])
    for spec_id, diagnostics in sorted(summary.get("candidate_diagnostics", {}).items()):
        lines.extend([f"### {spec_id}", "", "| Candidate | Available in raw mismatch rows | Exact to cost-implied | Semantic note |", "| --- | ---: | ---: | --- |"])
        for name, item in diagnostics.items():
            if name != "mismatch_count":
                lines.append(f"| {name} | {item['available_count']} | {item['exact_match_to_cost_implied_count']} | {item['semantic_note']} |")
        lines.append("")
    lines.extend(["The complete configured-history per-Trade fields, including original `lastPx` and `canonical_execution_price`, are in `execution_price_precision_trades.csv` and the `trades` array in JSON. `unresolved.csv` is capped at 200 samples and is empty when all configured historical rows resolve.", ""])
    md_path.write_text("\n".join(lines), encoding="utf-8")
    return {"csv": csv_path, "detail_csv": detail_path, "json": json_path, "md": md_path, "unresolved": unresolved_path, "unresolved_compat": unresolved_compat_path}


__all__ = [
    "EXACT", "EXECUTION_PRICE_FIELDS", "OFF_TICK_GRID", "OBSERVED_LAST_PX_EXACT",
    "OBSERVED_PRICE_COARSENED_BY_HALF_DISPLAY_QUANTUM", "OBSERVED_PRICE_COARSENED_BY_ONE_TICK", "RECOVERED",
    "RECOVERED_FROM_EXEC_COST_OFFICIAL_MULTIPLIER", "UNRESOLVED", "build_execution_price_precision_report",
    "build_price_precision_report", "classify_price_precision_difference", "derive_cost_implied_price",
    "reconcile_execution_price", "reconcile_execution_prices", "validate_price_tick_grid", "write_execution_price_reports",
]
