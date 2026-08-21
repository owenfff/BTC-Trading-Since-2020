"""Normalize public BitMEX market responses to UTC research rows."""

from __future__ import annotations

from collections import Counter
from collections import defaultdict
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


def resample_trade_bars(
    source_rows: Iterable[dict[str, Any]],
    *,
    source_interval_minutes: int = 5,
    target_interval_minutes: int = 60,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Derive larger UTC bars without filling missing source bars."""
    if source_interval_minutes <= 0 or target_interval_minutes <= source_interval_minutes:
        raise ValueError("target interval must be larger than the source interval")
    if target_interval_minutes % source_interval_minutes:
        raise ValueError("target interval must be a multiple of the source interval")
    source = sorted(
        (row for row in source_rows if parse_utc(row.get("timestamp")) is not None),
        key=lambda row: parse_utc(row.get("timestamp")),
    )
    buckets: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    target_delta = timedelta(minutes=target_interval_minutes)
    for row in source:
        timestamp = parse_utc(row["timestamp"])
        assert timestamp is not None
        bucket_end = timestamp.replace(minute=0, second=0, microsecond=0)
        if timestamp.minute or timestamp.second or timestamp.microsecond:
            bucket_end += timedelta(hours=1)
        buckets[bucket_end].append(row)

    expected_child_count = target_interval_minutes // source_interval_minutes
    output: list[dict[str, Any]] = []
    for bucket_end in sorted(buckets):
        children = buckets[bucket_end]
        values = [float(row[field]) for row in children for field in ("open", "high", "low", "close") if row.get(field) is not None]
        volume = sum(float(row.get("volume") or 0) for row in children)
        turnover = sum(float(row.get("turnover") or 0) for row in children)
        output.append({
            "symbol": children[0].get("symbol", "XBTUSD"),
            "bar_interval": f"{target_interval_minutes}m" if target_interval_minutes < 60 else f"{target_interval_minutes // 60}h",
            "bar_start_time_utc": iso_utc(bucket_end - target_delta),
            "bar_end_time_utc": iso_utc(bucket_end),
            "timestamp": iso_utc(bucket_end),
            "open": children[0].get("open"),
            "high": max(float(row["high"]) for row in children if row.get("high") is not None),
            "low": min(float(row["low"]) for row in children if row.get("low") is not None),
            "close": children[-1].get("close"),
            "volume": volume,
            "turnover": turnover,
            "vwap": (turnover / volume) if volume else None,
            "child_bar_count": len(children),
            "expected_child_bar_count": expected_child_count,
            "child_coverage_ratio": len(children) / expected_child_count,
            "source": "derived_from_bitmex_trade_bucketed_5m",
        })
    return output, {
        "source_row_count": len(source),
        "normalized_row_count": len(output),
        "target_interval": output[0]["bar_interval"] if output else f"{target_interval_minutes // 60}h",
        "expected_child_count": expected_child_count,
        "incomplete_target_bar_count": sum(row["child_bar_count"] < expected_child_count for row in output),
        "note": "Derived by UTC bucket aggregation; no missing 5m child bar is filled.",
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


__all__ = ["normalize_funding", "normalize_instrument", "normalize_trade_bars", "resample_trade_bars"]
