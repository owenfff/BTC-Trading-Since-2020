"""No-key BitMEX public market-data download helpers.

The downloader is deliberately small and standard-library only.  It never
accepts API credentials: this package is for research context, not account
access or order placement.  Raw responses are cached under the ignored
``quant/outputs`` tree and their hashes are recorded in the lineage report.
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


PUBLIC_API_ROOT = "https://www.bitmex.com/api/v1"
MAX_PAGE_SIZE = 500


class MarketDownloadError(RuntimeError):
    """A public market source could not be downloaded or decoded."""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    else:
        text = str(value or "").strip()
        if not text:
            return None
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        try:
            parsed = datetime.fromisoformat(text)
        except ValueError:
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def iso_utc(value: Any) -> str:
    parsed = parse_utc(value)
    return parsed.isoformat(timespec="milliseconds").replace("+00:00", "Z") if parsed else ""


def _url(path: str, params: dict[str, Any]) -> str:
    clean = {key: value for key, value in params.items() if value not in (None, "")}
    suffix = urlencode(clean, doseq=True)
    return f"{PUBLIC_API_ROOT}/{path.lstrip('/')}" + (f"?{suffix}" if suffix else "")


def build_trade_bucketed_url(
    symbol: str,
    bin_size: str,
    *,
    start_time: Any = None,
    end_time: Any = None,
    count: int = MAX_PAGE_SIZE,
    start: int = 0,
    reverse: bool = False,
) -> str:
    return _url("trade/bucketed", {
        "symbol": symbol,
        "binSize": bin_size,
        "partial": "false",
        "count": count,
        "start": start,
        "reverse": "true" if reverse else "false",
        "startTime": iso_utc(start_time),
        "endTime": iso_utc(end_time),
    })


def build_funding_url(
    symbol: str,
    *,
    start_time: Any = None,
    end_time: Any = None,
    count: int = MAX_PAGE_SIZE,
    start: int = 0,
    reverse: bool = False,
) -> str:
    return _url("funding", {
        "symbol": symbol,
        "count": count,
        "start": start,
        "reverse": "true" if reverse else "false",
        "startTime": iso_utc(start_time),
        "endTime": iso_utc(end_time),
    })


def build_instrument_url(
    symbol: str,
    *,
    start_time: Any = None,
    end_time: Any = None,
    count: int = MAX_PAGE_SIZE,
    start: int = 0,
    reverse: bool = False,
) -> str:
    return _url("instrument", {
        "symbol": symbol,
        "count": count,
        "start": start,
        "reverse": "true" if reverse else "false",
        "startTime": iso_utc(start_time),
        "endTime": iso_utc(end_time),
    })


def fetch_json(url: str, *, timeout: int = 30, opener=urlopen) -> Any:
    """Fetch one JSON response without credentials."""
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "btc-replay-research/1.0"})
    try:
        with opener(request, timeout=timeout) as response:
            payload = response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise MarketDownloadError(f"public source request failed: {exc}") from exc
    try:
        return json.loads(payload.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise MarketDownloadError(f"public source returned non-JSON data: {exc}") from exc


def fetch_bytes(url: str, *, timeout: int = 60, opener=urlopen) -> bytes:
    """Fetch one public archive object without credentials."""
    request = Request(url, headers={"Accept": "*/*", "User-Agent": "btc-replay-research/1.0"})
    try:
        with opener(request, timeout=timeout) as response:
            return response.read()
    except (HTTPError, URLError, TimeoutError, OSError) as exc:
        raise MarketDownloadError(f"public archive request failed: {exc}") from exc


def _cache_load(path: Path) -> list[dict[str, Any]] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MarketDownloadError(f"cached market response is unreadable: {path}: {exc}") from exc
    if not isinstance(payload, list) or any(not isinstance(row, dict) for row in payload):
        raise MarketDownloadError(f"cached market response is not a list of objects: {path}")
    return payload


def _cache_write(path: Path, rows: list[dict[str, Any]]) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    path.write_bytes(encoded)
    return hashlib.sha256(encoded).hexdigest()


def download_paginated(
    url_builder,
    *,
    cache_path: Path,
    start_time: Any = None,
    end_time: Any = None,
    timeout: int = 30,
    page_limit: int = 10000,
    sleep_seconds: float = 0.0,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Download a stable oldest-first public series, or use its verified cache."""
    cached = _cache_load(cache_path)
    if cached is not None:
        digest = hashlib.sha256(cache_path.read_bytes()).hexdigest()
        return cached, {
            "status": "CACHED",
            "cache_path": str(cache_path),
            "sha256": digest,
            "row_count": len(cached),
            "download_time_utc": None,
            "request_count": 0,
        }

    rows: list[dict[str, Any]] = []
    offset = 0
    request_count = 0
    last_key: tuple[Any, ...] | None = None
    started = utc_now()
    try:
        for _ in range(page_limit):
            url = url_builder(start_time=start_time, end_time=end_time, count=MAX_PAGE_SIZE, start=offset, reverse=False)
            page = fetch_json(url, timeout=timeout)
            request_count += 1
            if not isinstance(page, list) or any(not isinstance(row, dict) for row in page):
                raise MarketDownloadError("public source response page is not a JSON list of objects")
            if not page:
                break
            key = tuple(page[-1].get(field) for field in ("timestamp", "id", "symbol"))
            if last_key is not None and key == last_key:
                raise MarketDownloadError("public source pagination made no progress")
            last_key = key
            rows.extend(page)
            if len(page) < MAX_PAGE_SIZE:
                break
            offset += len(page)
            if sleep_seconds:
                time.sleep(sleep_seconds)
        else:
            raise MarketDownloadError(f"public source exceeded page limit {page_limit}")
    except Exception:
        # A partial series is not safe for research.  Do not cache it.
        raise
    digest = _cache_write(cache_path, rows)
    return rows, {
        "status": "DOWNLOADED",
        "cache_path": str(cache_path),
        "sha256": digest,
        "row_count": len(rows),
        "download_time_utc": started,
        "request_count": request_count,
    }


