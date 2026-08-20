"""As-of market-context joins that never use a future observation."""

from __future__ import annotations

from bisect import bisect_right
from typing import Any, Iterable

from .download import iso_utc, parse_utc


def _asof_index(rows: Iterable[dict[str, Any]]) -> tuple[list[Any], list[dict[str, Any]]]:
    ordered = sorted((row for row in rows if parse_utc(row.get("timestamp")) is not None), key=lambda row: parse_utc(row.get("timestamp")))
    return [parse_utc(row.get("timestamp")) for row in ordered], ordered


def _join_one(event_time, times, rows):
    index = bisect_right(times, event_time) - 1
    if index < 0:
        return None, None
    source = rows[index]
    source_time = times[index]
    return source, int((event_time - source_time).total_seconds())


def attach_market_context(
    bars: Iterable[dict[str, Any]],
    *,
    instrument_rows: Iterable[dict[str, Any]] = (),
    funding_rows: Iterable[dict[str, Any]] = (),
    max_mark_age_seconds: int = 3600,
    max_funding_age_seconds: int = 9 * 3600,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    instrument_times, instruments = _asof_index(instrument_rows)
    funding_times, funding = _asof_index(funding_rows)
    output: list[dict[str, Any]] = []
    status_counts = {"COMPLETE": 0, "MARK_INDEX_MISSING": 0, "FUNDING_MISSING": 0, "STALE_CONTEXT": 0}
    for bar in sorted(bars, key=lambda row: parse_utc(row.get("timestamp"))):
        event_time = parse_utc(bar.get("timestamp"))
        if event_time is None:
            continue
        instrument, mark_age = _join_one(event_time, instrument_times, instruments)
        funding_row, funding_age = _join_one(event_time, funding_times, funding)
        result = dict(bar)
        result.update({
            "mark_price": instrument.get("mark_price") if instrument else None,
            "index_price": instrument.get("index_price") if instrument else None,
            "fair_price": instrument.get("fair_price") if instrument else None,
            "mark_source_timestamp_utc": iso_utc(instrument.get("timestamp")) if instrument else None,
            "mark_age_seconds": mark_age,
            "funding_rate": funding_row.get("funding_rate") if funding_row else None,
            "funding_rate_daily": funding_row.get("funding_rate_daily") if funding_row else None,
            "funding_source_timestamp_utc": iso_utc(funding_row.get("timestamp")) if funding_row else None,
            "funding_age_seconds": funding_age,
        })
        mark_ok = instrument is not None and mark_age is not None and mark_age <= max_mark_age_seconds and result.get("mark_price") is not None and result.get("index_price") is not None
        funding_ok = funding_row is not None and funding_age is not None and funding_age <= max_funding_age_seconds and funding_row.get("funding_rate") is not None
        if mark_ok and funding_ok:
            status = "COMPLETE"
        elif instrument is None or result.get("mark_price") is None or result.get("index_price") is None:
            status = "MARK_INDEX_MISSING"
        elif funding_row is None or funding_row.get("funding_rate") is None:
            status = "FUNDING_MISSING"
        else:
            status = "STALE_CONTEXT"
        result["context_status"] = status
        status_counts[status] += 1
        output.append(result)
    return output, {
        "row_count": len(output),
        "status_counts": status_counts,
        "instrument_source_row_count": len(instruments),
        "funding_source_row_count": len(funding),
        "join_policy": "ASOF_PREVIOUS_OR_EQUAL_UTC; FUTURE_OBSERVATIONS_FORBIDDEN",
        "max_mark_age_seconds": max_mark_age_seconds,
        "max_funding_age_seconds": max_funding_age_seconds,
    }


__all__ = ["attach_market_context"]
