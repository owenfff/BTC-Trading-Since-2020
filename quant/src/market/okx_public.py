"""Credential-free OKX public market history for causal research replay.

This module deliberately contains no account authentication, API-key handling,
order placement, or Demo-account logic.  It downloads only public market
responses and keeps OKX instrument semantics separate from the BitMEX teacher
records.  The normalized candle timestamp is the *close* of the source bar;
the source opening timestamp is retained separately.  This makes a row safe
to use as an already-closed observation at ``timestamp``.
"""

from __future__ import annotations

import csv
import hashlib
import json
import math
import time
from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from http.client import HTTPException
from pathlib import Path
from typing import Any, Callable, Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

from features.market_features import build_market_features

from .download import parse_utc


OKX_PUBLIC_API_ROOT = "https://www.okx.com/api/v5"
OKX_PUBLIC_DOCUMENTATION = "https://app.okx.com/docs-v5/en/"
OKX_PUBLIC_HOSTS = {"www.okx.com", "app.okx.com", "openapi.okx.com"}
OKX_CANDLE_LIMIT = 300
OKX_MARK_INDEX_LIMIT = 100
OKX_FUNDING_LIMIT = 400

_CANDLE_ENDPOINT = "/market/history-candles"
_MARK_ENDPOINT = "/market/history-mark-price-candles"
_INDEX_ENDPOINT = "/market/history-index-candles"
_FUNDING_ENDPOINT = "/public/funding-rate-history"


class OkxPublicError(RuntimeError):
    """A public OKX response was unavailable, invalid, or unsafe to use."""


def _ensure_public_base_url(base_url: str) -> str:
    parsed = urlsplit(base_url)
    if parsed.scheme != "https" or parsed.netloc.lower() not in OKX_PUBLIC_HOSTS:
        raise ValueError(
            "OKX public market downloader only accepts HTTPS OKX public hosts; "
            f"received {base_url!r}"
        )
    return base_url.rstrip("/")


def _clean_decimal(value: Any) -> str | None:
    if value in (None, ""):
        return None
    try:
        number = Decimal(str(value).strip())
    except (InvalidOperation, ValueError):
        return None
    if not number.is_finite():
        return None
    return str(value).strip()


def _positive_decimal(value: Any) -> bool:
    clean = _clean_decimal(value)
    if clean is None:
        return False
    try:
        return Decimal(clean) > 0
    except InvalidOperation:
        return False


def _epoch_ms(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float, Decimal)):
        try:
            number = int(value)
        except (TypeError, ValueError, OverflowError):
            return None
        return number if number >= 0 else None
    text = str(value).strip()
    if text.isdigit():
        number = int(text)
        return number if number >= 0 else None
    parsed = parse_utc(text)
    return int(parsed.timestamp() * 1000) if parsed else None


def _iso_ms(timestamp_ms: int | None) -> str:
    if timestamp_ms is None:
        return ""
    return datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _bar_seconds(bar: str) -> int:
    normalized = bar.strip().lower()
    mapping = {
        "1m": 60,
        "3m": 180,
        "5m": 300,
        "15m": 900,
        "30m": 1800,
        "1h": 3600,
        "2h": 7200,
        "4h": 14400,
        "6h": 21600,
        "12h": 43200,
        "1d": 86400,
        "1w": 604800,
        "1mth": 2592000,
        "1mon": 2592000,
    }
    if normalized not in mapping:
        raise ValueError(f"unsupported OKX bar for this importer: {bar}")
    return mapping[normalized]


def _canonical_digest(payload: Any) -> str:
    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _safe_filename(text: str) -> str:
    return "".join(char if char.isalnum() or char in "._-" else "_" for char in text)


def _endpoint_limit(endpoint: str, requested: int) -> int:
    maximum = OKX_FUNDING_LIMIT if endpoint == _FUNDING_ENDPOINT else (OKX_MARK_INDEX_LIMIT if endpoint in {_MARK_ENDPOINT, _INDEX_ENDPOINT} else OKX_CANDLE_LIMIT)
    return min(int(requested), maximum)


