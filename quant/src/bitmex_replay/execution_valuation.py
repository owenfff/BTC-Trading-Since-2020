from __future__ import annotations

from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from .historical_spec_registry import normalize_currency as _normalize_currency
from .io_utils import clean, iter_csv_dicts


TRADE = "Trade"
FUNDING = "Funding"
SETTLEMENT = "Settlement"

POSITION_COST = "POSITION_COST"
TRADE_FEE_OR_REBATE = "TRADE_FEE_OR_REBATE"
FUNDING_PAYMENT = "FUNDING_PAYMENT"
SETTLEMENT_COMMISSION = "SETTLEMENT_COMMISSION"
REPORTED_REALISED_PNL = "REPORTED_REALISED_PNL"
EXECUTION_COST_REFERENCE = "EXECUTION_COST_REFERENCE"
SETTLEMENT_POSITION_VALUE_REFERENCE = "SETTLEMENT_POSITION_VALUE_REFERENCE"

MISSING = "MISSING"
VALID = "VALID"
INVALID_RAW_AMOUNT = "INVALID_RAW_AMOUNT"
NON_INTEGER_RAW_AMOUNT = "NON_INTEGER_RAW_AMOUNT"

PASS = "PASS"
FAIL = "FAIL"
MISSING_ONLY = "MISSING_ONLY"


class RawAmountError(ValueError):
    """A raw wallet-unit amount is absent, invalid, or non-integer."""

    def __init__(self, status: str, message: str) -> None:
        super().__init__(message)
        self.status = status


class AssetScaleError(ValueError):
    """A required currency is not present in the frozen wallet asset registry."""


def normalize_currency_code(value: Any) -> str:
    """Normalize BitMEX currency aliases without applying market conversion."""

    raw = clean(value).strip()
    if not raw:
        return ""
    normalized = _normalize_currency(raw)
    return normalized or raw.upper()


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


def _sign_label(value: Decimal | None) -> str:
    if value is None:
        return MISSING
    if value > 0:
        return "POSITIVE"
    if value < 0:
        return "NEGATIVE"
    return "ZERO"


def _raw_text(value: Any) -> str:
    return clean(value).strip()


def parse_raw_integer_decimal(value: Any) -> Decimal | None:
    """Parse a raw amount, accepting integer-like Decimal strings only.

    Blank values return ``None`` so missing remains distinct from zero. Invalid and
    non-integer values raise ``RawAmountError`` with an auditable status.
    """

    raw = _raw_text(value)
    if not raw:
        return None
    try:
        number = Decimal(raw)
    except (InvalidOperation, ValueError) as exc:
        raise RawAmountError(INVALID_RAW_AMOUNT, f"raw amount is not a finite Decimal: {raw!r}") from exc
    if not number.is_finite():
        raise RawAmountError(INVALID_RAW_AMOUNT, f"raw amount is not finite: {raw!r}")
    if number != number.to_integral_value():
        raise RawAmountError(NON_INTEGER_RAW_AMOUNT, f"raw amount is not integer-like: {raw!r}")
    return number.to_integral_value()


def load_asset_scale_registry(path: Path) -> dict[str, dict[str, Any]]:
    """Load the frozen wallet-assets currency/majorCurrency/scale registry."""

    registry: dict[str, dict[str, Any]] = {}
    for _, row in iter_csv_dicts(Path(path)):
        raw_scale = _raw_text(row.get("scale"))
        if not raw_scale:
            raise AssetScaleError(f"missing wallet asset scale for {row.get('currency', '')!r}")
        try:
            scale = parse_raw_integer_decimal(raw_scale)
        except RawAmountError as exc:
            raise AssetScaleError(f"invalid wallet asset scale for {row.get('currency', '')!r}: {exc}") from exc
        if scale is None or scale < 0:
            raise AssetScaleError(f"invalid wallet asset scale for {row.get('currency', '')!r}: {raw_scale!r}")
        keys = {
            normalize_currency_code(row.get("currency")),
            normalize_currency_code(row.get("majorCurrency")),
            normalize_currency_code(row.get("asset")),
        } - {""}
        for currency in keys:
            existing = registry.get(currency)
            if existing is not None and existing["scale"] != int(scale):
                raise AssetScaleError(f"conflicting wallet asset scales for {currency}: {existing['scale']} vs {scale}")
            registry[currency] = {
                "currency": currency,
                "scale": int(scale),
                "raw_currency": _raw_text(row.get("currency")),
                "major_currency": _raw_text(row.get("majorCurrency")),
            }
    return registry


