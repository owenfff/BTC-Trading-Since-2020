"""Public no-key hourly market context for the cross-asset dataset."""

from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from market.download import (
    MarketDownloadError,
    build_funding_url,
    build_trade_bucketed_url,
    download_windowed,
    parse_utc,
)
from market.normalize import resample_trade_bars


UTC = timezone.utc
HOUR_SECONDS = 3600
BAR_FIELDS = [
    "symbol", "timestamp", "bar_interval", "open", "high", "low", "close",
    "volume", "turnover", "mark_price", "index_price", "funding_rate",
    "funding_source_timestamp_utc", "source",
]


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _compact_bar(row: dict[str, Any], symbol: str, source: str) -> dict[str, Any] | None:
    timestamp = parse_utc(row.get("timestamp"))
    close = _number(row.get("close"))
    if timestamp is None or close is None or close <= 0:
        return None
    return {
        "symbol": symbol,
        "timestamp": _iso(timestamp),
        "bar_interval": "1h",
        "open": _number(row.get("open")),
        "high": _number(row.get("high")),
        "low": _number(row.get("low")),
        "close": close,
        "volume": _number(row.get("volume")),
        "turnover": _number(row.get("turnover")),
        "mark_price": _number(row.get("mark_price")),
        "index_price": _number(row.get("index_price")),
        "funding_rate": _number(row.get("funding_rate")),
        "funding_source_timestamp_utc": "",
        "source": source,
    }