@dataclass
class OkxPublicClient:
    """Small standard-library client for OKX public endpoints only."""

    base_url: str = OKX_PUBLIC_API_ROOT
    timeout: float = 30.0
    opener: Callable[..., Any] = urlopen
    user_agent: str = "btc-trading-since-2020-public-research/1.0"

    def __post_init__(self) -> None:
        self.base_url = _ensure_public_base_url(self.base_url)

    def build_url(self, endpoint: str, params: dict[str, Any] | None = None) -> str:
        path = endpoint if endpoint.startswith("/") else f"/{endpoint}"
        query = {key: value for key, value in (params or {}).items() if value not in (None, "")}
        encoded = urlencode(sorted(query.items()), doseq=True)
        return f"{self.base_url}{path}" + (f"?{encoded}" if encoded else "")

    def get_json(self, endpoint: str, params: dict[str, Any] | None = None) -> tuple[dict[str, Any], str]:
        url = self.build_url(endpoint, params)
        request = Request(url, headers={"Accept": "application/json", "User-Agent": self.user_agent})
        try:
            with self.opener(request, timeout=self.timeout) as response:
                raw = response.read()
        except (HTTPError, URLError, TimeoutError, OSError, HTTPException) as exc:
            raise OkxPublicError(f"OKX public request failed: {exc}") from exc
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise OkxPublicError(f"OKX public response was not valid JSON: {exc}") from exc
        if not isinstance(payload, dict):
            raise OkxPublicError("OKX public response was not an object")
        if str(payload.get("code")) != "0":
            raise OkxPublicError(f"OKX public API error {payload.get('code')}: {payload.get('msg')}")
        data = payload.get("data")
        if not isinstance(data, list):
            raise OkxPublicError("OKX public response data was not a list")
        return payload, url


def _cached_get_json(
    client: OkxPublicClient,
    endpoint: str,
    params: dict[str, Any],
    cache_dir: Path | None,
) -> tuple[dict[str, Any], str, bool]:
    url = client.build_url(endpoint, params)
    cache_path: Path | None = None
    if cache_dir is not None:
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_path = cache_dir / f"{hashlib.sha256(url.encode('utf-8')).hexdigest()}.json"
        if cache_path.exists():
            try:
                payload = json.loads(cache_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise OkxPublicError(f"OKX cache is unreadable: {cache_path}: {exc}") from exc
            if isinstance(payload, dict) and str(payload.get("code")) == "0" and isinstance(payload.get("data"), list):
                return payload, url, True
            raise OkxPublicError(f"OKX cache has an invalid response: {cache_path}")
    payload, url = client.get_json(endpoint, params)
    if cache_path is not None:
        cache_path.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True), encoding="utf-8")
    return payload, url, False


def _within_bounds(timestamp_ms: int, start_ms: int | None, end_ms: int | None) -> bool:
    return (start_ms is None or timestamp_ms >= start_ms) and (end_ms is None or timestamp_ms <= end_ms)


def _normalize_candle(
    source_row: Any,
    *,
    inst_id: str,
    bar: str,
    source_kind: str,
    source_row_number: int,
) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(source_row, list) or len(source_row) < 6:
        return None, "invalid_row_shape"
    timestamp_ms = _epoch_ms(source_row[0])
    if timestamp_ms is None:
        return None, "timestamp_parse_failed"
    values = [_clean_decimal(source_row[index]) if index < len(source_row) else None for index in range(1, 5)]
    if any(value is None for value in values):
        return None, "missing_ohlc"
    if not all(_positive_decimal(value) for value in values):
        return None, "non_positive_ohlc"
    confirm = str(source_row[8] if len(source_row) >= 9 else source_row[5]).strip()
    if source_kind == "candles" and confirm != "1":
        return None, "unclosed_candle"
    interval_seconds = _bar_seconds(bar)
    bar_open = datetime.fromtimestamp(timestamp_ms / 1000, tz=timezone.utc)
    bar_end_ms = timestamp_ms + interval_seconds * 1000
    output: dict[str, Any] = {
        "venue": "OKX",
        "inst_id": inst_id,
        "bar": bar,
        "source_kind": source_kind,
        "source_row_number": source_row_number,
        "source_timestamp_ms": str(timestamp_ms),
        "bar_open_time_utc": _iso_ms(timestamp_ms),
        "timestamp": _iso_ms(bar_end_ms),
        "bar_end_time_utc": _iso_ms(bar_end_ms),
        "open": values[0],
        "high": values[1],
        "low": values[2],
        "close": values[3],
        "volume": _clean_decimal(source_row[5]) if len(source_row) >= 6 else None,
        "volume_currency": _clean_decimal(source_row[6]) if len(source_row) >= 7 else None,
        "volume_quote": _clean_decimal(source_row[7]) if len(source_row) >= 8 else None,
        "confirm": confirm,
        "closed": confirm == "1",
        "source": f"okx_public_{source_kind}",
    }
    return output, None


