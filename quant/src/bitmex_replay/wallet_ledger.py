from __future__ import annotations

import csv
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable

from .execution_valuation import load_asset_scale_registry, normalize_currency_code
from .io_utils import clean, iter_csv_dicts, parse_datetime


WALLET_TYPE_GROUPS = {
    "Deposit": "DEPOSIT",
    "Withdrawal": "WITHDRAWAL",
    "RealisedPNL": "REALISED_PNL",
    "Funding": "FUNDING",
    "Transfer": "TRANSFER",
    "Conversion": "CONVERSION",
    "SpotTrade": "SPOT_TRADE",
    "UnrealisedPNL": "UNREALISED_PNL",
}
COMPLETED = "Completed"


def _decimal(value: Any) -> Decimal | None:
    raw = clean(value).strip()
    if not raw:
        return None
    try:
        number = Decimal(raw)
    except (InvalidOperation, ValueError):
        return None
    return number if number.is_finite() else None


def _raw_text(value: Any) -> str | None:
    number = _decimal(value)
    if number is None:
        return None
    if number != number.to_integral_value():
        return None
    return format(number.to_integral_value(), "f")


def _major(raw: Decimal | None, scale: int | None) -> str | None:
    if raw is None or scale is None:
        return None
    return format(raw / (Decimal(10) ** scale), "f")


def _time_text(value: Any) -> str:
    parsed = parse_datetime(value)
    return parsed.isoformat().replace("+00:00", "Z") if parsed else ""


def _time_key(value: Any) -> datetime:
    return parse_datetime(value) or datetime.min.replace(tzinfo=timezone.utc)


