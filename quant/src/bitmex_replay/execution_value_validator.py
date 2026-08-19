from __future__ import annotations

import csv
from collections import Counter
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from .historical_spec_registry import normalize_currency
from .io_utils import clean, iter_csv_dicts


PARTIAL_EVIDENCE = "OFFICIAL_PARTIAL_EXECUTION_VALIDATED"
EXECUTION_INFERRED = "EXECUTION_INFERRED"
UNRESOLVED = "UNRESOLVED"
NO_ROUNDING_POLICY = "NONE_EXACT_DECIMAL_RAW_UNIT_COMPARISON"
IMPLIED_MULTIPLIER_MODE = "ACTUAL_EXEC_COST_RAW_DIVIDED_BY_SIGNED_QTY_TIMES_LAST_PX"


def _decimal(value: Any) -> Decimal | None:
    if value is None or not clean(value).strip():
        return None
    try:
        number = Decimal(clean(value).strip())
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _decimal_text(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value, "f")


def _sign(value: Decimal) -> int:
    return 1 if value > 0 else (-1 if value < 0 else 0)


def load_wallet_asset_scales(path: Path) -> dict[str, dict[str, Any]]:
    """Load the frozen wallet asset scale table without network access."""

    assets: dict[str, dict[str, Any]] = {}
    for _, row in iter_csv_dicts(Path(path)):
        scale = _decimal(row.get("scale"))
        if scale is None or scale != scale.to_integral_value():
            continue
        scale_int = int(scale)
        for value in (row.get("currency"), row.get("majorCurrency"), row.get("asset")):
            currency = normalize_currency(value)
            if currency:
                assets[currency] = {
                    "currency": currency,
                    "scale": scale_int,
                    "raw_currency": clean(row.get("currency")).strip(),
                    "major_currency": clean(row.get("majorCurrency")).strip(),
                }
    return assets


def normalize_raw_settlement_amount(
    raw_amount: Any,
    currency: Any,
    wallet_assets: dict[str, dict[str, Any]],
) -> Decimal:
    """Convert an integer-like BitMEX settlement amount to major currency using asset scale.

    The validator keeps the raw-unit comparison as the acceptance criterion. This conversion
    is an additional auditable representation and never rounds or uses binary floats.
    """

    amount = _decimal(raw_amount)
    if amount is None:
        raise ValueError(f"raw settlement amount is not a finite Decimal: {raw_amount!r}")
    normalized_currency = normalize_currency(currency)
    asset = wallet_assets.get(normalized_currency)
    if not asset:
        raise KeyError(f"wallet asset scale is unavailable for {normalized_currency or currency!r}")
    scale = asset.get("scale")
    if not isinstance(scale, int) or scale < 0:
        raise ValueError(f"wallet asset scale is invalid for {normalized_currency!r}: {scale!r}")
    return amount / (Decimal(10) ** scale)


def _configured_specs(registry: dict[str, Any]) -> list[dict[str, Any]]:
    configured = registry.get("configured_specs")
    if isinstance(configured, list):
        return configured
    return [spec for spec in registry.get("specs", []) if spec.get("source_type") == "CONFIGURED_HISTORICAL"]


def _event_mapping(mapping_rows: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        clean(row.get("execID")).strip(): row
        for row in mapping_rows
        if clean(row.get("execID")).strip()
    }


def _empty_spec_result(spec: dict[str, Any]) -> dict[str, Any]:
    return {
        "spec_id": spec.get("spec_id", ""),
        "symbol": spec.get("symbol", ""),
        "payout_model": spec.get("payout_model", ""),
        "settlement_currency": spec.get("settlement_currency", ""),
        "configured_multiplier_major": spec.get("multiplier_major"),
        "configured_multiplier_raw": spec.get("multiplier_raw"),
        "declared_evidence_confidence": spec.get("evidence_confidence", ""),
        "effective_evidence_confidence": spec.get("evidence_confidence", ""),
        "derivative_trade_count": 0,
        "eligible_validation_count": 0,
        "exact_match_count": 0,
        "mismatch_count": 0,
        "match_ratio": "0",
        "max_abs_error_raw": "0",
        "configured_multiplier": spec.get("multiplier_raw"),
        "implied_multiplier_mode": IMPLIED_MULTIPLIER_MODE,
        "implied_multiplier_min": None,
        "implied_multiplier_max": None,
        "sign_validation_status": "NOT_EVALUATED",
        "rounding_policy": NO_ROUNDING_POLICY,
        "multiplier_validation_status": "NOT_EVALUATED",
        "blocking_reason": "",
    }