def _normalize_funding(source_row: Any, *, inst_id: str, source_row_number: int) -> tuple[dict[str, Any] | None, str | None]:
    if not isinstance(source_row, dict):
        return None, "invalid_row_shape"
    timestamp_ms = _epoch_ms(source_row.get("fundingTime"))
    if timestamp_ms is None:
        return None, "timestamp_parse_failed"
    realized = _clean_decimal(source_row.get("realizedRate"))
    predicted = _clean_decimal(source_row.get("fundingRate"))
    rate = realized if realized is not None else predicted
    if rate is None:
        return None, "funding_rate_missing"
    return {
        "venue": "OKX",
        "inst_id": inst_id,
        "timestamp": _iso_ms(timestamp_ms),
        "funding_time_utc": _iso_ms(timestamp_ms),
        "funding_rate": rate,
        "realized_rate": realized,
        "predicted_rate": predicted,
        "rate_kind": "REALIZED" if realized is not None else "PREDICTED_ONLY",
        "method": source_row.get("method"),
        "formula_type": source_row.get("formulaType"),
        "source_row_number": source_row_number,
        "source": "okx_public_funding_rate_history",
    }, None


def _dedupe_sort(rows: Iterable[dict[str, Any]], *, key: str = "timestamp") -> list[dict[str, Any]]:
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        unique[(str(row.get("inst_id") or ""), str(row.get(key) or ""))] = row
    return sorted(unique.values(), key=lambda row: (parse_utc(row.get(key)) or datetime.max.replace(tzinfo=timezone.utc), str(row.get("inst_id") or "")))


def _fetch_pages(
    client: OkxPublicClient,
    *,
    endpoint: str,
    inst_id: str,
    start: Any = None,
    end: Any = None,
    limit: int,
    max_pages: int,
    cache_dir: Path | None,
    sleep_seconds: float,
    row_time_field: str,
    extra_params: dict[str, Any] | None = None,
) -> tuple[list[Any], dict[str, Any]]:
    start_ms = _epoch_ms(start)
    end_ms = _epoch_ms(end)
    if start is not None and start_ms is None:
        raise ValueError(f"invalid start time: {start!r}")
    if end is not None and end_ms is None:
        raise ValueError(f"invalid end time: {end!r}")
    if start_ms is not None and end_ms is not None and end_ms < start_ms:
        raise ValueError("end time must not be earlier than start time")
    cursor = end_ms
    previous_oldest: int | None = None
    raw_rows: list[Any] = []
    request_count = 0
    cache_hit_count = 0
    page_digests: list[str] = []
    completion = "RANGE_REACHED"
    failure: dict[str, Any] | None = None
    for page_number in range(1, max_pages + 1):
        params: dict[str, Any] = {"instId": inst_id, "limit": _endpoint_limit(endpoint, limit)}
        if extra_params:
            params.update(extra_params)
        if cursor is not None:
            params["after"] = str(cursor)
        try:
            payload, url, from_cache = _cached_get_json(client, endpoint, params, cache_dir)
        except OkxPublicError as exc:
            if raw_rows:
                completion = "PARTIAL_REQUEST_FAILURE"
                failure = {"page_number": page_number, "error_type": type(exc).__name__, "error": str(exc)}
                break
            raise
        request_count += 0 if from_cache else 1
        cache_hit_count += int(from_cache)
        data = payload.get("data") or []
        if not data:
            completion = "EMPTY_PAGE"
            break
        raw_rows.extend(data)
        page_digests.append(_canonical_digest(data))
        timestamps = [_epoch_ms(row.get(row_time_field)) for row in data if isinstance(row, dict) and _epoch_ms(row.get(row_time_field)) is not None] if row_time_field != "0" else [_epoch_ms(row[0]) for row in data if isinstance(row, list) and row and _epoch_ms(row[0]) is not None]
        if not timestamps:
            raise OkxPublicError(f"OKX page {page_number} contained no parseable timestamps: {url}")
        oldest = min(timestamps)
        if start_ms is not None and oldest <= start_ms:
            completion = "START_REACHED"
            break
        if len(data) < int(params["limit"]):
            completion = "SHORT_PAGE"
            break
        if previous_oldest is not None and oldest >= previous_oldest:
            raise OkxPublicError("OKX pagination made no progress toward older timestamps")
        previous_oldest = oldest
        cursor = oldest
        if sleep_seconds:
            time.sleep(sleep_seconds)
    else:
        raise OkxPublicError(f"OKX pagination exceeded max_pages={max_pages}")
    lineage = {
        "endpoint": endpoint,
        "inst_id": inst_id,
        "start_time_utc": _iso_ms(start_ms),
        "end_time_utc": _iso_ms(end_ms),
        "limit": _endpoint_limit(endpoint, limit),
        "max_pages": max_pages,
        "page_count": len(page_digests),
        "raw_row_count": len(raw_rows),
        "request_count": request_count,
        "cache_hit_count": cache_hit_count,
        "page_sha256": page_digests,
        "completion": completion,
        "credentials": "none",
        "documentation": OKX_PUBLIC_DOCUMENTATION,
    }
    if failure is not None:
        lineage["failure"] = failure
    return raw_rows, lineage