def _asset(currency: Any, asset_registry: dict[str, dict[str, Any]]) -> dict[str, Any]:
    code = normalize_currency_code(currency)
    if not code or code not in asset_registry:
        raise AssetScaleError(f"asset scale is unavailable for {currency!r}")
    return asset_registry[code]


def raw_to_major(raw_amount: Any, currency: Any, asset_registry: dict[str, dict[str, Any]]) -> Decimal | None:
    """Convert integer raw units to major currency units using Decimal."""

    raw = raw_amount if isinstance(raw_amount, Decimal) else parse_raw_integer_decimal(raw_amount)
    if raw is None:
        return None
    scale = _asset(currency, asset_registry)["scale"]
    return raw / (Decimal(10) ** scale)


def major_to_raw(major_amount: Any, currency: Any, asset_registry: dict[str, dict[str, Any]]) -> Decimal | None:
    """Convert major units back to raw units and reject fractional raw units."""

    major = _decimal(major_amount)
    if major is None:
        return None
    scale = _asset(currency, asset_registry)["scale"]
    raw = major * (Decimal(10) ** scale)
    if raw != raw.to_integral_value():
        raise RawAmountError(NON_INTEGER_RAW_AMOUNT, f"major amount cannot map to integer raw units: {major_amount!r}")
    return raw.to_integral_value()