def validate_configured_multiplier(
    normalized_events: Iterable[dict[str, Any]],
    registry: dict[str, Any],
    mapping_rows: Iterable[dict[str, Any]],
    wallet_assets: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Validate configured historical multipliers against signed raw execCost values.

    For Quanto XBT rows the fixed, auditable rule is:
    ``expected_execCost_raw = signed_contract_qty * multiplier_raw * lastPx``.
    Buy quantities are positive, Sell quantities are negative, and no absolute value or
    best-of-several-rounding rule is used. A row is eligible only when all inputs and the
    settlement currency scale are present and parseable.
    """

    specs = _configured_specs(registry)
    results = {spec.get("spec_id", ""): _empty_spec_result(spec) for spec in specs}
    rows_by_spec: dict[str, list[dict[str, Any]]] = {spec_id: [] for spec_id in results}
    mapping_by_exec = _event_mapping(mapping_rows)
    mismatches: list[dict[str, Any]] = []
    ineligible_reasons: Counter[str] = Counter()
    implied_values: dict[str, list[Decimal]] = {spec_id: [] for spec_id in results}
    max_errors: dict[str, Decimal] = {spec_id: Decimal("0") for spec_id in results}
    sign_statuses: dict[str, set[str]] = {spec_id: set() for spec_id in results}
    spec_by_id = {spec.get("spec_id", ""): spec for spec in specs}

    for event in normalized_events:
        if event.get("instrument_class") != "DERIVATIVE" or event.get("execType") != "Trade":
            continue
        mapping = mapping_by_exec.get(clean(event.get("execID")).strip())
        spec_id = clean(mapping.get("spec_id") if mapping else "").strip()
        if spec_id not in results:
            continue
        result = results[spec_id]
        result["derivative_trade_count"] += 1
        spec = spec_by_id[spec_id]

        signed_qty = _decimal(event.get("signed_contract_qty"))
        last_px = _decimal(event.get("lastPx"))
        actual_raw = _decimal(event.get("execCost"))
        multiplier_raw = _decimal(spec.get("multiplier_raw"))
        event_currency = normalize_currency(event.get("settlCurrency"))
        spec_currency = normalize_currency(spec.get("settlement_currency"))
        reason = ""
        if signed_qty is None or signed_qty == 0:
            reason = "signed_contract_qty missing or zero"
        elif last_px is None or last_px == 0:
            reason = "lastPx missing or zero"
        elif actual_raw is None:
            reason = "execCost missing or not a finite Decimal"
        elif multiplier_raw is None:
            reason = "configured multiplier_raw missing or not a finite Decimal"
        elif not event_currency:
            reason = "execution settlCurrency missing"
        elif event_currency != spec_currency:
            reason = f"settlement currency mismatch: execution={event_currency} spec={spec_currency}"
        elif event_currency not in wallet_assets:
            reason = f"wallet asset scale unavailable for {event_currency}"

        if reason:
            ineligible_reasons[reason] += 1
            continue

        expected_raw = signed_qty * multiplier_raw * last_px
        difference_raw = actual_raw - expected_raw
        sign_status = "PASS" if _sign(actual_raw) == _sign(expected_raw) else "CONFLICT"
        sign_statuses[spec_id].add(sign_status)
        implied = actual_raw / (signed_qty * last_px)
        implied_values[spec_id].append(implied)
        max_errors[spec_id] = max(max_errors[spec_id], abs(difference_raw))
        result["eligible_validation_count"] += 1
        row = {
            "event_time": event.get("event_time", ""),
            "source_row_number": event.get("source_row_number"),
            "execID": event.get("execID", ""),
            "symbol": event.get("symbol", ""),
            "side": event.get("side", ""),
            "signed_contract_qty": _decimal_text(signed_qty),
            "lastPx": _decimal_text(last_px),
            "configured_multiplier_raw": _decimal_text(multiplier_raw),
            "expected_execCost_raw": _decimal_text(expected_raw),
            "actual_execCost_raw": _decimal_text(actual_raw),
            "difference_raw": _decimal_text(difference_raw),
            "expected_execCost_major": _decimal_text(normalize_raw_settlement_amount(expected_raw, event_currency, wallet_assets)),
            "actual_execCost_major": _decimal_text(normalize_raw_settlement_amount(actual_raw, event_currency, wallet_assets)),
            "settlement_currency": event_currency,
            "wallet_asset_scale": wallet_assets[event_currency]["scale"],
            "spec_id": spec_id,
            "sign_validation_status": sign_status,
        }
        rows_by_spec[spec_id].append(row)
        if difference_raw == 0 and sign_status == "PASS":
            result["exact_match_count"] += 1
        else:
            result["mismatch_count"] += 1
            if len(mismatches) < 200:
                mismatches.append(row)

    for spec_id, result in results.items():
        eligible = result["eligible_validation_count"]
        exact = result["exact_match_count"]
        result["match_ratio"] = f"{(Decimal(exact) / Decimal(eligible)):.12f}" if eligible else "0"
        result["max_abs_error_raw"] = _decimal_text(max_errors[spec_id]) or "0"
        values = implied_values[spec_id]
        result["implied_multiplier_min"] = _decimal_text(min(values)) if values else None
        result["implied_multiplier_max"] = _decimal_text(max(values)) if values else None
        statuses = sign_statuses[spec_id]
        result["sign_validation_status"] = "PASS" if statuses == {"PASS"} else ("CONFLICT" if "CONFLICT" in statuses else "NOT_EVALUATED")
        if eligible == 0:
            result["multiplier_validation_status"] = "BLOCKED_NO_ELIGIBLE_ROWS"
            result["blocking_reason"] = "eligible_validation_count is zero"
        elif result["mismatch_count"]:
            result["multiplier_validation_status"] = "BLOCKED_MISMATCH"
            result["blocking_reason"] = f"{result['mismatch_count']} raw execCost mismatch(es)"
        elif result["sign_validation_status"] != "PASS":
            result["multiplier_validation_status"] = "BLOCKED_SIGN_CONFLICT"
            result["blocking_reason"] = "signed Buy/Sell direction does not reproduce execCost sign"
        else:
            result["multiplier_validation_status"] = "PASS"
            result["blocking_reason"] = ""

    return {
        "rows": list(results.values()),
        "mismatches": mismatches,
        "validation_rows": [row for rows in rows_by_spec.values() for row in rows],
        "ineligible_reasons": dict(ineligible_reasons),
        "spec_count": len(results),
        "mismatch_count": sum(row["mismatch_count"] for row in results.values()),
        "eligible_count": sum(row["eligible_validation_count"] for row in results.values()),
        "exact_count": sum(row["exact_match_count"] for row in results.values()),
    }


def validate_partial_evidence_specs(validation: dict[str, Any]) -> dict[str, Any]:
    """Apply the executable-evidence gate without trusting the declared JSON label alone."""

    rows = validation.get("rows", [])
    partial_results = []
    for row in rows:
        if row.get("declared_evidence_confidence") != PARTIAL_EVIDENCE:
            row["effective_evidence_confidence"] = row.get("declared_evidence_confidence", "")
            continue
        eligible = row.get("eligible_validation_count", 0)
        implied_min = row.get("implied_multiplier_min")
        implied_max = row.get("implied_multiplier_max")
        configured = row.get("configured_multiplier_raw")
        validated = (
            eligible > 0
            and row.get("mismatch_count", 0) == 0
            and row.get("sign_validation_status") == "PASS"
            and implied_min == configured
            and implied_max == configured
        )
        if validated:
            row["effective_evidence_confidence"] = PARTIAL_EVIDENCE
            row["multiplier_validation_status"] = "PASS"
        else:
            row["effective_evidence_confidence"] = UNRESOLVED if eligible == 0 else EXECUTION_INFERRED
            if row.get("multiplier_validation_status") == "PASS":
                row["multiplier_validation_status"] = "BLOCKED_PARTIAL_EVIDENCE"
            if not row.get("blocking_reason"):
                row["blocking_reason"] = "partial evidence did not pass executable multiplier validation"
        partial_results.append(row)
    return {
        "rows": partial_results,
        "all_passed": all(row.get("multiplier_validation_status") == "PASS" for row in partial_results),
        "failed_spec_ids": [row.get("spec_id") for row in partial_results if row.get("multiplier_validation_status") != "PASS"],
    }


def build_multiplier_validation_report(validation: dict[str, Any]) -> dict[str, Any]:
    """Return machine-readable report content; file writing remains in the build script."""

    rows = validation.get("rows", [])
    confidence_counts = Counter(row.get("effective_evidence_confidence", "") for row in rows)
    return {
        "report_version": "M0-02B-0.1/1.0",
        "spec_count": len(rows),
        "eligible_validation_count": validation.get("eligible_count", 0),
        "exact_match_count": validation.get("exact_count", 0),
        "mismatch_count": validation.get("mismatch_count", 0),
        "match_ratio": f"{(Decimal(validation.get('exact_count', 0)) / Decimal(validation.get('eligible_count', 1))):.12f}" if validation.get("eligible_count", 0) else "0",
        "effective_evidence_confidence_counts": dict(confidence_counts),
        "ineligible_reasons": validation.get("ineligible_reasons", {}),
        "rows": rows,
        "mismatches": validation.get("mismatches", []),
    }


__all__ = [
    "build_multiplier_validation_report",
    "load_wallet_asset_scales",
    "normalize_raw_settlement_amount",
    "validate_configured_multiplier",
    "validate_partial_evidence_specs",
]