def fetch_history_candles(
    client: OkxPublicClient,
    *,
    inst_id: str,
    bar: str = "1H",
    start: Any = None,
    end: Any = None,
    limit: int = OKX_CANDLE_LIMIT,
    max_pages: int = 1000,
    cache_dir: Path | None = None,
    sleep_seconds: float = 0.11,
    source_kind: str = "candles",
    endpoint: str | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch a closed candle series from OKX, paginating backward in time."""

    if source_kind not in {"candles", "mark_price", "index"}:
        raise ValueError(f"unsupported candle source_kind: {source_kind}")
    endpoint = endpoint or ({"candles": _CANDLE_ENDPOINT, "mark_price": _MARK_ENDPOINT, "index": _INDEX_ENDPOINT}[source_kind])
    raw_rows, lineage = _fetch_pages(
        client,
        endpoint=endpoint,
        inst_id=inst_id,
        start=start,
        end=end,
        limit=limit,
        max_pages=max_pages,
        cache_dir=cache_dir,
        sleep_seconds=sleep_seconds,
        row_time_field="0",
        extra_params={"bar": bar},
    )
    start_ms = _epoch_ms(start)
    end_ms = _epoch_ms(end)
    normalized: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    for source_row_number, source_row in enumerate(raw_rows, start=1):
        parsed, reason = _normalize_candle(source_row, inst_id=inst_id, bar=bar, source_kind=source_kind, source_row_number=source_row_number)
        if parsed is None:
            rejected[reason or "unknown"] = rejected.get(reason or "unknown", 0) + 1
            continue
        if not _within_bounds(int(parsed["source_timestamp_ms"]), start_ms, end_ms):
            continue
        normalized.append(parsed)
    rows = _dedupe_sort(normalized, key="timestamp")
    lineage.update({
        "status": "PASS" if rows and lineage.get("completion") != "PARTIAL_REQUEST_FAILURE" else ("PARTIAL" if rows else "EMPTY"),
        "source_kind": source_kind,
        "bar": bar,
        "normalized_row_count": len(rows),
        "rejected_counts": rejected,
        "unclosed_source_rows": rejected.get("unclosed_candle", 0),
        "sha256": _canonical_digest(rows),
    })
    return rows, lineage


def fetch_funding_history(
    client: OkxPublicClient,
    *,
    inst_id: str,
    start: Any = None,
    end: Any = None,
    limit: int = OKX_FUNDING_LIMIT,
    max_pages: int = 100,
    cache_dir: Path | None = None,
    sleep_seconds: float = 0.21,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Fetch available realized funding history; OKX documents a three-month limit."""

    raw_rows, lineage = _fetch_pages(
        client,
        endpoint=_FUNDING_ENDPOINT,
        inst_id=inst_id,
        start=start,
        end=end,
        limit=limit,
        max_pages=max_pages,
        cache_dir=cache_dir,
        sleep_seconds=sleep_seconds,
        row_time_field="fundingTime",
    )
    start_ms = _epoch_ms(start)
    end_ms = _epoch_ms(end)
    normalized: list[dict[str, Any]] = []
    rejected: dict[str, int] = {}
    for source_row_number, source_row in enumerate(raw_rows, start=1):
        parsed, reason = _normalize_funding(source_row, inst_id=inst_id, source_row_number=source_row_number)
        if parsed is None:
            rejected[reason or "unknown"] = rejected.get(reason or "unknown", 0) + 1
            continue
        if _within_bounds(_epoch_ms(parsed["timestamp"]) or 0, start_ms, end_ms):
            normalized.append(parsed)
    rows = _dedupe_sort(normalized)
    lineage.update({
        "status": "PASS" if rows and lineage.get("completion") != "PARTIAL_REQUEST_FAILURE" else ("PARTIAL" if rows else "EMPTY"),
        "retention_note": "OKX documents this public endpoint as available for up to three months; older funding observations remain missing.",
        "normalized_row_count": len(rows),
        "rejected_counts": rejected,
        "sha256": _canonical_digest(rows),
    })
    return rows, lineage


def infer_index_id(inst_id: str) -> str:
    """Derive the common OKX index ID from a linear/inverse swap ID."""

    upper = inst_id.strip().upper()
    for suffix in ("-SWAP", "-FUTURES"):
        if upper.endswith(suffix):
            return upper[: -len(suffix)]
    return upper


def _asof_row(timestamp: datetime, times: list[datetime], rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    index = bisect_right(times, timestamp) - 1
    return rows[index] if index >= 0 else None


def attach_okx_context(
    candles: Iterable[dict[str, Any]],
    *,
    mark_rows: Iterable[dict[str, Any]] = (),
    index_rows: Iterable[dict[str, Any]] = (),
    funding_rows: Iterable[dict[str, Any]] = (),
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Attach previous-or-equal OKX mark/index/funding observations only."""

    mark = _dedupe_sort(mark_rows)
    index = _dedupe_sort(index_rows)
    funding = _dedupe_sort(funding_rows)
    mark_times = [parse_utc(row.get("timestamp")) for row in mark]
    index_times = [parse_utc(row.get("timestamp")) for row in index]
    funding_times = [parse_utc(row.get("timestamp")) for row in funding]
    mark_times = [value for value in mark_times if value is not None]
    index_times = [value for value in index_times if value is not None]
    funding_times = [value for value in funding_times if value is not None]
    output: list[dict[str, Any]] = []
    status_counts: dict[str, int] = {}
    for candle in _dedupe_sort(candles):
        timestamp = parse_utc(candle.get("timestamp"))
        if timestamp is None:
            continue
        mark_row = _asof_row(timestamp, mark_times, mark) if mark_times else None
        index_row = _asof_row(timestamp, index_times, index) if index_times else None
        funding_row = _asof_row(timestamp, funding_times, funding) if funding_times else None
        result = dict(candle)
        result.update({
            "mark_price": mark_row.get("close") if mark_row else None,
            "mark_source_timestamp_utc": mark_row.get("timestamp") if mark_row else None,
            "index_price": index_row.get("close") if index_row else None,
            "index_source_timestamp_utc": index_row.get("timestamp") if index_row else None,
            "funding_rate": funding_row.get("funding_rate") if funding_row else None,
            "funding_source_timestamp_utc": funding_row.get("timestamp") if funding_row else None,
            "funding_source_time": parse_utc(funding_row.get("timestamp")) if funding_row else None,
            "feature_mark_missing": mark_row is None or mark_row.get("close") in (None, ""),
            "feature_index_missing": index_row is None or index_row.get("close") in (None, ""),
            "feature_funding_missing": funding_row is None or funding_row.get("funding_rate") in (None, ""),
        })
        if not result["feature_mark_missing"] and not result["feature_index_missing"] and not result["feature_funding_missing"]:
            status = "COMPLETE"
        elif result["feature_mark_missing"] or result["feature_index_missing"]:
            status = "MARK_INDEX_MISSING"
        else:
            status = "FUNDING_MISSING"
        result["context_status"] = status
        status_counts[status] = status_counts.get(status, 0) + 1
        output.append(result)
    return output, {
        "row_count": len(output),
        "status_counts": status_counts,
        "join_policy": "ASOF_PREVIOUS_OR_EQUAL_CLOSED_BAR; FUTURE_CONTEXT_FORBIDDEN",
        "mark_rows": len(mark),
        "index_rows": len(index),
        "funding_rows": len(funding),
    }


def audit_okx_grid(rows: Iterable[dict[str, Any]], *, interval_seconds: int) -> dict[str, Any]:
    """Return deterministic coverage, duplicate, ordering, and gap statistics."""

    source = list(rows)
    parsed = [parse_utc(row.get("timestamp")) for row in source]
    valid = [value for value in parsed if value is not None]
    counts: dict[datetime, int] = {}
    for value in valid:
        counts[value] = counts.get(value, 0) + 1
    unique = sorted(counts)
    gaps = []
    for left, right in zip(unique, unique[1:]):
        seconds = int((right - left).total_seconds())
        if seconds > interval_seconds and seconds % interval_seconds == 0:
            gaps.append(seconds // interval_seconds - 1)
        elif seconds > interval_seconds:
            gaps.append(None)
    expected = int((unique[-1] - unique[0]).total_seconds() // interval_seconds) + 1 if unique else 0
    missing = sum(value for value in gaps if value is not None)
    return {
        "status": "PASS" if valid and not gaps and not any(value > 1 for value in counts.values()) else ("WARNING" if valid else "BLOCKED"),
        "row_count": len(source),
        "valid_timestamp_count": len(valid),
        "unique_timestamp_count": len(unique),
        "duplicate_timestamp_count": sum(value - 1 for value in counts.values() if value > 1),
        "timestamp_parse_failure_count": len(parsed) - len(valid),
        "out_of_order_transition_count": sum(1 for left, right in zip(valid, valid[1:]) if right < left),
        "first_timestamp_utc": _iso_ms(int(unique[0].timestamp() * 1000)) if unique else "",
        "last_timestamp_utc": _iso_ms(int(unique[-1].timestamp() * 1000)) if unique else "",
        "expected_grid_count": expected,
        "missing_grid_count": missing,
        "gap_count": len(gaps),
        "coverage_ratio": len(unique) / expected if expected else 0.0,
        "interval_seconds": interval_seconds,
    }


def build_causal_indicator_rows(
    rows: Iterable[dict[str, Any]],
    *,
    interval_seconds: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Use the repository's shared indicator function on closed bars only."""

    ordered = _dedupe_sort(rows)
    output: list[dict[str, Any]] = []
    violations = 0
    for index, row in enumerate(ordered):
        window = ordered[max(0, index - 99) : index + 1]
        decision_time = parse_utc(row.get("timestamp"))
        if decision_time is None:
            continue
        decision_time = decision_time + timedelta(milliseconds=1)
        numeric_window: list[dict[str, Any]] = []
        for item in window:
            numeric_item = dict(item)
            numeric_item["timestamp"] = parse_utc(item.get("timestamp"))
            for field in ("open", "high", "low", "close", "volume", "mark_price", "index_price", "funding_rate"):
                value = numeric_item.get(field)
                try:
                    numeric_item[field] = float(value) if value not in (None, "") else None
                except (TypeError, ValueError):
                    numeric_item[field] = None
            numeric_window.append(numeric_item)
        features = build_market_features(
            numeric_window,
            decision_time,
            timestamps=[parse_utc(item.get("timestamp")) for item in numeric_window],
            bar_seconds=interval_seconds,
        )
        result = dict(row)
        result.update(features)
        result["decision_time_utc"] = decision_time.isoformat(timespec="milliseconds").replace("+00:00", "Z")
        result["feature_context_status"] = row.get("context_status", "UNAVAILABLE")
        latest = parse_utc(features.get("feature_latest_bar_time"))
        if latest is not None and latest >= decision_time:
            violations += 1
        output.append(result)
    return output, {
        "row_count": len(output),
        "causal_timestamp_violation_count": violations,
        "feature_implementation": "features.market_features.build_market_features",
        "feature_policy": "closed_OKX_bars_only; previous_or_equal_context; no_labels; no_future_observations",
    }


def write_rows_csv(path: Path, rows: Iterable[dict[str, Any]]) -> str:
    """Write generated research rows to an ignored output and return its SHA256."""

    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in materialized:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in materialized:
            writer.writerow({key: "" if row.get(key) is None else _csv_value(row.get(key)) for key in fieldnames})
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _csv_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (dict, list, tuple)):
        return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    if isinstance(value, float) and not math.isfinite(value):
        return ""
    return value


__all__ = [
    "OKX_CANDLE_LIMIT",
    "OKX_MARK_INDEX_LIMIT",
    "OKX_FUNDING_LIMIT",
    "OKX_PUBLIC_API_ROOT",
    "OKX_PUBLIC_DOCUMENTATION",
    "OkxPublicClient",
    "OkxPublicError",
    "attach_okx_context",
    "audit_okx_grid",
    "build_causal_indicator_rows",
    "fetch_funding_history",
    "fetch_history_candles",
    "infer_index_id",
    "write_rows_csv",
]