def download_windowed(
    url_builder,
    *,
    cache_dir: Path,
    cache_stem: str,
    start_time: Any,
    end_time: Any,
    window_days: int = 30,
    timeout: int = 60,
    page_limit: int = 1000,
    sleep_seconds: float = 0.0,
    retries: int = 2,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Download a long time series in bounded, resumable UTC windows.

    BitMEX can serve a small bounded interval reliably, while a six-year
    ``startTime``/``endTime`` request can time out before the first page is
    returned.  Each window is cached independently, so a rerun resumes from
    the last verified window instead of silently accepting a partial series.
    Boundary rows are deduplicated by timestamp and symbol after all windows
    have been read.
    """
    start = parse_utc(start_time)
    end = parse_utc(end_time)
    if start is None or end is None or end < start:
        raise MarketDownloadError("windowed download requires an ordered UTC time range")
    if window_days <= 0:
        raise ValueError("window_days must be positive")

    cache_dir.mkdir(parents=True, exist_ok=True)
    all_rows: list[dict[str, Any]] = []
    windows: list[dict[str, Any]] = []
    current = start
    started = utc_now()

    def fetch_window(window_start: datetime, window_end: datetime) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        cache_path = cache_dir / (
            f"{cache_stem}_{window_start.strftime('%Y%m%dT%H%M%S')}_"
            f"{window_end.strftime('%Y%m%dT%H%M%S')}.json"
        )
        last_error: MarketDownloadError | None = None
        for attempt in range(retries + 1):
            try:
                rows, lineage = download_paginated(
                    url_builder,
                    cache_path=cache_path,
                    start_time=window_start,
                    end_time=window_end,
                    timeout=timeout,
                    page_limit=page_limit,
                    sleep_seconds=sleep_seconds,
                )
                return rows, [{
                    "start_time_utc": iso_utc(window_start),
                    "end_time_utc": iso_utc(window_end),
                    **lineage,
                }]
            except MarketDownloadError as exc:
                last_error = exc
                if attempt >= retries:
                    break
                time.sleep(min(2.0 * (attempt + 1), 5.0))

        # A problematic seven-day range can still contain a perfectly valid
        # smaller range.  Split it rather than abandoning the entire source
        # or falling through to multi-gigabyte raw trade archives.
        span_seconds = int((window_end - window_start).total_seconds())
        minimum_seconds = 24 * 60 * 60
        if span_seconds > minimum_seconds:
            midpoint = window_start + timedelta(seconds=span_seconds // 2)
            left_rows, left_lineage = fetch_window(window_start, midpoint)
            right_rows, right_lineage = fetch_window(midpoint, window_end)
            return left_rows + right_rows, left_lineage + right_lineage
        raise last_error or MarketDownloadError("windowed download failed")

    while current < end:
        window_end = min(current + timedelta(days=window_days), end)
        rows, window_lineage = fetch_window(current, window_end)
        all_rows.extend(rows)
        windows.extend(window_lineage)
        current = window_end

    unique: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in all_rows:
        unique[(row.get("timestamp"), row.get("symbol"), row.get("id"))] = row
    rows = sorted(unique.values(), key=lambda row: (parse_utc(row.get("timestamp")) or datetime.max.replace(tzinfo=timezone.utc), str(row.get("id") or "")))
    encoded = json.dumps(rows, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    return rows, {
        "status": "DOWNLOADED",
        "cache_path": str(cache_dir),
        "sha256": digest,
        "row_count": len(rows),
        "download_time_utc": started,
        "request_count": sum(int(item.get("request_count") or 0) for item in windows),
        "window_count": len(windows),
        "window_days": window_days,
        "retries": retries,
        "windows": windows,
    }


def source_descriptor(endpoint: str, *, symbol: str, interval: str | None, start_time: Any, end_time: Any) -> dict[str, Any]:
    return {
        "provider": "BitMEX",
        "endpoint": endpoint,
        "symbol": symbol,
        "interval": interval,
        "start_time_utc": iso_utc(start_time),
        "end_time_utc": iso_utc(end_time),
        "credentials": "none",
        "official_documentation": {
            "trade_bucketed": "https://docs.bitmex.com/api-explorer/get-trade-bucketed",
            "funding": "https://docs.bitmex.com/api-explorer/get-funding",
            "instrument": "https://docs.bitmex.com/api-explorer/get-instruments.html",
        },
    }


__all__ = [
    "MAX_PAGE_SIZE",
    "MarketDownloadError",
    "PUBLIC_API_ROOT",
    "build_funding_url",
    "build_instrument_url",
    "build_trade_bucketed_url",
    "download_paginated",
    "download_windowed",
    "fetch_bytes",
    "fetch_json",
    "iso_utc",
    "parse_utc",
    "source_descriptor",
    "utc_now",
]
