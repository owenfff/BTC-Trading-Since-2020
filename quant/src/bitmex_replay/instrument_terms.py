from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

from .io_utils import clean, parse_datetime


class InstrumentTermsError(ValueError):
    pass


def load_historical_instrument_terms(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    terms = payload.get("terms") if isinstance(payload, dict) else None
    if not isinstance(terms, list):
        raise InstrumentTermsError("historical instrument terms must contain a terms list")
    normalized: list[dict[str, Any]] = []
    for term in terms:
        row = dict(term)
        row["symbol"] = clean(row.get("symbol")).strip()
        row["term_id"] = clean(row.get("term_id")).strip()
        row["valid_from"] = clean(row.get("valid_from")).strip()
        row["valid_to_exclusive"] = clean(row.get("valid_to_exclusive")).strip()
        row["lot_size"] = clean(row.get("lot_size")).strip()
        start = parse_datetime(row["valid_from"])
        end = parse_datetime(row["valid_to_exclusive"])
        if not row["symbol"] or not row["term_id"] or start is None or end is None or not start < end:
            raise InstrumentTermsError(f"invalid historical instrument term: {term!r}")
        try:
            lot_size = int(row["lot_size"])
        except ValueError as exc:
            raise InstrumentTermsError(f"invalid lot_size in {term!r}") from exc
        if lot_size <= 0:
            raise InstrumentTermsError(f"lot_size must be positive in {term!r}")
        row["_start"] = start
        row["_end"] = end
        normalized.append(row)
    by_symbol: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for term in normalized:
        by_symbol[term["symbol"]].append(term)
    errors: list[str] = []
    for symbol, rows in by_symbol.items():
        rows.sort(key=lambda item: (item["_start"], item["term_id"]))
        for previous, current in zip(rows, rows[1:]):
            if current["_start"] < previous["_end"]:
                errors.append(f"{symbol}: overlapping terms {previous['term_id']} and {current['term_id']}")
    if errors:
        raise InstrumentTermsError("; ".join(errors))
    return {
        "schema_version": payload.get("schema_version", ""),
        "config_path": str(Path(path)),
        "terms": normalized,
        "terms_by_symbol": dict(by_symbol),
    }


def resolve_instrument_terms(registry: Any, symbol: str, event_time: Any) -> dict[str, Any]:
    event_dt = event_time if isinstance(event_time, datetime) else parse_datetime(event_time)
    symbol = clean(symbol).strip()
    if event_dt is None:
        return {"status": "UNRESOLVED_EVENT_TIME", "term": None, "reason": "event time is not parseable"}
    candidates = []
    for term in (registry or {}).get("terms_by_symbol", {}).get(symbol, []):
        if term["_start"] <= event_dt < term["_end"]:
            candidates.append(term)
    if len(candidates) == 1:
        term = candidates[0]
        return {
            "status": "MATCHED",
            "term": term,
            "term_id": term["term_id"],
            "lot_size": term["lot_size"],
            "reason": "exact temporal instrument terms match",
        }
    if not candidates:
        return {"status": "MISSING", "term": None, "reason": "no temporal lot-size term matched"}
    return {"status": "AMBIGUOUS", "term": None, "reason": "multiple temporal lot-size terms matched"}


def audit_instrument_terms(events: Iterable[dict[str, Any]], registry: dict[str, Any]) -> list[dict[str, Any]]:
    terms_registry = registry.get("instrument_terms", registry) if isinstance(registry, dict) else registry
    full_specs = registry.get("specs", []) if isinstance(registry, dict) else []
    rows: list[dict[str, Any]] = []
    for event in events:
        if event.get("instrument_class") != "DERIVATIVE":
            continue
        resolution = resolve_instrument_terms(terms_registry, event.get("symbol"), event.get("_event_dt") or event.get("event_time"))
        if resolution.get("status") == "MISSING":
            event_dt = event.get("_event_dt")
            fallback_specs = []
            for spec in full_specs:
                if str(spec.get("symbol", "")) != str(event.get("symbol", "")):
                    continue
                start = parse_datetime(spec.get("valid_from"))
                end = parse_datetime(spec.get("valid_to_exclusive"))
                if event_dt is not None and start is not None and end is not None and start <= event_dt < end:
                    fallback_specs.append(spec)
            if len(fallback_specs) == 1 and fallback_specs[0].get("lot_size") not in (None, ""):
                fallback = fallback_specs[0]
                resolution = {
                    "status": "SNAPSHOT_FALLBACK",
                    "term": {"evidence_confidence": fallback.get("evidence_confidence", ""), "source_url": "", "lot_size": fallback.get("lot_size")},
                    "lot_size": fallback.get("lot_size"),
                    "term_id": fallback.get("spec_id", ""),
                }
            elif event.get("instrument_metadata_lot_size") not in (None, ""):
                resolution = {
                    "status": "SNAPSHOT_FALLBACK",
                    "term": {"evidence_confidence": "OFFICIAL_EXPLICIT", "source_url": "", "lot_size": event.get("instrument_metadata_lot_size")},
                    "lot_size": str(event.get("instrument_metadata_lot_size")),
                    "term_id": f"{event.get('symbol', '')}-INSTRUMENT-SNAPSHOT",
                }
        lot_size = resolution.get("lot_size")
        qty = event.get("lastQty")
        order_qty = event.get("orderQty")
        def multiple(value: Any) -> str:
            if lot_size is None or value in (None, ""):
                return "NOT_EVALUATED"
            try:
                return "PASS" if int(value) % int(lot_size) == 0 else "ODD_LOT"
            except (TypeError, ValueError):
                return "INVALID_QTY"
        rows.append({
            "event_time": event.get("event_time", ""),
            "execID": event.get("execID", ""),
            "symbol": event.get("symbol", ""),
            "execType": event.get("execType", ""),
            "resolved_lot_size": lot_size,
            "lastQty": qty,
            "orderQty": order_qty,
            "position_after": event.get("position_after", event.get("derivative_position_after", "")),
            "terms_resolution_status": resolution.get("status", ""),
            "terms_id": resolution.get("term_id", ""),
            "lastQty_multiple_status": multiple(qty),
            "orderQty_multiple_status": multiple(order_qty),
            "evidence_confidence": (resolution.get("term") or {}).get("evidence_confidence", ""),
            "source_url": (resolution.get("term") or {}).get("source_url", ""),
        })
    return rows


def summarize_instrument_terms(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "row_count": len(rows),
        "status_counts": dict(Counter(str(row.get("terms_resolution_status", "")) for row in rows)),
        "lot_size_counts": dict(Counter(str(row.get("resolved_lot_size", "")) for row in rows)),
        "odd_last_qty_count": sum(row.get("lastQty_multiple_status") == "ODD_LOT" for row in rows),
        "odd_order_qty_count": sum(row.get("orderQty_multiple_status") == "ODD_LOT" for row in rows),
        "symbols": sorted({str(row.get("symbol", "")) for row in rows}),
    }


__all__ = [
    "InstrumentTermsError",
    "audit_instrument_terms",
    "load_historical_instrument_terms",
    "resolve_instrument_terms",
    "summarize_instrument_terms",
]