def validate_raw_major_roundtrip(
    raw_amount: Any,
    currency: Any,
    asset_registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Return an exact raw → major → raw audit result."""

    raw_text = _raw_text(raw_amount)
    if not raw_text:
        return {"status": MISSING, "raw": None, "major": None, "roundtrip_raw": None, "reason": "raw amount missing"}
    try:
        raw = parse_raw_integer_decimal(raw_text)
        major = raw_to_major(raw, currency, asset_registry)
        roundtrip = major_to_raw(major, currency, asset_registry)
    except RawAmountError as exc:
        return {"status": exc.status, "raw": raw_text, "major": None, "roundtrip_raw": None, "reason": str(exc)}
    except AssetScaleError as exc:
        return {"status": FAIL, "raw": raw_text, "major": None, "roundtrip_raw": None, "reason": str(exc)}
    status = PASS if roundtrip == raw else FAIL
    return {
        "status": status,
        "raw": _decimal_text(raw),
        "major": _decimal_text(major),
        "roundtrip_raw": _decimal_text(roundtrip),
        "reason": "exact equality" if status == PASS else "raw-major-raw mismatch",
    }


def _component_definition(exec_type: str, source_field: str) -> dict[str, Any]:
    if source_field == "realisedPnl":
        return {
            "component_type": REPORTED_REALISED_PNL,
            "accounting_role": REPORTED_REALISED_PNL,
            "is_position_cost_component": False,
            "is_wallet_cashflow_candidate": True,
            "overlap_status": "OVERLAP_WITH_FEES_AND_FUNDING_NOT_YET_RECONCILED",
        }
    if source_field == "execCost":
        if exec_type == TRADE:
            return {
                "component_type": POSITION_COST,
                "accounting_role": POSITION_COST,
                "is_position_cost_component": True,
                "is_wallet_cashflow_candidate": False,
                "overlap_status": "NOT_APPLICABLE",
            }
        if exec_type == SETTLEMENT:
            return {
                "component_type": SETTLEMENT_POSITION_VALUE_REFERENCE,
                "accounting_role": SETTLEMENT_POSITION_VALUE_REFERENCE,
                "is_position_cost_component": False,
                "is_wallet_cashflow_candidate": False,
                "overlap_status": "NON_CASH_REFERENCE_PENDING_RECONCILIATION",
            }
        return {
            "component_type": EXECUTION_COST_REFERENCE,
            "accounting_role": EXECUTION_COST_REFERENCE,
            "is_position_cost_component": False,
            "is_wallet_cashflow_candidate": False,
            "overlap_status": "NON_CASH_REFERENCE_PENDING_RECONCILIATION",
        }
    if exec_type == TRADE:
        component_type = TRADE_FEE_OR_REBATE
    elif exec_type == FUNDING:
        component_type = FUNDING_PAYMENT
    else:
        component_type = SETTLEMENT_COMMISSION
    return {
        "component_type": component_type,
        "accounting_role": component_type,
        "is_position_cost_component": False,
        "is_wallet_cashflow_candidate": True,
        "overlap_status": "NOT_APPLICABLE",
    }


def classify_execution_components(event: dict[str, Any]) -> list[dict[str, Any]]:
    """Classify amount fields without summing components into a net cashflow."""

    exec_type = clean(event.get("execType")).strip()
    definitions: list[dict[str, Any]] = []
    for source_field in ("execCost", "execComm", "realisedPnl"):
        definition = _component_definition(exec_type, source_field)
        definition.update({"source_field": source_field, "execType": exec_type})
        definitions.append(definition)
    return definitions


def _parse_amount_field(
    value: Any,
    currency: str,
    asset_registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    raw_text = _raw_text(value)
    if not raw_text:
        return {"raw": None, "major": None, "status": MISSING, "reason": "field missing"}
    try:
        parsed = parse_raw_integer_decimal(raw_text)
        major = raw_to_major(parsed, currency, asset_registry)
        roundtrip = major_to_raw(major, currency, asset_registry)
    except RawAmountError as exc:
        return {"raw": raw_text, "major": None, "status": exc.status, "reason": str(exc)}
    except AssetScaleError as exc:
        return {"raw": raw_text, "major": None, "status": FAIL, "reason": str(exc)}
    if roundtrip != parsed:
        return {"raw": _decimal_text(parsed), "major": _decimal_text(major), "status": FAIL, "reason": "raw-major-raw mismatch"}
    return {"raw": _decimal_text(parsed), "major": _decimal_text(major), "status": VALID, "reason": "exact raw-major-raw roundtrip"}


def _resolve_currency(
    event: dict[str, Any],
    spec: dict[str, Any],
    asset_registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    raw_settlement = _raw_text(event.get("settlCurrency"))
    event_currency = normalize_currency_code(raw_settlement)
    spec_currency = normalize_currency_code(spec.get("settlement_currency"))
    reasons: list[str] = []
    status = PASS
    if event_currency and spec_currency and event_currency != spec_currency:
        status = FAIL
        reasons.append(f"settlement currency conflict: event={event_currency} spec={spec_currency}")
    settlement_currency = event_currency or spec_currency
    scale = None
    if settlement_currency:
        try:
            scale = _asset(settlement_currency, asset_registry)["scale"]
        except AssetScaleError as exc:
            status = FAIL
            reasons.append(str(exc))
    else:
        status = FAIL
        reasons.append("settlement currency unresolved")
    exec_comm_raw_currency = normalize_currency_code(event.get("execCommCcy"))
    if exec_comm_raw_currency:
        commission_currency = exec_comm_raw_currency
        commission_source = "EXEC_COMM_CCY"
    elif event_currency and event_currency == spec_currency:
        commission_currency = event_currency
        commission_source = "EVENT_SETTL_CURRENCY_FALLBACK"
    elif spec_currency:
        commission_currency = spec_currency
        commission_source = "SPEC_SETTLEMENT_CURRENCY_FALLBACK"
    else:
        commission_currency = ""
        commission_source = "UNRESOLVED"
    commission_scale = None
    if commission_currency:
        try:
            commission_scale = _asset(commission_currency, asset_registry)["scale"]
        except AssetScaleError as exc:
            status = FAIL
            reasons.append(str(exc))
    else:
        status = FAIL
        reasons.append("commission currency unresolved")
    return {
        "settlement_currency_raw": raw_settlement,
        "settlement_currency": settlement_currency,
        "settlement_asset_scale": scale,
        "commission_currency": commission_currency,
        "commission_currency_source": commission_source,
        "commission_asset_scale": commission_scale,
        "status": status,
        "reasons": reasons,
    }


def _canonical_price_fields(
    event: dict[str, Any],
    price_row: dict[str, Any] | None,
) -> dict[str, Any]:
    if clean(event.get("execType")).strip() != TRADE:
        return {
            "canonical_execution_price": None,
            "canonical_price_status": "NOT_APPLICABLE",
            "price_resolution_method": "NOT_A_TRADE",
        }
    if price_row is None:
        return {
            "canonical_execution_price": event.get("lastPx") or None,
            "canonical_price_status": "NOT_AUDITED_IN_M0_02B_0_2",
            "price_resolution_method": "RAW_LASTPX_PRESERVED",
        }
    precision_status = price_row.get("price_precision_status")
    if precision_status == "EXACT":
        status = "AUDITED_OBSERVED_EXACT"
    elif precision_status == "OBSERVED_PRICE_COARSENED_BY_ONE_TICK":
        status = "AUDITED_RECOVERED_FROM_EXECCOST"
    else:
        status = "AUDITED_UNRESOLVED"
    return {
        "canonical_execution_price": price_row.get("canonical_execution_price"),
        "canonical_price_status": status,
        "price_resolution_method": price_row.get("price_resolution_method", "M0_02B_0_2_RECONCILIATION"),
    }


def _fee_diagnostic(
    event: dict[str, Any],
    exec_cost: dict[str, Any],
    exec_comm: dict[str, Any],
    commission_rate: Decimal | None,
    *,
    comparable_currency: bool,
) -> dict[str, Any]:
    if clean(event.get("execType")).strip() != TRADE:
        return {"fee_formula_status": "NOT_APPLICABLE", "fee_formula_difference_raw": None}
    if not comparable_currency:
        return {"fee_formula_status": "NOT_COMPARABLE_CURRENCY", "fee_formula_difference_raw": None}
    cost = _decimal(exec_cost.get("raw"))
    actual = _decimal(exec_comm.get("raw"))
    if cost is None or actual is None or commission_rate is None:
        return {"fee_formula_status": "NOT_EVALUATED", "fee_formula_difference_raw": None}
    candidate = (cost if cost >= 0 else -cost) * commission_rate
    difference = actual - candidate
    return {
        "fee_formula_status": "EXACT" if difference == 0 else "DIAGNOSTIC_DIFFERENCE",
        "fee_formula_difference_raw": _decimal_text(difference),
        "fee_candidate_execComm_raw": _decimal_text(candidate),
    }


def normalize_execution_value(
    event: dict[str, Any],
    spec: dict[str, Any],
    asset_registry: dict[str, dict[str, Any]],
    *,
    price_row: dict[str, Any] | None = None,
    resolved_lot_size: Any | None = None,
) -> dict[str, Any]:
    """Normalize one derivative execution while preserving component separation."""

    currency = _resolve_currency(event, spec, asset_registry)
    settlement_currency = currency["settlement_currency"]
    commission_currency = currency["commission_currency"]
    exec_cost = _parse_amount_field(event.get("execCost"), settlement_currency, asset_registry) if settlement_currency else {"raw": None, "major": None, "status": FAIL, "reason": "settlement currency unresolved"}
    exec_comm = _parse_amount_field(event.get("execComm"), commission_currency, asset_registry) if commission_currency else {"raw": None, "major": None, "status": FAIL, "reason": "commission currency unresolved"}
    realised = _parse_amount_field(event.get("realisedPnl"), settlement_currency, asset_registry) if settlement_currency else {"raw": None, "major": None, "status": FAIL, "reason": "settlement currency unresolved"}
    commission = _decimal(event.get("commission"))
    reasons = list(currency["reasons"])
    parse_results = {"execCost": exec_cost, "execComm": exec_comm, "realisedPnl": realised}
    for field, result in parse_results.items():
        if result["status"] in {INVALID_RAW_AMOUNT, NON_INTEGER_RAW_AMOUNT, FAIL}:
            reasons.append(f"{field}: {result['reason']}")
    if _raw_text(event.get("commission")) and commission is None:
        reasons.append("commission rate is not a finite Decimal")
    invalid = currency["status"] == FAIL or any(result["status"] in {INVALID_RAW_AMOUNT, NON_INTEGER_RAW_AMOUNT, FAIL} for result in parse_results.values())
    roundtrip_status = MISSING_ONLY
    present_results = [result for result in parse_results.values() if result["status"] != MISSING]
    if present_results:
        roundtrip_status = PASS if all(result["status"] == VALID for result in present_results) else FAIL
    fee = _fee_diagnostic(
        event,
        exec_cost,
        exec_comm,
        commission,
        comparable_currency=bool(commission_currency and commission_currency == settlement_currency),
    )
    if fee.get("fee_formula_status") == "DIAGNOSTIC_DIFFERENCE":
        reasons.append("candidate fee formula differs from actual execComm; actual execComm retained")
    if invalid:
        normalization_status = "BLOCKED"
    elif reasons:
        normalization_status = "WARNING"
    else:
        normalization_status = "PASS"
    canonical = _canonical_price_fields(event, price_row)
    definitions = {item["source_field"]: item for item in classify_execution_components(event)}
    roles = {
        "position_cost_role": definitions["execCost"]["accounting_role"],
        "exec_comm_role": definitions["execComm"]["accounting_role"],
        "realised_pnl_role": definitions["realisedPnl"]["accounting_role"],
    }
    return {
        "event_time": event.get("event_time", ""),
        "source_row_number": event.get("source_row_number"),
        "execID": event.get("execID", ""),
        "execType": event.get("execType", ""),
        "symbol": event.get("symbol", ""),
        "side": event.get("side", ""),
        "signed_contract_qty": str(event.get("signed_contract_qty")) if event.get("signed_contract_qty") is not None else None,
        "spec_id": spec.get("spec_id", ""),
        "payout_model": spec.get("payout_model", ""),
        "instrument_typ": event.get("instrument_typ", ""),
        "instrument_class": event.get("instrument_class", ""),
        "settlement_currency_raw": currency["settlement_currency_raw"],
        "settlement_currency": settlement_currency,
        "settlement_asset_scale": currency["settlement_asset_scale"],
        "commission_currency": commission_currency,
        "commission_currency_source": currency["commission_currency_source"],
        "commission_asset_scale": currency["commission_asset_scale"],
        "commission_rate": _decimal_text(commission),
        "execCost_raw": exec_cost["raw"],
        "execCost_major": exec_cost["major"],
        "execCost_parse_status": exec_cost["status"],
        "execComm_raw": exec_comm["raw"],
        "execComm_major": exec_comm["major"],
        "execComm_parse_status": exec_comm["status"],
        "realisedPnl_raw": realised["raw"],
        "realisedPnl_major": realised["major"],
        "realisedPnl_parse_status": realised["status"],
        "brokerCommission_raw": event.get("brokerCommission", "") or None,
        "brokerExecComm_raw": event.get("brokerExecComm", "") or None,
        "resolved_lot_size": resolved_lot_size if resolved_lot_size not in (None, "") else spec.get("lot_size"),
        "homeNotional": _decimal_text(_decimal(event.get("homeNotional"))),
        "foreignNotional": _decimal_text(_decimal(event.get("foreignNotional"))),
        "lastPx": _decimal_text(_decimal(event.get("lastPx"))),
        "avgPx": _decimal_text(_decimal(event.get("avgPx"))),
        "canonical_execution_price": canonical["canonical_execution_price"],
        "canonical_price_status": canonical["canonical_price_status"],
        "price_resolution_method": canonical["price_resolution_method"],
        "position_cost_role": roles["position_cost_role"],
        "exec_comm_role": roles["exec_comm_role"],
        "realised_pnl_role": roles["realised_pnl_role"],
        "raw_major_roundtrip_status": roundtrip_status,
        "normalization_status": normalization_status,
        "normalization_reason": "; ".join(dict.fromkeys(reasons)),
        "commission_sign": _sign_label(commission),
        "execComm_sign": _sign_label(_decimal(exec_comm.get("raw"))),
        "lastLiquidityInd": event.get("lastLiquidityInd", ""),
        "fee_formula_status": fee.get("fee_formula_status"),
        "fee_formula_difference_raw": fee.get("fee_formula_difference_raw"),
        "fee_candidate_execComm_raw": fee.get("fee_candidate_execComm_raw"),
        "execCost_present": exec_cost["status"] != MISSING,
        "execComm_present": exec_comm["status"] != MISSING,
        "realisedPnl_present": realised["status"] != MISSING,
        "orderID": event.get("orderID", ""),
        "trdMatchID": event.get("trdMatchID", ""),
    }


def build_component_ledger(valuations: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Build long-form components without producing a combined net cashflow."""

    components: list[dict[str, Any]] = []
    for valuation in valuations:
        event_type = clean(valuation.get("execType")).strip()
        for definition in classify_execution_components(valuation):
            source_field = definition["source_field"]
            if not valuation.get(f"{source_field}_present", False):
                continue
            currency = valuation.get("commission_currency") if source_field == "execComm" else valuation.get("settlement_currency")
            scale = valuation.get("commission_asset_scale") if source_field == "execComm" else valuation.get("settlement_asset_scale")
            raw = valuation.get(f"{source_field}_raw")
            major = valuation.get(f"{source_field}_major")
            parse_status = valuation.get(f"{source_field}_parse_status")
            components.append({
                "component_id": f"{valuation.get('execID', '')}:{source_field}",
                "execID": valuation.get("execID", ""),
                "event_time": valuation.get("event_time", ""),
                "source_row_number": valuation.get("source_row_number"),
                "symbol": valuation.get("symbol", ""),
                "execType": event_type,
                "component_type": definition["component_type"],
                "source_field": source_field,
                "currency": currency,
                "asset_scale": scale,
                "amount_raw_signed": raw,
                "amount_major_signed": major,
                "accounting_role": definition["accounting_role"],
                "is_position_cost_component": definition["is_position_cost_component"],
                "is_wallet_cashflow_candidate": definition["is_wallet_cashflow_candidate"],
                "overlap_status": definition["overlap_status"],
                "normalization_status": "PASS" if parse_status == VALID else "BLOCKED",
                "normalization_reason": "" if parse_status == VALID else valuation.get("normalization_reason", parse_status),
            })
    return components


def _field_statistics(valuations: list[dict[str, Any]], field: str) -> dict[str, int]:
    stats = {"total": len(valuations), "missing": 0, "zero": 0, "positive": 0, "negative": 0, "invalid": 0, "non_integer": 0}
    status_field = f"{field}_parse_status"
    for row in valuations:
        status = row.get(status_field)
        if status == MISSING:
            stats["missing"] += 1
        elif status == NON_INTEGER_RAW_AMOUNT:
            stats["non_integer"] += 1
        elif status in {INVALID_RAW_AMOUNT, FAIL}:
            stats["invalid"] += 1
        else:
            value = _decimal(row.get(f"{field}_raw"))
            if value is None:
                stats["invalid"] += 1
            elif value == 0:
                stats["zero"] += 1
            elif value > 0:
                stats["positive"] += 1
            else:
                stats["negative"] += 1
    return stats


def _sum_decimal(values: Iterable[Any]) -> str:
    total = Decimal("0")
    for value in values:
        parsed = _decimal(value)
        if parsed is not None:
            total += parsed
    return _decimal_text(total) or "0"


def summarize_execution_valuation(
    valuations: list[dict[str, Any]],
    components: list[dict[str, Any]],
) -> dict[str, Any]:
    """Create compact, currency-separated summaries for reports."""

    exec_type_counts = Counter(clean(row.get("execType")).strip() for row in valuations)
    component_type_counts = Counter(clean(row.get("component_type")).strip() for row in components)
    normalization_counts = Counter(clean(row.get("normalization_status")).strip() for row in valuations)
    commission_sources = Counter(clean(row.get("commission_currency_source")).strip() for row in valuations)
    currencies = Counter(clean(row.get("settlement_currency")).strip() for row in valuations if clean(row.get("settlement_currency")).strip())
    scale_rows: list[dict[str, Any]] = []
    for currency in sorted(currencies):
        rows = [row for row in valuations if row.get("settlement_currency") == currency]
        scales = sorted({row.get("settlement_asset_scale") for row in rows if row.get("settlement_asset_scale") is not None})
        scale_rows.append({
            "currency": currency,
            "asset_scale": scales[0] if len(scales) == 1 else ("CONFLICT" if scales else None),
            "execution_count": len(rows),
            "scale_available_count": sum(row.get("settlement_asset_scale") is not None for row in rows),
            "scale_missing_count": sum(row.get("settlement_asset_scale") is None for row in rows),
            "coverage_ratio": f"{Decimal(sum(row.get('settlement_asset_scale') is not None for row in rows)) / Decimal(len(rows)):.12f}" if rows else "0",
        })
    component_currency: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for component in components:
        component_currency[(component.get("component_type", ""), component.get("currency", ""))].append(component)
    component_summary = []
    for (component_type, currency), rows in sorted(component_currency.items()):
        component_summary.append({
            "component_type": component_type,
            "currency": currency,
            "component_count": len(rows),
            "raw_sum_signed": _sum_decimal(row.get("amount_raw_signed") for row in rows),
            "major_sum_signed": _sum_decimal(row.get("amount_major_signed") for row in rows),
            "normalization_failure_count": sum(row.get("normalization_status") != PASS for row in rows),
        })
    funding_rows = [row for row in valuations if row.get("execType") == FUNDING]
    funding_summary: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in funding_rows:
        funding_summary[(row.get("symbol", ""), row.get("settlement_currency", ""))].append(row)
    funding_groups = []
    for (symbol, currency), rows in sorted(funding_summary.items()):
        funding_groups.append({
            "symbol": symbol,
            "settlement_currency": currency,
            "funding_event_count": len(rows),
            "positive_execComm_count": sum(row.get("execComm_sign") == "POSITIVE" for row in rows),
            "negative_execComm_count": sum(row.get("execComm_sign") == "NEGATIVE" for row in rows),
            "zero_execComm_count": sum(row.get("execComm_sign") == "ZERO" for row in rows),
            "missing_execComm_count": sum(row.get("execComm_sign") == MISSING for row in rows),
            "execComm_raw_sum": _sum_decimal(row.get("execComm_raw") for row in rows),
            "execComm_major_sum": _sum_decimal(row.get("execComm_major") for row in rows),
            "first_event_time": min(row.get("event_time", "") for row in rows),
            "last_event_time": max(row.get("event_time", "") for row in rows),
            "normalization_failure_count": sum(row.get("normalization_status") == "BLOCKED" for row in rows),
        })
    trade_rows = [row for row in valuations if row.get("execType") == TRADE]
    fee_groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in trade_rows:
        fee_groups[(row.get("symbol", ""), row.get("settlement_currency", ""), row.get("lastLiquidityInd", ""))].append(row)
    trade_fee_summary = []
    for (symbol, currency, liquidity), rows in sorted(fee_groups.items()):
        trade_fee_summary.append({
            "symbol": symbol,
            "settlement_currency": currency,
            "lastLiquidityInd": liquidity,
            "trade_count": len(rows),
            "positive_execComm_count": sum(row.get("execComm_sign") == "POSITIVE" for row in rows),
            "negative_execComm_count": sum(row.get("execComm_sign") == "NEGATIVE" for row in rows),
            "zero_execComm_count": sum(row.get("execComm_sign") == "ZERO" for row in rows),
            "missing_execComm_count": sum(row.get("execComm_sign") == MISSING for row in rows),
            "positive_commission_count": sum(row.get("commission_sign") == "POSITIVE" for row in rows),
            "negative_commission_count": sum(row.get("commission_sign") == "NEGATIVE" for row in rows),
            "zero_commission_count": sum(row.get("commission_sign") == "ZERO" for row in rows),
            "fee_formula_exact_count": sum(row.get("fee_formula_status") == "EXACT" for row in rows),
            "fee_formula_difference_count": sum(row.get("fee_formula_status") == "DIAGNOSTIC_DIFFERENCE" for row in rows),
            "fee_formula_difference_raw_sum": _sum_decimal(row.get("fee_formula_difference_raw") for row in rows),
        })
    settlement_rows = [row for row in valuations if row.get("execType") == SETTLEMENT]
    settlement_summary = [{
        "event_time": row.get("event_time", ""),
        "execID": row.get("execID", ""),
        "symbol": row.get("symbol", ""),
        "spec_id": row.get("spec_id", ""),
        "settlement_currency": row.get("settlement_currency", ""),
        "asset_scale": row.get("settlement_asset_scale"),
        "execCost_raw": row.get("execCost_raw"),
        "execCost_major": row.get("execCost_major"),
        "execComm_raw": row.get("execComm_raw"),
        "execComm_major": row.get("execComm_major"),
        "realisedPnl_raw": row.get("realisedPnl_raw"),
        "realisedPnl_major": row.get("realisedPnl_major"),
        "settlement_status": row.get("normalization_status"),
        "normalization_status": row.get("normalization_status"),
    } for row in settlement_rows]
    raw_major_failures = sum(row.get("raw_major_roundtrip_status") == FAIL for row in valuations)
    canonical_counts = Counter(row.get("canonical_price_status", "") for row in valuations)
    canonical_methods = Counter(row.get("price_resolution_method", "") for row in valuations)
    return {
        "execution_count": len(valuations),
        "exec_type_counts": dict(exec_type_counts),
        "component_type_counts": dict(component_type_counts),
        "normalization_status_counts": dict(normalization_counts),
        "settlement_currency_counts": dict(currencies),
        "commission_currency_source_counts": dict(commission_sources),
        "scale_coverage": scale_rows,
        "field_statistics": {
            "execCost": _field_statistics(valuations, "execCost"),
            "execComm": _field_statistics(valuations, "execComm"),
            "realisedPnl": _field_statistics(valuations, "realisedPnl"),
        },
        "raw_major_roundtrip_failure_count": raw_major_failures,
        "component_summary": component_summary,
        "funding_summary": funding_groups,
        "trade_fee_summary": trade_fee_summary,
        "settlement_summary": settlement_summary,
        "canonical_price_status_counts": dict(canonical_counts),
        "canonical_price_method_counts": dict(canonical_methods),
        "canonical_historical_exact_count": canonical_counts.get("AUDITED_OBSERVED_EXACT", 0),
        "canonical_historical_recovered_count": canonical_counts.get("AUDITED_RECOVERED_FROM_EXECCOST", 0),
        "canonical_historical_unresolved_count": canonical_counts.get("AUDITED_UNRESOLVED", 0),
        "currency_component_summary": component_summary,
    }


def build_execution_valuation(
    normalized_events: Iterable[dict[str, Any]],
    registry: dict[str, Any],
    mapping_rows: Iterable[dict[str, Any]],
    asset_registry: dict[str, dict[str, Any]],
    *,
    price_reconciliation: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one valuation row per derivative execution and its component ledger."""

    events = [event for event in normalized_events if event.get("instrument_class") == "DERIVATIVE"]
    mapping_list = list(mapping_rows)
    mapping_by_exec: dict[str, dict[str, Any]] = {}
    duplicate_mapping_ids: list[str] = []
    for row in mapping_list:
        exec_id = clean(row.get("execID")).strip()
        if exec_id in mapping_by_exec:
            duplicate_mapping_ids.append(exec_id)
        mapping_by_exec[exec_id] = row
    specs = {clean(spec.get("spec_id")).strip(): spec for spec in registry.get("specs", [])}
    price_by_exec = {
        clean(row.get("execID")).strip(): row
        for row in (price_reconciliation or {}).get("rows", [])
        if clean(row.get("execID")).strip()
    }
    valuations: list[dict[str, Any]] = []
    anomalies: list[dict[str, Any]] = []
    for event in events:
        exec_id = clean(event.get("execID")).strip()
        mapping = mapping_by_exec.get(exec_id, {})
        spec_id = clean(mapping.get("spec_id")).strip()
        spec = specs.get(spec_id, {})
        price_row = price_by_exec.get(exec_id)
        valuation = normalize_execution_value(
            event,
            spec,
            asset_registry,
            price_row=price_row,
            resolved_lot_size=mapping.get("resolved_lot_size"),
        )
        valuation["spec_resolution_status"] = mapping.get("spec_resolution_status", "MISSING_SPEC")
        valuation["compatibility_status"] = mapping.get("compatibility_status", "MISSING_SPEC")
        valuation["terms_id"] = mapping.get("terms_id", "")
        valuation["terms_resolution_status"] = mapping.get("terms_resolution_status", "MISSING")
        if not spec_id or valuation["spec_resolution_status"] != "MATCHED" or valuation["compatibility_status"] != "PASS":
            valuation["normalization_status"] = "BLOCKED"
            valuation["normalization_reason"] = "; ".join(filter(None, [
                valuation.get("normalization_reason", ""),
                "resolved specification missing, incompatible, or not uniquely matched",
            ]))
        if valuation["normalization_status"] == "BLOCKED" or valuation["raw_major_roundtrip_status"] == FAIL:
            if len(anomalies) < 200:
                anomalies.append({
                    "execID": exec_id,
                    "event_time": valuation.get("event_time", ""),
                    "symbol": valuation.get("symbol", ""),
                    "execType": valuation.get("execType", ""),
                    "anomaly_type": "NORMALIZATION_BLOCKED",
                    "normalization_status": valuation.get("normalization_status", ""),
                    "reason": valuation.get("normalization_reason", ""),
                })
        valuations.append(valuation)
    components = build_component_ledger(valuations)
    summary = summarize_execution_valuation(valuations, components)
    summary["duplicate_mapping_execID_count"] = len(duplicate_mapping_ids)
    summary["duplicate_mapping_execIDs"] = duplicate_mapping_ids[:20]
    summary["join_input_row_count"] = len(events)
    summary["join_output_row_count"] = len(valuations)
    summary["anomaly_sample_count"] = len(anomalies)
    return {"valuations": valuations, "components": components, "summary": summary, "anomalies": anomalies}


__all__ = [
    "AssetScaleError", "FAIL", "FUNDING", "FUNDING_PAYMENT", "INVALID_RAW_AMOUNT", "MISSING", "MISSING_ONLY",
    "NON_INTEGER_RAW_AMOUNT", "PASS", "POSITION_COST", "RawAmountError", "REPORTED_REALISED_PNL", "SETTLEMENT",
    "SETTLEMENT_COMMISSION", "SETTLEMENT_POSITION_VALUE_REFERENCE", "TRADE", "TRADE_FEE_OR_REBATE", "VALID",
    "build_component_ledger", "build_execution_valuation", "classify_execution_components", "load_asset_scale_registry",
    "major_to_raw", "normalize_currency_code", "normalize_execution_value", "parse_raw_integer_decimal", "raw_to_major",
    "summarize_execution_valuation", "validate_raw_major_roundtrip",
]
