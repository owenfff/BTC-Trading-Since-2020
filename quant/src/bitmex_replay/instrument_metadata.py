from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .io_utils import clean, iter_csv_dicts, parse_datetime


INSTRUMENT_FIELDS = (
    "symbol",
    "state",
    "typ",
    "listing",
    "expiry",
    "settle",
    "lotSize",
    "settlCurrency",
    "positionCurrency",
    "isInverse",
    "isQuanto",
    "multiplier",
)

KNOWN_DERIVATIVE_TYPES = {
    "FFWCSX",  # Perpetual Contract
    "FFWCSF",  # Perpetual Contract with FX underlier
    "FFCCSX",  # Futures
    "FFMCSX",  # Futures Spread
    "FFSCSX",  # TradFi Contract
}

INSTRUMENT_TYPE_DOC = "https://docs.bitmex.com/api-explorer/get-instruments"


def classify_instrument_typ(typ: str) -> str:
    value = clean(typ).strip()
    if value == "IFXXXP":
        return "SPOT"
    if value.startswith("MR"):
        return "REFERENCE_INDEX"
    if value in KNOWN_DERIVATIVE_TYPES:
        return "DERIVATIVE"
    return "UNKNOWN"


def load_instruments(path: Path) -> dict[str, list[dict[str, str]]]:
    """Load every metadata record per symbol; never silently overwrite a symbol."""

    instruments: dict[str, list[dict[str, str]]] = {}
    for _, row in iter_csv_dicts(path):
        symbol = clean(row.get("symbol", "")).strip()
        if symbol:
            record = {field: clean(row.get(field, "")) for field in INSTRUMENT_FIELDS}
            record["instrument_class"] = classify_instrument_typ(record.get("typ", ""))
            instruments.setdefault(symbol, []).append(record)
    for records in instruments.values():
        records.sort(key=lambda row: (parse_datetime(row.get("listing", "")) or datetime.min.replace(tzinfo=timezone.utc), row.get("typ", "")))
    return instruments


def select_instrument(records: list[dict[str, str]], event_dt: datetime | None = None) -> dict[str, str]:
    """Select the best available record while retaining the full record history."""

    if not records:
        return {}
    if event_dt is not None:
        historical = [
            record
            for record in records
            if (listing_dt := parse_datetime(record.get("listing", ""))) is not None and listing_dt <= event_dt
        ]
        if historical:
            return historical[-1]
    return records[-1]


def metadata_temporal_status(first_event_dt: datetime | None, record: dict[str, str]) -> tuple[str, bool]:
    if not record:
        return "METADATA_MISSING", True
    listing_dt = parse_datetime(record.get("listing", ""))
    if first_event_dt is not None and listing_dt is not None and first_event_dt < listing_dt:
        return "EXECUTION_BEFORE_CURRENT_LISTING", True
    return "TEMPORALLY_COVERED", False


def build_instrument_temporal_audit(
    events: list[dict[str, Any]],
    instruments: dict[str, list[dict[str, str]]],
    historical_evidence_symbols: set[str] | None = None,
) -> list[dict[str, Any]]:
    historical_evidence_symbols = historical_evidence_symbols or set()
    grouped: dict[str, list[dict[str, Any]]] = {}
    for event in events:
        grouped.setdefault(str(event.get("symbol", "")), []).append(event)

    rows: list[dict[str, Any]] = []
    for symbol in sorted(grouped):
        symbol_events = grouped[symbol]
        event_times = [event.get("_event_dt") for event in symbol_events if event.get("_event_dt") is not None]
        first_dt = min(event_times) if event_times else None
        last_dt = max(event_times) if event_times else None
        record = select_instrument(instruments.get(symbol, []), first_dt)
        temporal_status, requires_historical_spec = metadata_temporal_status(first_dt, record)
        if symbol in historical_evidence_symbols and temporal_status == "EXECUTION_BEFORE_CURRENT_LISTING":
            temporal_status = "SYMBOL_REUSE_SUSPECTED"
        rows.append(
            {
                "symbol": symbol,
                "first_execution_time": first_dt.isoformat().replace("+00:00", "Z") if first_dt else "",
                "last_execution_time": last_dt.isoformat().replace("+00:00", "Z") if last_dt else "",
                "metadata_listing": record.get("listing", ""),
                "metadata_expiry": record.get("expiry", ""),
                "metadata_settle": record.get("settle", ""),
                "typ": record.get("typ", ""),
                "instrument_class": record.get("instrument_class", "UNKNOWN"),
                "first_execution_before_listing": temporal_status in {"EXECUTION_BEFORE_CURRENT_LISTING", "SYMBOL_REUSE_SUSPECTED"},
                "metadata_temporal_status": temporal_status,
                "requires_historical_spec": requires_historical_spec,
                "metadata_record_count": len(instruments.get(symbol, [])),
                "note": "Current metadata is a snapshot; historical contract specification is required before M0-02B." if requires_historical_spec else "",
            }
        )
    return rows


def instrument_distribution(events: list[dict[str, Any]]) -> dict[str, Any]:
    typ_counts = Counter(str(event.get("instrument_typ", "")) or "MISSING" for event in events)
    class_counts = Counter(str(event.get("instrument_class", "UNKNOWN")) for event in events)
    by_symbol: dict[str, dict[str, Any]] = {}
    for event in events:
        symbol = str(event.get("symbol", ""))
        item = by_symbol.setdefault(
            symbol,
            {
                "symbol": symbol,
                "instrument_typ": event.get("instrument_typ", ""),
                "instrument_class": event.get("instrument_class", "UNKNOWN"),
                "execution_count": 0,
            },
        )
        item["execution_count"] += 1
        item["instrument_typ"] = event.get("instrument_typ", "")
        item["instrument_class"] = event.get("instrument_class", "UNKNOWN")
    return {"typ_counts": dict(typ_counts), "class_counts": dict(class_counts), "by_symbol": list(by_symbol.values())}