def normalize_wallet_row(
    line_number: int,
    row: dict[str, str],
    asset_registry: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    timestamp = parse_datetime(row.get("timestamp"))
    transact_time = parse_datetime(row.get("transactTime"))
    # Wallet balance snapshots follow the export/ledger timestamp.  transactTime
    # can be earlier than timestamp for delayed wallet events such as withdrawals.
    event_dt = timestamp or transact_time
    raw_currency = clean(row.get("currency")).strip()
    currency = normalize_currency_code(raw_currency) or raw_currency.upper()
    asset = asset_registry.get(currency, {})
    scale = asset.get("scale")
    amount = _decimal(row.get("amount"))
    fee = _decimal(row.get("fee"))
    wallet_balance = _decimal(row.get("walletBalance"))
    margin_balance = _decimal(row.get("marginBalance"))
    status = clean(row.get("transactStatus")).strip()
    transaction_type = clean(row.get("transactType")).strip()
    group = WALLET_TYPE_GROUPS.get(transaction_type, "OTHER")
    parse_status = "PASS"
    parse_reason = ""
    for field, value in (("amount", amount), ("fee", fee), ("walletBalance", wallet_balance)):
        raw = clean(row.get(field)).strip()
        if raw and value is None:
            parse_status = "BLOCKED"
            parse_reason = f"{field} is not a finite Decimal"
        elif raw and value != value.to_integral_value():
            parse_status = "BLOCKED"
            parse_reason = f"{field} is not an integer raw wallet unit"
    return {
        "source_row_number": line_number,
        "timestamp": _time_text(timestamp),
        "transactTime": _time_text(transact_time),
        "event_time": _time_text(event_dt),
        "event_date": event_dt.date().isoformat() if event_dt else "",
        "transactType": transaction_type,
        "wallet_type_group": group,
        "transactStatus": status,
        "is_completed": status == COMPLETED,
        "raw_currency": raw_currency,
        "currency": currency,
        "asset_scale": scale,
        "network": clean(row.get("network")).strip(),
        "amount_raw": _raw_text(row.get("amount")),
        "amount_major": _major(amount, scale),
        "fee_raw": _raw_text(row.get("fee")),
        "fee_major": _major(fee, scale),
        "walletBalance_raw": _raw_text(row.get("walletBalance")),
        "walletBalance_major": _major(wallet_balance, scale),
        "marginBalance_raw": _raw_text(row.get("marginBalance")),
        "marginBalance_major": _major(margin_balance, scale),
        "orderID": clean(row.get("orderID")).strip(),
        "transactID": clean(row.get("transactID")).strip(),
        "address_redacted": clean(row.get("address")).strip() in {"", "Redacted"},
        "address_present": bool(clean(row.get("address")).strip()),
        "parse_status": parse_status,
        "parse_reason": parse_reason,
    }


def load_wallet_ledger(path: Path, asset_registry: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    rows = [normalize_wallet_row(line, row, asset_registry) for line, row in iter_csv_dicts(Path(path))]
    rows.sort(key=lambda row: (_time_key(row.get("event_time")), _time_key(row.get("timestamp")), int(row.get("source_row_number") or 0)))
    batches: dict[str, dict[str, Any]] = {}
    previous: dict[str, Decimal] = {}
    batch_number: dict[str, int] = defaultdict(int)

    def finalize(currency: str, batch: dict[str, Any]) -> None:
        members = batch["rows"]
        balance = batch["balance"]
        amount_total = sum((_decimal(row.get("amount_raw")) or Decimal(0) for row in members), Decimal(0))
        prior = previous.get(currency)
        if prior is None:
            batch_status = "BASELINE_FIRST_OBSERVATION"
            delta = None
        elif balance is None:
            batch_status = "NOT_EVALUATED_MISSING_BALANCE"
            delta = None
        else:
            delta = balance - prior
            batch_status = "PASS" if delta == amount_total else "BALANCE_DELTA_MISMATCH"
        batch_number[currency] += 1
        batch_id = f"{currency}-{batch_number[currency]:06d}"
        for row in members:
            row["continuity_batch_id"] = batch_id
            row["continuity_batch_row_count"] = len(members)
            row["previous_walletBalance_raw"] = format(prior, "f") if prior is not None else None
            row["balance_delta_raw"] = format(delta, "f") if delta is not None else None
            row["balance_expected_delta_raw"] = format(amount_total, "f") if delta is not None or prior is None else None
            row["continuity_batch_status"] = batch_status
            row["continuity_status"] = batch_status
        if balance is not None:
            previous[currency] = balance

    for row in rows:
        currency = str(row.get("currency", ""))
        if not row["is_completed"]:
            row["continuity_status"] = "NOT_APPLICABLE_NON_COMPLETED"
            row["continuity_batch_status"] = "NOT_APPLICABLE_NON_COMPLETED"
            continue
        balance = _decimal(row.get("walletBalance_raw"))
        amount = _decimal(row.get("amount_raw"))
        if balance is None or amount is None:
            row["continuity_status"] = "NOT_EVALUATED_MISSING_AMOUNT_OR_BALANCE"
            row["continuity_batch_status"] = row["continuity_status"]
            continue
        current = batches.get(currency)
        if current is None or current["balance"] != balance:
            if current is not None:
                finalize(currency, current)
            current = {"balance": balance, "rows": []}
            batches[currency] = current
        current["rows"].append(row)
    for currency, batch in batches.items():
        finalize(currency, batch)
    return rows


def build_daily_wallet_ledger(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row.get("event_date") and row.get("is_completed"):
            groups[(str(row.get("event_date")), str(row.get("currency", "")))].append(row)
    daily: list[dict[str, Any]] = []
    for (event_date, currency), group in sorted(groups.items()):
        amount = sum((_decimal(row.get("amount_raw")) or Decimal(0) for row in group), Decimal(0))
        fee = sum((_decimal(row.get("fee_raw")) or Decimal(0) for row in group), Decimal(0))
        last = max(group, key=lambda row: (_time_key(row.get("event_time")), int(row.get("source_row_number") or 0)))
        scales = {row.get("asset_scale") for row in group if row.get("asset_scale") is not None}
        scale = next(iter(scales)) if len(scales) == 1 else None
        daily.append({
            "event_date": event_date,
            "currency": currency,
            "asset_scale": scale,
            "event_count": len(group),
            "transaction_type_count": len({row.get("transactType") for row in group}),
            "net_amount_raw": format(amount, "f"),
            "net_amount_major": _major(amount, scale),
            "fee_raw": format(fee, "f"),
            "fee_major": _major(fee, scale),
            "last_event_time": last.get("event_time", ""),
            "last_walletBalance_raw": last.get("walletBalance_raw"),
            "last_walletBalance_major": last.get("walletBalance_major"),
        })
    return daily


def summarize_wallet_by_type(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row.get("wallet_type_group", "OTHER")), str(row.get("transactType", "")), str(row.get("currency", "")))].append(row)
    output: list[dict[str, Any]] = []
    for (group_name, transaction_type, currency), group in sorted(groups.items()):
        amount = sum((_decimal(row.get("amount_raw")) or Decimal(0) for row in group if row.get("is_completed")), Decimal(0))
        fee = sum((_decimal(row.get("fee_raw")) or Decimal(0) for row in group if row.get("is_completed")), Decimal(0))
        scales = {row.get("asset_scale") for row in group if row.get("asset_scale") is not None}
        scale = next(iter(scales)) if len(scales) == 1 else None
        output.append({
            "wallet_type_group": group_name,
            "transactType": transaction_type,
            "currency": currency,
            "asset_scale": scale,
            "row_count": len(group),
            "completed_count": sum(row.get("is_completed") is True for row in group),
            "pending_count": sum(row.get("transactStatus") == "Pending" for row in group),
            "canceled_count": sum(row.get("transactStatus") == "Canceled" for row in group),
            "amount_raw_completed_sum": format(amount, "f"),
            "amount_major_completed_sum": _major(amount, scale),
            "fee_raw_completed_sum": format(fee, "f"),
            "fee_major_completed_sum": _major(fee, scale),
            "first_event_time": min(row.get("event_time", "") for row in group),
            "last_event_time": max(row.get("event_time", "") for row in group),
        })
    return output


def reconcile_wallet_snapshots(rows: Iterable[dict[str, Any]], snapshot_path: Path) -> list[dict[str, Any]]:
    ledger = list(rows)
    snapshots = list(iter_csv_dicts(Path(snapshot_path)))
    output: list[dict[str, Any]] = []
    for line, snapshot in snapshots:
        currency = normalize_currency_code(snapshot.get("currency")) or clean(snapshot.get("currency")).strip().upper()
        snapshot_dt = parse_datetime(snapshot.get("timestamp"))
        candidates = [
            row for row in ledger
            if row.get("currency") == currency and row.get("is_completed") and (snapshot_dt is None or parse_datetime(row.get("event_time")) is None or parse_datetime(row.get("event_time")) <= snapshot_dt)
        ]
        last = max(candidates, key=lambda row: (_time_key(row.get("event_time")), int(row.get("source_row_number") or 0)), default=None)
        expected = _raw_text(snapshot.get("amount"))
        actual = last.get("walletBalance_raw") if last else None
        if actual is None and expected == "0":
            status = "ZERO_SNAPSHOT_NO_HISTORY"
        else:
            status = "PASS" if actual is not None and expected is not None and Decimal(actual) == Decimal(expected) else "UNRESOLVED_OR_MISMATCH"
        output.append({
            "snapshot_source_row": line,
            "snapshot_timestamp": _time_text(snapshot.get("timestamp")),
            "currency": currency,
            "snapshot_amount_raw": expected,
            "reconstructed_last_walletBalance_raw": actual,
            "last_event_time": last.get("event_time", "") if last else "",
            "difference_raw": format(Decimal(actual) - Decimal(expected), "f") if actual is not None and expected is not None else None,
            "status": status,
        })
    return output


def reconcile_equity_curve(rows: Iterable[dict[str, Any]], equity_path: Path) -> dict[str, Any]:
    wallet_xbt = [row for row in rows if row.get("currency") == "XBT" and row.get("is_completed") and row.get("walletBalance_major") not in (None, "")]
    equity = [row for _, row in iter_csv_dicts(Path(equity_path))]
    last_wallet = max(wallet_xbt, key=lambda row: (_time_key(row.get("event_time")), int(row.get("source_row_number") or 0)), default=None)
    last_equity = max(equity, key=lambda row: (_time_key(row.get("timestamp")), _time_key(row.get("transactTime"))), default=None)
    actual = _decimal(last_wallet.get("walletBalance_major")) if last_wallet else None
    expected = _decimal(last_equity.get("walletBalanceXBT")) if last_equity else None
    return {
        "wallet_last_event_time": last_wallet.get("event_time", "") if last_wallet else "",
        "equity_last_event_time": last_equity.get("timestamp", "") if last_equity else "",
        "wallet_balance_xbt_major": format(actual, "f") if actual is not None else None,
        "equity_walletBalanceXBT": format(expected, "f") if expected is not None else None,
        "difference_xbt_major": format(actual - expected, "f") if actual is not None and expected is not None else None,
        "status": "PASS" if actual is not None and expected is not None and actual == expected else "UNRESOLVED_OR_MISMATCH",
        "equity_row_count": len(equity),
    }


def build_execution_aggregate(execution_path: Path) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str], dict[str, Any]] = {}
    for line, row in iter_csv_dicts(Path(execution_path)):
        exec_type = clean(row.get("execType")).strip()
        currency = normalize_currency_code(row.get("settlCurrency")) or normalize_currency_code(row.get("currency"))
        event_dt = parse_datetime(row.get("transactTime")) or parse_datetime(row.get("timestamp"))
        event_date = event_dt.date().isoformat() if event_dt else ""
        key = (exec_type, currency, event_date)
        item = groups.setdefault(key, {"execType": exec_type, "currency": currency, "event_date": event_date, "execution_count": 0, "realisedPnl_present_count": 0, "realisedPnl_raw_sum": Decimal(0), "execComm_present_count": 0, "execComm_raw_sum": Decimal(0)})
        item["execution_count"] += 1
        realised = _decimal(row.get("realisedPnl"))
        comm = _decimal(row.get("execComm"))
        if realised is not None:
            item["realisedPnl_present_count"] += 1
            item["realisedPnl_raw_sum"] += realised
        if comm is not None:
            item["execComm_present_count"] += 1
            item["execComm_raw_sum"] += comm
    output = []
    for item in sorted(groups.values(), key=lambda row: (row["event_date"], row["execType"], row["currency"])):
        output.append({**item, "realisedPnl_raw_sum": format(item["realisedPnl_raw_sum"], "f"), "execComm_raw_sum": format(item["execComm_raw_sum"], "f")})
    return output


