from __future__ import annotations

import hashlib
import json
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from .instrument_metadata import classify_instrument_typ
from .instrument_terms import load_historical_instrument_terms, resolve_instrument_terms
from .io_utils import clean, iso_datetime, iter_csv_dicts, parse_datetime


EVIDENCE_LEVELS = {
    "OFFICIAL_EXPLICIT",
    "OFFICIAL_PARTIAL_EXECUTION_VALIDATED",
    "EXECUTION_INFERRED",
    "UNRESOLVED",
}
PAYOUT_MODELS = {"INVERSE", "LINEAR", "QUANTO"}
REQUIRED_FIELDS = (
    "spec_id",
    "symbol",
    "valid_from",
    "valid_to_exclusive",
    "typ",
    "instrument_class",
    "payout_model",
    "underlying",
    "quote_currency",
    "settlement_currency",
    "margin_currency",
    "is_inverse",
    "is_quanto",
    "multiplier_major",
    "multiplier_currency",
    "multiplier_raw",
    "evidence_confidence",
    "sources",
)
DECIMAL_FIELDS = ("multiplier_major", "multiplier_raw", "lot_size", "tick_size")
SNAPSHOT_FIELDS = (
    "typ",
    "listing",
    "expiry",
    "settle",
    "settlCurrency",
    "positionCurrency",
    "isInverse",
    "isQuanto",
    "multiplier",
    "underlyingToPositionMultiplier",
    "underlyingToSettleMultiplier",
    "quoteToSettleMultiplier",
    "lotSize",
    "tickSize",
)
UTC_MAX = "9999-12-31T00:00:00Z"
INSTRUMENT_API_URL = "https://docs.bitmex.com/api-explorer/get-instruments"


def normalize_currency(value: Any) -> str:
    raw = clean(value).strip()
    if not raw:
        return ""
    upper = raw.upper()
    if upper == "XBT":
        return "XBT"
    if upper == "USDT":
        return "USDT"
    return upper


def _decimal_string(value: Any) -> bool:
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        return False
    return number.is_finite()


