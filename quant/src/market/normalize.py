"""Normalize public BitMEX market responses to UTC research rows."""

from __future__ import annotations

from collections import Counter
from datetime import timedelta
from typing import Any, Iterable

from .download import iso_utc, parse_utc


def _number(value: Any) -> int | float | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return int(number) if number.is_integer() else number


def _time_key(row: dict[str, Any]) -> Any:
    return parse_utc(row.get("timestamp"))


def normalize_trade_bars(
    source_rows: Iterable[dict[str, Any]],
    *,
    symbol: str = "XBTUSD",
    interval: str = "5m",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Normalize bucketed trade candles without filling missing bars."""
    source_rows = list(source_rows)
    interval_minutes = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "1d": 1440}.get(interval)
    if interval_minutes is None:
        raise ValueError(f"unsupported BitMEX interval: {interval}")
    output: list[dict[str, Any]] = []
    rejected = Counter()
    for source_row_number, source in enumerate(source_rows, start=1):
        timestamp = parse_utc(source.get("timestamp"))
        if timestamp is None:
            rejected["timestamp_parse_failed"] += 1
            continue
        if str(source.get("symbol") or symbol).upper() != symbol.upper():
            rejected["symbol_mismatch"] += 1
            continue
        values = {field: _number(source.get(field)) for field in ("open", "high", "low", "close", "volume", "turnover", "vwap")}
        if any(values[field] is None for field in ("open", "high", "low", "close")):
            rejected["missing_ohlc"] += 1
            continue
        if min(values[field] for field in ("open", "high", "low", "close")) <= 0:
            rejected["non_positive_ohlc"] += 1
            continue
        output.append({
            "source_row_number": source_row_number,
            "symbol": symbol,
            "bar_interval": interval,
            "bar_start_time_utc": iso_utc(timestamp - timedelta(minutes=interval_minutes)),
            "bar_end_time_utc": iso_utc(timestamp),
            "timestamp": iso_utc(timestamp),
            **values,
            "source": "bitmex_trade_bucketed",
        })
    output.sort(key=lambda row: parse_utc(row["timestamp"]))
    duplicate_count = sum(count - 1 for count in Counter(row["timestamp"] for row in output).values() if count > 1)
    unique: dict[str, dict[str, Any]] = {}
    for row in output:
        unique[row["timestamp"]] = row
    output = [unique[key] for key in sorted(unique)]
    return output, {
        "source_row_count": len(source_rows),
        "normalized_row_count": len(output),
        "rejected_counts": dict(rejected),
        "duplicate_row_count": duplicate_count,
        "interval": interval,
    }


def normalize_funding(source_rows: Iterable[dict[str, Any]], *, symbol: str = "XBTUSD") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output: list[dict[str, Any]] = []
    rejected = Counter()
    for source_row_number, source in enumerate(source_rows, start=1):
        timestamp = parse_utc(source.get("timestamp"))
        if timestamp is None:
            rejected["timestamp_parse_failed"] += 1
            continue
        if str(source.get("symbol") or symbol).upper() != symbol.upper():
            rejected["symbol_mismatch"] += 1
            continue
        output.append({
            "source_row_number": source_row_number,
            "symbol": symbol,
            "timestamp": iso_utc(timestamp),
            "funding_rate": _number(source.get("fundingRate")),
            "funding_rate_daily": _number(source.get("fundingRateDaily")),
            "funding_interval": source.get("fundingInterval"),
            "source": "bitmex_funding",
        })
    output.sort(key=lambda row: parse_utc(row["timestamp"]))
    return output, {"source_row_count": len(output) + sum(rejected.values()), "normalized_row_count": len(output), "rejected_counts": dict(rejected)}


def normalize_instrument(source_rows: Iterable[dict[str, Any]], *, symbol: str = "XBTUSD") -> tuple[list[dict[str, Any]], dict[str, Any]]:
    output: list[dict[str, Any]] = []
    rejected = Counter()
    fields = ("markPrice", "indexPrice", "fairPrice", "lastPrice", "indicativeSettlePrice", "midPrice")
    for source_row_number, source in enumerate(source_rows, start=1):
        timestamp = parse_utc(source.get("timestamp"))
        if timestamp is None:
            rejected["timestamp_parse_failed"] += 1
            continue
        row = {field: _number(source.get(field)) for field in fields}
        if not any(value is not None for value in row.values()):
            rejected["no_context_price"] += 1
            continue
        output.append({
            "source_row_number": source_row_number,
            "symbol": symbol,
            "timestamp": iso_utc(timestamp),
            "mark_price": row["markPrice"],
            "index_price": row["indexPrice"],
            "fair_price": row["fairPrice"],
            "last_price": row["lastPrice"],
            "indicative_settle_price": row["indicativeSettlePrice"],
            "mid_price": row["midPrice"],
            "source": "bitmex_instrument",
        })
    output.sort(key=lambda row: parse_utc(row["timestamp"]))
    return output, {"source_row_count": len(output) + sum(rejected.values()), "normalized_row_count": len(output), "rejected_counts": dict(rejected)}


__all__ = ["normalize_funding", "normalize_instrument", "normalize_trade_bars"]