def compare_wallet_execution_aggregates(wallet_type_rows: list[dict[str, Any]], execution_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    wallet_by_key = {(row.get("transactType"), row.get("currency")): row for row in wallet_type_rows}
    execution_by_type_currency: dict[tuple[str, str], dict[str, Decimal]] = defaultdict(lambda: {"realised": Decimal(0), "comm": Decimal(0), "rows": Decimal(0)})
    for row in execution_rows:
        key = (row.get("execType"), row.get("currency"))
        execution_by_type_currency[key]["realised"] += _decimal(row.get("realisedPnl_raw_sum")) or Decimal(0)
        execution_by_type_currency[key]["comm"] += _decimal(row.get("execComm_raw_sum")) or Decimal(0)
        execution_by_type_currency[key]["rows"] += Decimal(row.get("execution_count") or 0)
    comparisons: list[dict[str, Any]] = []
    for wallet_type, exec_type, source_field in (("RealisedPNL", "Trade", "realised"), ("Funding", "Funding", "comm")):
        for currency in sorted({key[1] for key in wallet_by_key if key[0] == wallet_type} | {key[1] for key in execution_by_type_currency if key[0] == exec_type}):
            wallet = wallet_by_key.get((wallet_type, currency), {})
            wallet_value = _decimal(wallet.get("amount_raw_completed_sum"))
            execution_value = execution_by_type_currency.get((exec_type, currency), {}).get(source_field, Decimal(0))
            status = "NOT_COMPARABLE_NO_WALLET_OR_EXECUTION_VALUE"
            if wallet_value is not None and execution_value is not None:
                status = "AGGREGATE_EXACT" if wallet_value == execution_value else "AGGREGATE_DIFFERENCE"
            comparisons.append({
                "wallet_type": wallet_type,
                "execution_type": exec_type,
                "currency": currency,
                "wallet_amount_raw": format(wallet_value, "f") if wallet_value is not None else None,
                "execution_comparison_field": source_field,
                "execution_amount_raw": format(execution_value, "f") if execution_value is not None else None,
                "difference_raw": format(wallet_value - execution_value, "f") if wallet_value is not None and execution_value is not None else None,
                "status": status,
                "note": "Aggregate diagnostic only; no fabricated one-to-one wallet-to-execution mapping.",
            })
    return comparisons


__all__ = [
    "WALLET_TYPE_GROUPS",
    "build_daily_wallet_ledger",
    "build_execution_aggregate",
    "compare_wallet_execution_aggregates",
    "load_asset_scale_registry",
    "load_wallet_ledger",
    "normalize_wallet_row",
    "reconcile_equity_curve",
    "reconcile_wallet_snapshots",
    "summarize_wallet_by_type",
]