def _parse_event_time(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
        return parse_datetime(parsed.isoformat())
    return parse_datetime(value)


def _specs_from(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        return list(value.get("specs", []))
    return list(value or [])


def validate_spec_schema(spec: dict[str, Any]) -> list[str]:
    """Return schema errors without silently coercing malformed configuration."""

    errors: list[str] = []
    if not isinstance(spec, dict):
        return ["spec must be an object"]
    for field in REQUIRED_FIELDS:
        if field not in spec:
            errors.append(f"missing field: {field}")
    if not clean(spec.get("spec_id")).strip():
        errors.append("spec_id must be non-empty")
    if not clean(spec.get("symbol")).strip():
        errors.append("symbol must be non-empty")
    if spec.get("instrument_class") != "DERIVATIVE":
        errors.append("instrument_class must be DERIVATIVE for a derivative specification")
    if spec.get("payout_model") not in PAYOUT_MODELS:
        errors.append(f"payout_model must be one of {sorted(PAYOUT_MODELS)}")
    combo = (spec.get("payout_model"), spec.get("is_inverse"), spec.get("is_quanto"))
    expected = {
        "INVERSE": (True, False),
        "LINEAR": (False, False),
        "QUANTO": (False, True),
    }
    if spec.get("payout_model") in expected and combo[1:] != expected[spec["payout_model"]]:
        errors.append("payout_model is inconsistent with is_inverse/is_quanto")
    if not isinstance(spec.get("is_inverse"), bool):
        errors.append("is_inverse must be boolean")
    if not isinstance(spec.get("is_quanto"), bool):
        errors.append("is_quanto must be boolean")
    if spec.get("evidence_confidence") not in EVIDENCE_LEVELS:
        errors.append(f"unsupported evidence_confidence: {spec.get('evidence_confidence')!r}")
    if not isinstance(spec.get("sources"), list) or not spec.get("sources"):
        errors.append("sources must be a non-empty list")
    for field in DECIMAL_FIELDS:
        if field in spec and spec[field] is not None and not _decimal_string(spec[field]):
            errors.append(f"{field} must be a Decimal string or null")
    for field in ("valid_from", "valid_to_exclusive"):
        if parse_datetime(spec.get(field)) is None:
            errors.append(f"{field} must be a UTC ISO-8601 timestamp")
    return errors


def validate_spec_intervals(specs_or_registry: Any) -> list[str]:
    """Return invalid or overlapping interval errors grouped by exact symbol."""

    specs = _specs_from(specs_or_registry)
    errors: list[str] = []
    grouped: dict[str, list[dict[str, Any]]] = {}
    for spec in specs:
        errors.extend(f"{spec.get('spec_id', '<unknown>')}: {error}" for error in validate_spec_schema(spec))
        start = parse_datetime(spec.get("valid_from"))
        end = parse_datetime(spec.get("valid_to_exclusive"))
        if start is None or end is None:
            continue
        if start >= end:
            errors.append(f"{spec.get('spec_id', '<unknown>')}: valid_from must be before valid_to_exclusive")
        grouped.setdefault(clean(spec.get("symbol")).strip(), []).append(spec)
    for symbol, symbol_specs in grouped.items():
        ordered = sorted(symbol_specs, key=lambda item: parse_datetime(item["valid_from"]) or datetime.max)
        for previous, current in zip(ordered, ordered[1:]):
            previous_end = parse_datetime(previous["valid_to_exclusive"])
            current_start = parse_datetime(current["valid_from"])
            if previous_end is not None and current_start is not None and current_start < previous_end:
                errors.append(
                    f"OVERLAPPING_SPECS: symbol={symbol} {previous.get('spec_id')} overlaps {current.get('spec_id')}"
                )
    return errors


def _canonical_row_hash(row: dict[str, Any]) -> str:
    payload = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _decimal_division(numerator: str, denominator: str) -> str | None:
    if not _decimal_string(numerator) or not _decimal_string(denominator):
        return None
    denominator_decimal = Decimal(denominator)
    if denominator_decimal == 0:
        return None
    value = Decimal(numerator) / denominator_decimal
    return format(value, "f").rstrip("0").rstrip(".") or "0"


def _snapshot_spec(row: dict[str, str], data_source_commit: str, row_hash: str) -> dict[str, Any] | None:
    symbol = clean(row.get("symbol")).strip()
    typ = clean(row.get("typ")).strip()
    if not symbol or classify_instrument_typ(typ) != "DERIVATIVE":
        return None
    listing = parse_datetime(row.get("listing"))
    if listing is None:
        return None
    is_inverse = clean(row.get("isInverse")).strip().lower() == "true"
    is_quanto = clean(row.get("isQuanto")).strip().lower() == "true"
    payout_model = "INVERSE" if is_inverse else ("QUANTO" if is_quanto else "LINEAR")
    raw_multiplier = clean(row.get("multiplier")).strip() or None
    if payout_model == "INVERSE":
        multiplier_major = _decimal_division(raw_multiplier or "", clean(row.get("underlyingToSettleMultiplier")).strip())
        multiplier_currency = normalize_currency(row.get("quoteCurrency")) or None
        derivation = "multiplier / underlyingToSettleMultiplier from the frozen instrument row"
    elif payout_model == "QUANTO":
        multiplier_major = _decimal_division(raw_multiplier or "", "100000000")
        multiplier_currency = "XBT" if multiplier_major is not None else None
        derivation = "multiplier / 100000000 XBt per the frozen BitMEX instrument snapshot"
    else:
        multiplier_major = _decimal_division("1", clean(row.get("underlyingToPositionMultiplier")).strip())
        multiplier_currency = normalize_currency(row.get("positionCurrency")) or clean(row.get("underlying")).strip() or None
        derivation = "1 / underlyingToPositionMultiplier from the frozen instrument row"
    snapshot_fields = {field: clean(row.get(field)) for field in SNAPSHOT_FIELDS}
    return {
        "spec_id": f"{symbol}-SNAPSHOT-{row_hash[:12]}",
        "symbol": symbol,
        "valid_from": iso_datetime(listing),
        "valid_to_exclusive": UTC_MAX,
        "typ": typ,
        "instrument_class": "DERIVATIVE",
        "payout_model": payout_model,
        "underlying": clean(row.get("underlying")).strip() or None,
        "quote_currency": normalize_currency(row.get("quoteCurrency")) or None,
        "settlement_currency": normalize_currency(row.get("settlCurrency")) or None,
        "margin_currency": normalize_currency(row.get("settlCurrency")) or None,
        "is_inverse": is_inverse,
        "is_quanto": is_quanto,
        "multiplier_major": multiplier_major,
        "multiplier_currency": multiplier_currency,
        "multiplier_raw": raw_multiplier,
        "lot_size": clean(row.get("lotSize")).strip() or None,
        "tick_size": clean(row.get("tickSize")).strip() or None,
        "evidence_confidence": "OFFICIAL_EXPLICIT",
        "source_type": "BITMEX_INSTRUMENT_SNAPSHOT",
        "data_source_commit": data_source_commit,
        "metadata_row_sha256": row_hash,
        "snapshot_fields": snapshot_fields,
        "sources": [{
            "source_type": "BITMEX_INSTRUMENT_SNAPSHOT",
            "source_title": "Frozen api-v1-instrument.all.csv row",
            "source_url": INSTRUMENT_API_URL,
            "published_at": None,
            "notes": f"data_source_commit={data_source_commit}; row_sha256={row_hash}",
        }],
        "field_provenance": {
            "snapshot_fields": "Directly retained from the complete frozen CSV row.",
            "multiplier_major": derivation,
            "valid_interval": "listing through the registry snapshot horizon; not a claim about future exchange metadata.",
        },
        "notes": "Current snapshot version generated locally without network access.",
    }


def load_historical_specs(
    config_path: Path,
    instrument_path: Path | None = None,
    data_source_commit: str | None = None,
    terms_path: Path | None = None,
) -> dict[str, Any]:
    """Load configured historical versions and materialize frozen snapshot versions."""

    config_path = Path(config_path)
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("specs"), list):
        raise ValueError("historical specification config must contain an object with a specs list")
    configured_specs = [dict(spec) for spec in payload["specs"]]
    for spec in configured_specs:
        errors = validate_spec_schema(spec)
        if errors:
            raise ValueError(f"Invalid historical spec {spec.get('spec_id', '<unknown>')}: {errors}")
        spec.setdefault("source_type", "CONFIGURED_HISTORICAL")
    snapshot_specs: list[dict[str, Any]] = []
    snapshot_source = payload.get("snapshot_source") or {}
    if instrument_path is None and snapshot_source.get("path"):
        candidate = config_path.parents[2] / snapshot_source["path"]
        if candidate.is_file():
            instrument_path = candidate
    if instrument_path is not None:
        instrument_path = Path(instrument_path)
        if not instrument_path.is_file():
            raise FileNotFoundError(instrument_path)
        commit = data_source_commit or snapshot_source.get("data_source_commit") or payload.get("data_source_commit") or ""
        for _, row in iter_csv_dicts(instrument_path):
            spec = _snapshot_spec(row, commit, _canonical_row_hash(row))
            if spec is not None:
                snapshot_specs.append(spec)
    if terms_path is None:
        candidate_terms = config_path.parent / "historical_instrument_terms.json"
        if candidate_terms.is_file():
            terms_path = candidate_terms
    instrument_terms = load_historical_instrument_terms(terms_path) if terms_path is not None else {"terms": [], "terms_by_symbol": {}}
    specs = sorted(configured_specs + snapshot_specs, key=lambda item: (item.get("symbol", ""), item.get("valid_from", ""), item.get("spec_id", "")))
    interval_errors = validate_spec_intervals(specs)
    if interval_errors:
        raise ValueError("Invalid historical specification intervals: " + "; ".join(interval_errors[:10]))
    by_symbol: dict[str, list[dict[str, Any]]] = {}
    for spec in specs:
        by_symbol.setdefault(spec["symbol"], []).append(spec)
    return {
        "schema_version": payload.get("schema_version", ""),
        "data_source_commit": data_source_commit or payload.get("data_source_commit", ""),
        "config_path": str(config_path),
        "specs": specs,
        "configured_specs": configured_specs,
        "snapshot_specs": snapshot_specs,
        "specs_by_symbol": by_symbol,
        "source_metadata": payload.get("snapshot_source", {}),
        "instrument_terms": instrument_terms,
    }


def resolve_spec(registry: Any, symbol: str, event_time: Any) -> dict[str, Any]:
    """Resolve by exact symbol and a left-closed/right-open UTC interval."""

    event_dt = _parse_event_time(event_time)
    if event_dt is None:
        return {"status": "MISSING_SPEC", "matches": [], "spec": None, "reason": "event_time is not parseable as UTC"}
    candidates = []
    for spec in _specs_from(registry):
        if clean(spec.get("symbol")).strip() != clean(symbol).strip():
            continue
        start = parse_datetime(spec.get("valid_from"))
        end = parse_datetime(spec.get("valid_to_exclusive"))
        if start is not None and end is not None and start <= event_dt < end:
            candidates.append(spec)
    if len(candidates) == 1:
        return {"status": "MATCHED", "matches": candidates, "spec": candidates[0], "reason": "exactly one interval matched"}
    if not candidates:
        return {"status": "MISSING_SPEC", "matches": [], "spec": None, "reason": "no exact symbol interval matched"}
    return {"status": "OVERLAPPING_SPECS", "matches": candidates, "spec": None, "reason": "more than one interval matched; no latest-version fallback"}


def validate_execution_spec_compatibility(event: dict[str, Any], spec_or_resolution: Any) -> dict[str, Any]:
    resolution = spec_or_resolution if isinstance(spec_or_resolution, dict) and "status" in spec_or_resolution else None
    spec = resolution.get("spec") if resolution else spec_or_resolution
    if resolution and resolution.get("status") != "MATCHED":
        return {"compatibility_status": resolution["status"], "compatibility_reason": resolution.get("reason", "")}
    if not isinstance(spec, dict):
        return {"compatibility_status": "MISSING_SPEC", "compatibility_reason": "no resolved specification"}
    reasons: list[str] = []
    if clean(event.get("symbol")).strip() != clean(spec.get("symbol")).strip():
        reasons.append("symbol mismatch")
    if event.get("instrument_class") not in {None, "", "DERIVATIVE"}:
        reasons.append("event instrument_class is not DERIVATIVE")
    execution_settlement = normalize_currency(event.get("settlCurrency"))
    specification_settlement = normalize_currency(spec.get("settlement_currency"))
    if execution_settlement and specification_settlement and execution_settlement != specification_settlement:
        reasons.append(f"settlement currency mismatch: execution={execution_settlement} spec={specification_settlement}")
    if event.get("execType") not in {None, "", "Trade", "Funding", "Settlement"}:
        reasons.append(f"unsupported derivative execType={event.get('execType')!r}")
    expected = {"INVERSE": (True, False), "LINEAR": (False, False), "QUANTO": (False, True)}
    if spec.get("payout_model") in expected and (spec.get("is_inverse"), spec.get("is_quanto")) != expected[spec["payout_model"]]:
        reasons.append("payout_model/isInverse/isQuanto conflict")
    event_dt = _parse_event_time(event.get("_event_dt") or event.get("event_time"))
    start = parse_datetime(spec.get("valid_from"))
    end = parse_datetime(spec.get("valid_to_exclusive"))
    if event_dt is None or start is None or end is None or not (start <= event_dt < end):
        reasons.append("event_time is outside resolved specification interval")
    listing = parse_datetime(event.get("instrument_metadata_listing"))
    if spec.get("source_type") == "BITMEX_INSTRUMENT_SNAPSHOT" and listing and event_dt and event_dt < listing:
        reasons.append("current metadata listing is after event_time")
    if reasons:
        return {"compatibility_status": "CONFLICT", "compatibility_reason": "; ".join(reasons)}
    return {"compatibility_status": "PASS", "compatibility_reason": "currency, execType, interval and payout-model checks passed"}


def resolve_specs_for_events(
    events: Iterable[dict[str, Any]],
    registry: Any,
    terms_registry: Any | None = None,
) -> list[dict[str, Any]]:
    """Return one mapping row per DERIVATIVE event; Spot is deliberately excluded."""

    rows: list[dict[str, Any]] = []
    for event in events:
        if event.get("instrument_class") != "DERIVATIVE":
            continue
        symbol = clean(event.get("symbol")).strip()
        resolution = resolve_spec(registry, symbol, event.get("_event_dt") or event.get("event_time"))
        compatibility = validate_execution_spec_compatibility(event, resolution)
        spec = resolution.get("spec") or {}
        terms = resolve_instrument_terms(
            terms_registry or registry.get("instrument_terms", {}),
            symbol,
            event.get("_event_dt") or event.get("event_time"),
        )
        resolved_lot_size = terms.get("lot_size") or spec.get("lot_size")
        rows.append({
            "event_time": event.get("event_time") or (event.get("_event_dt").isoformat() if event.get("_event_dt") else ""),
            "source_row_number": event.get("source_row_number"),
            "execID": event.get("execID", ""),
            "execType": event.get("execType", ""),
            "symbol": symbol,
            "instrument_class": event.get("instrument_class", ""),
            "spec_id": spec.get("spec_id", ""),
            "payout_model": spec.get("payout_model"),
            "quote_currency": spec.get("quote_currency"),
            "settlement_currency": spec.get("settlement_currency"),
            "multiplier_major": spec.get("multiplier_major"),
            "multiplier_currency": spec.get("multiplier_currency"),
            "lot_size": spec.get("lot_size"),
            "resolved_lot_size": resolved_lot_size,
            "terms_id": terms.get("term_id", ""),
            "terms_resolution_status": terms.get("status", "MISSING"),
            "terms_evidence_confidence": (terms.get("term") or {}).get("evidence_confidence", ""),
            "spec_resolution_status": resolution.get("status", ""),
            "spec_evidence_confidence": spec.get("evidence_confidence", ""),
            "execution_settlCurrency": event.get("settlCurrency", ""),
            "compatibility_status": compatibility["compatibility_status"],
            "compatibility_reason": compatibility["compatibility_reason"],
        })
    return rows


__all__ = [
    "EVIDENCE_LEVELS",
    "load_historical_specs",
    "load_historical_instrument_terms",
    "normalize_currency",
    "resolve_spec",
    "resolve_specs_for_events",
    "validate_execution_spec_compatibility",
    "validate_spec_intervals",
    "validate_spec_schema",
]