def _load_xbtusd_hourly(market_context_path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with market_context_path.open("r", encoding="utf-8", newline="") as handle:
        for source in csv.DictReader(handle):
            timestamp = parse_utc(source.get("timestamp"))
            if timestamp is None or str(source.get("symbol") or "").upper() != "XBTUSD":
                continue
            rows.append({
                "timestamp": _iso(timestamp),
                "symbol": "XBTUSD",
                "open": _number(source.get("open")),
                "high": _number(source.get("high")),
                "low": _number(source.get("low")),
                "close": _number(source.get("close")),
                "volume": _number(source.get("volume")),
                "turnover": _number(source.get("turnover")),
                "mark_price": _number(source.get("mark_price")),
                "index_price": _number(source.get("index_price")),
                "funding_rate": _number(source.get("funding_rate")),
                "funding_source_timestamp_utc": source.get("funding_source_timestamp_utc", ""),
            })
    hourly, _ = resample_trade_bars(rows, source_interval_minutes=5, target_interval_minutes=60)
    output: list[dict[str, Any]] = []
    for row in hourly:
        compact = _compact_bar(row, "XBTUSD", "derived_from_verified_xbtusd_5m")
        if compact:
            output.append(compact)
    return output


def _join_funding(bars: list[dict[str, Any]], funding_rows: list[dict[str, Any]]) -> None:
    funding = []
    for row in funding_rows:
        timestamp = parse_utc(row.get("timestamp"))
        rate = _number(row.get("fundingRate"))
        if timestamp is not None and rate is not None:
            funding.append((timestamp, rate))
    funding.sort()
    index = 0
    latest: tuple[datetime, float] | None = None
    for bar in sorted(bars, key=lambda item: item["timestamp"]):
        timestamp = parse_utc(bar["timestamp"])
        if timestamp is None:
            continue
        while index < len(funding) and funding[index][0] <= timestamp:
            latest = funding[index]
            index += 1
        if latest is not None:
            bar["funding_rate"] = latest[1]
            bar["funding_source_timestamp_utc"] = _iso(latest[0])


def _audit(symbol: str, bars: list[dict[str, Any]], first_decision: datetime, last_decision: datetime, status: str, error: str = "") -> dict[str, Any]:
    times = [parse_utc(row["timestamp"]) for row in bars]
    clean_times = [value for value in times if value is not None]
    duplicate_count = len(clean_times) - len(set(clean_times))
    gaps = 0
    for left, right in zip(sorted(set(clean_times)), sorted(set(clean_times))[1:]):
        if int((right - left).total_seconds()) != HOUR_SECONDS:
            gaps += max(0, int((right - left).total_seconds() // HOUR_SECONDS) - 1)
    covered = bool(clean_times) and min(clean_times) <= first_decision and max(clean_times) >= last_decision
    coverage_status = "PASS" if status == "PASS" and covered else ("FAILED" if status == "FAILED" else "INSUFFICIENT")
    return {
        "symbol": symbol,
        "status": status,
        "coverage_status": coverage_status,
        "row_count": len(bars),
        "duplicate_timestamp_count": duplicate_count,
        "hour_grid_gap_count": gaps,
        "first_bar_time_utc": _iso(min(clean_times)) if clean_times else "",
        "last_bar_time_utc": _iso(max(clean_times)) if clean_times else "",
        "first_decision_time_utc": _iso(first_decision),
        "last_decision_time_utc": _iso(last_decision),
        "mark_index_available_count": sum(row.get("mark_price") is not None and row.get("index_price") is not None for row in bars),
        "funding_available_count": sum(row.get("funding_rate") is not None for row in bars),
        "error": error,
    }


def build_cross_asset_market(
    root: Path,
    decision_ranges: dict[str, tuple[datetime, datetime]],
    *,
    fetcher: Callable[..., tuple[list[dict[str, Any]], dict[str, Any]]] = download_windowed,
) -> dict[str, Any]:
    """Build an ignored hourly context cache and a small coverage manifest."""
    outputs = root / "quant" / "outputs"
    cache_dir = outputs / "cross_asset_market" / "raw"
    cache_dir.mkdir(parents=True, exist_ok=True)
    all_bars: list[dict[str, Any]] = []
    audits: list[dict[str, Any]] = []
    xbt_rows = _load_xbtusd_hourly(outputs / "market_context.csv") if "XBTUSD" in decision_ranges else []

    for symbol, (first_decision, last_decision) in sorted(decision_ranges.items()):
        if symbol == "XBTUSD":
            bars = [row for row in xbt_rows if first_decision - timedelta(days=4) <= parse_utc(row["timestamp"]) <= last_decision + timedelta(hours=1)]
            audits.append(_audit(symbol, bars, first_decision, last_decision, "PASS" if bars else "FAILED"))
            all_bars.extend(bars)
            continue

        start = first_decision - timedelta(days=4)
        end = last_decision + timedelta(hours=1)
        try:
            raw_bars, market_lineage = fetcher(
                lambda **kwargs: build_trade_bucketed_url(symbol, "1h", **kwargs),
                cache_dir=cache_dir / "bars",
                cache_stem=f"{symbol}_1h",
                start_time=start,
                end_time=end,
                window_days=30,
                timeout=60,
                page_limit=1000,
                sleep_seconds=0.05,
                retries=2,
            )
            bars = [compact for row in raw_bars if (compact := _compact_bar(row, symbol, "bitmex_public_trade_bucketed_1h"))]
            try:
                raw_funding, _ = fetcher(
                    lambda **kwargs: build_funding_url(symbol, **kwargs),
                    cache_dir=cache_dir / "funding",
                    cache_stem=f"{symbol}_funding",
                    start_time=start,
                    end_time=end,
                    window_days=365,
                    timeout=60,
                    page_limit=1000,
                    sleep_seconds=0.05,
                    retries=1,
                )
            except MarketDownloadError:
                raw_funding = []
            _join_funding(bars, raw_funding)
            audits.append({**_audit(symbol, bars, first_decision, last_decision, "PASS"), "market_lineage": market_lineage})
            all_bars.extend(bars)
        except MarketDownloadError as exc:
            audits.append(_audit(symbol, [], first_decision, last_decision, "FAILED", str(exc)))

    all_bars.sort(key=lambda row: (row["symbol"], row["timestamp"]))
    path = outputs / "cross_asset_market_context.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=BAR_FIELDS)
        writer.writeheader()
        writer.writerows(all_bars)
    coverage = {
        "report_version": "M13-CROSS-ASSET-MARKET-1.0",
        "interval": "1h",
        "provider": "BitMEX public endpoints",
        "credentials": "none",
        "synthetic_market_data": False,
        "symbols_requested": sorted(decision_ranges),
        "symbol_count": len(decision_ranges),
        "bars_written": len(all_bars),
        "coverage": audits,
        "coverage_status": "PASS" if all(item["coverage_status"] == "PASS" for item in audits) else "PARTIAL_COVERAGE",
        "notes": "Historical mark/index values remain missing unless present in the verified XBTUSD source; current snapshots are never backfilled.",
    }
    (outputs / "cross_asset_market_coverage.json").write_text(json.dumps(coverage, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return coverage


__all__ = ["build_cross_asset_market"]
