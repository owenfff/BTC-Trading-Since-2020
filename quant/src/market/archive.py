"""Incremental reader for BitMEX's official daily public trade archive."""

from __future__ import annotations

import csv
import gzip
import hashlib
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Iterator

from .download import MarketDownloadError, fetch_bytes, iso_utc, parse_utc, utc_now


PUBLIC_ARCHIVE_BASE = "https://public.bitmex.com/data"


def archive_trade_url(day: date) -> str:
    return f"{PUBLIC_ARCHIVE_BASE}/trade/{day.strftime('%Y%m%d')}.csv.gz"


def _number(value: Any) -> float | int | None:
    if value in (None, ""):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return int(number) if number.is_integer() else number


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def fetch_daily_trade_file(day: date, raw_dir: Path, *, timeout: int = 60) -> tuple[Path, dict[str, Any]]:
    """Download one archive object or reuse an existing complete cache file."""
    path = raw_dir / "trade" / f"{day.strftime('%Y%m%d')}.csv.gz"
    url = archive_trade_url(day)
    if path.exists() and path.stat().st_size > 0:
        return path, {"date": day.isoformat(), "url": url, "status": "CACHED", "path": str(path), "size_bytes": path.stat().st_size, "sha256": _sha256(path), "download_time_utc": None}
    try:
        payload = fetch_bytes(url, timeout=timeout)
        if not payload.startswith(b"\x1f\x8b"):
            raise MarketDownloadError("archive object is not gzip data")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(payload)
        return path, {"date": day.isoformat(), "url": url, "status": "DOWNLOADED", "path": str(path), "size_bytes": len(payload), "sha256": hashlib.sha256(payload).hexdigest(), "download_time_utc": utc_now()}
    except MarketDownloadError as exc:
        return path, {"date": day.isoformat(), "url": url, "status": "FAILED", "path": str(path), "size_bytes": 0, "sha256": "", "download_time_utc": None, "error_type": type(exc).__name__, "error": str(exc)}


def iter_daily_trade_rows(path: Path) -> Iterator[dict[str, str]]:
    with gzip.open(path, "rt", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return
        for row in reader:
            yield {key: "" if value is None else value for key, value in row.items() if key is not None}


def aggregate_trade_rows(source_rows: Iterable[dict[str, Any]], *, symbol: str = "XBTUSD", interval_minutes: int = 5, start_time: datetime | None = None, end_time: datetime | None = None) -> list[dict[str, Any]]:
    """Aggregate raw trades into closed UTC bars without filling empty bars."""
    buckets: dict[datetime, dict[str, Any]] = {}
    for source_row_number, row in enumerate(source_rows, start=1):
        if str(row.get("symbol", "")).strip().upper() != symbol.upper():
            continue
        timestamp = parse_utc(row.get("timestamp"))
        price = _number(row.get("price"))
        size = _number(row.get("size"))
        if timestamp is None or price is None or price <= 0 or size is None:
            continue
        if start_time is not None and timestamp < start_time:
            continue
        if end_time is not None and timestamp > end_time:
            continue
        bucket_minute = (timestamp.minute // interval_minutes) * interval_minutes
        bucket_start = timestamp.replace(minute=bucket_minute, second=0, microsecond=0)
        bucket_end = bucket_start + timedelta(minutes=interval_minutes)
        item = buckets.setdefault(bucket_start, {"timestamp": iso_utc(bucket_end), "bar_start_time_utc": iso_utc(bucket_start), "bar_end_time_utc": iso_utc(bucket_end), "symbol": symbol, "open": None, "high": price, "low": price, "close": price, "volume": 0, "turnover": 0, "trades": 0, "source": "bitmex_public_archive_trade_aggregated", "source_row_first": source_row_number, "source_row_last": source_row_number})
        if item["open"] is None:
            item["open"] = price
        item["high"] = max(item["high"], price)
        item["low"] = min(item["low"], price)
        item["close"] = price
        item["volume"] += size
        foreign_notional = _number(row.get("foreignNotional"))
        gross_value = _number(row.get("grossValue"))
        item["turnover"] += foreign_notional if foreign_notional is not None else (gross_value or 0)
        item["trades"] += 1
        item["source_row_last"] = source_row_number
    return [buckets[key] for key in sorted(buckets)]


def download_archive_trade_bars(start_time: datetime, end_time: datetime, raw_dir: Path, *, symbol: str = "XBTUSD", interval_minutes: int = 5) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch every UTC day in the requested range; reject incomplete ranges."""
    current = start_time.date()
    last = end_time.date()
    expected_day_count = (last - current).days + 1
    consecutive_failures = 0
    not_attempted_day_count = 0
    all_bars: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    while current <= last:
        path, lineage = fetch_daily_trade_file(current, raw_dir)
        files.append(lineage)
        if lineage["status"] == "FAILED":
            consecutive_failures += 1
            if consecutive_failures >= 3:
                not_attempted_day_count = (last - current).days
                break
        else:
            consecutive_failures = 0
            try:
                all_bars.extend(aggregate_trade_rows(iter_daily_trade_rows(path), symbol=symbol, interval_minutes=interval_minutes, start_time=start_time, end_time=end_time))
            except (OSError, gzip.BadGzipFile, csv.Error) as exc:
                files[-1].update({"status": "FAILED", "error_type": type(exc).__name__, "error": str(exc)})
        current += timedelta(days=1)
    failed = [item for item in files if item.get("status") == "FAILED"]
    unique = {row["timestamp"]: row for row in all_bars}
    bars = [unique[key] for key in sorted(unique)]
    return bars if not failed else [], {"provider": "BitMEX", "endpoint": "public.bitmex.com/data/trade/YYYYMMDD.csv.gz", "symbol": symbol, "interval": f"{interval_minutes}m", "credentials": "none", "status": "PASS" if bars else ("FAILED_INCOMPLETE_RANGE" if failed else "EMPTY"), "requested_start_time_utc": iso_utc(start_time), "requested_end_time_utc": iso_utc(end_time), "day_count": expected_day_count, "attempted_day_count": len(files), "not_attempted_day_count": not_attempted_day_count, "failed_day_count": len(failed), "cached_day_count": sum(item.get("status") == "CACHED" for item in files), "downloaded_day_count": sum(item.get("status") == "DOWNLOADED" for item in files), "row_count": len(bars), "files": files, "official_archive": "https://public.bitmex.com/", "note": "Raw trade files are retained separately; bars are local UTC aggregations and do not include inferred mark/index/funding."}


__all__ = ["PUBLIC_ARCHIVE_BASE", "aggregate_trade_rows", "archive_trade_url", "download_archive_trade_bars", "fetch_daily_trade_file", "iter_daily_trade_rows"]
