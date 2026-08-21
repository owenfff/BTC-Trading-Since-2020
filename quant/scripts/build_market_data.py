#!/usr/bin/env python3
"""Download and audit public BitMEX BTC market context.

This script is intentionally account-independent.  It uses only public
BitMEX endpoints, never reads API credentials, never writes the protected
account exports, and never fills a missing market bar with an invented price.
If the desktop runtime cannot reach the public source, it still writes a
machine-readable BLOCKED report so the environmental blocker is explicit.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bitmex_replay.io_utils import hash_files, iter_csv_dicts, parse_datetime  # noqa: E402
from market.archive import download_archive_trade_bars  # noqa: E402
from market.context import attach_market_context  # noqa: E402
from market.download import (  # noqa: E402
    MarketDownloadError,
    build_funding_url,
    build_instrument_url,
    build_trade_bucketed_url,
    download_paginated,
    download_windowed,
    source_descriptor,
    utc_now,
)
from market.gaps import audit_time_grid, build_gap_rows  # noqa: E402
from market.normalize import normalize_funding, normalize_instrument, normalize_trade_bars, resample_trade_bars  # noqa: E402
from bitmex_replay.reconciliation import write_parquet  # noqa: E402


PROTECTED_FILES = [
    "api-v1-execution-tradeHistory.csv",
    "api-v1-order.csv",
    "api-v1-user-walletHistory.csv",
    "api-v1-position.snapshot.csv",
    "api-v1-user-wallet.snapshot-all.csv",
    "api-v1-user-margin.snapshot-all.csv",
    "api-v1-instrument.all.csv",
    "api-v1-wallet-assets.csv",
    "derived-equity-curve.csv",
    "manifest.json",
]


def git_value(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(item) for item in value]
    return value


def _fieldnames(rows: list[dict[str, Any]], default: list[str]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                names.append(key)
    return names or default


def _write_csv(path: Path, rows: list[dict[str, Any]], fieldnames: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({field: "" if row.get(field) is None else row.get(field, "") for field in fieldnames})


def _execution_bounds(root: Path, symbol: str) -> tuple[datetime | None, datetime | None, int]:
    first: datetime | None = None
    last: datetime | None = None
    count = 0
    path = root / "api-v1-execution-tradeHistory.csv"
    for _, row in iter_csv_dicts(path):
        if str(row.get("symbol", "")).strip().upper() != symbol.upper() or str(row.get("execType", "")).strip() != "Trade":
            continue
        event_time = parse_datetime(row.get("transactTime")) or parse_datetime(row.get("timestamp"))
        if event_time is None:
            continue
        count += 1
        first = event_time if first is None or event_time < first else first
        last = event_time if last is None or event_time > last else last
    return first, last, count


def _fetch(
    name: str,
    builder: Callable[..., str],
    cache_path: Path,
    *,
    symbol: str,
    interval: str | None,
    start_time: datetime | None,
    end_time: datetime | None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    descriptor = source_descriptor(
        builder(symbol, **({"bin_size": interval} if name == "trade_bucketed" else {}), start_time=start_time, end_time=end_time),
        symbol=symbol,
        interval=interval,
        start_time=start_time,
        end_time=end_time,
    )
    try:
        rows, lineage = download_paginated(
            lambda **kwargs: builder(symbol, **({"bin_size": interval} if name == "trade_bucketed" else {}), **kwargs),
            cache_path=cache_path,
            start_time=start_time,
            end_time=end_time,
        )
        descriptor.update(lineage)
        descriptor["status"] = "PASS" if rows else "EMPTY"
        return rows, descriptor
    except MarketDownloadError as exc:
        descriptor.update({"status": "FAILED", "error_type": type(exc).__name__, "error": str(exc)})
        return [], descriptor


def _fetch_windowed(
    name: str,
    builder: Callable[..., str],
    cache_dir: Path,
    cache_stem: str,
    *,
    symbol: str,
    interval: str | None,
    start_time: datetime | None,
    end_time: datetime | None,
    window_days: int,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if start_time is None or end_time is None:
        return [], {"status": "FAILED_NO_TIME_BOUNDS", "row_count": 0}
    endpoint = builder(symbol, **({"bin_size": interval} if name == "trade_bucketed" else {}), start_time=start_time, end_time=end_time)
    descriptor = source_descriptor(endpoint, symbol=symbol, interval=interval, start_time=start_time, end_time=end_time)
    try:
        rows, lineage = download_windowed(
            lambda **kwargs: builder(symbol, **({"bin_size": interval} if name == "trade_bucketed" else {}), **kwargs),
            cache_dir=cache_dir,
            cache_stem=cache_stem,
            start_time=start_time,
            end_time=end_time,
            window_days=window_days,
            timeout=60,
            page_limit=1000,
        )
        descriptor.update(lineage)
        descriptor["status"] = "PASS" if rows else "EMPTY"
        return rows, descriptor
    except MarketDownloadError as exc:
        descriptor.update({"status": "FAILED", "error_type": type(exc).__name__, "error": str(exc)})
        return [], descriptor


def _output_large(rows: list[dict[str, Any]], parquet_path: Path) -> dict[str, Any]:
    try:
        write_parquet(rows, parquet_path)
        return {"format": "parquet", "path": str(parquet_path.relative_to(ROOT)), "row_count": len(rows)}
    except (ImportError, RuntimeError):
        fallback = parquet_path.with_suffix(".csv")
        _write_csv(fallback, rows, _fieldnames(rows, ["timestamp"]))
        return {
            "format": "csv_fallback_no_parquet_engine",
            "path": str(fallback.relative_to(ROOT)),
            "requested_path": str(parquet_path.relative_to(ROOT)),
            "row_count": len(rows),
        }


def _report_markdown(summary: dict[str, Any], path: Path) -> None:
    lines = [
        "# Public Market Data Audit",
        "",
        f"- status: **{summary['market_data_status']}**",
        f"- analysis commit: `{summary['analysis_commit']}`",
        f"- source: `{summary['source']['provider']}` public API; credentials: `{summary['source']['credentials']}`",
        f"- symbol: `{summary['symbol']}`",
        f"- requested interval: `{summary['requested_interval']}`; selected interval: `{summary['selected_interval'] or 'none'}`",
        f"- account execution bounds: `{summary['requested_start_time_utc']}` to `{summary['requested_end_time_utc']}` ({summary['account_trade_count']} XBTUSD Trade rows)",
        "",
        "## Source lineage",
        "",
        "The canonical price series is requested from BitMEX `trade/bucketed`, with the official public S3 trade archive as an explicit fallback. Funding is requested from `funding`; the current `/instrument` endpoint is not treated as a historical mark/index series. Raw responses are kept only under ignored `quant/data/market/raw/` and their SHA-256 is recorded in the JSON report.",
        "",
        "| source | status | rows | sha256 |",
        "| --- | --- | ---: | --- |",
    ]
    for name, item in summary["lineage"].items():
        lines.append(f"| {name} | {item.get('status', '')} | {item.get('row_count', 0)} | `{item.get('sha256', '')}` |")
    lines.extend([
        "",
        "## Coverage and gaps",
        "",
        f"- bar audit: `{json.dumps(summary['bar_audit'], ensure_ascii=False)}`",
        f"- derived 1h bar audit: `{json.dumps(summary['bar_1h_audit'], ensure_ascii=False)}`",
        f"- gap rows: `{summary['gap_row_count']}`; details: `market_data_gaps.csv`",
        f"- context status counts: `{json.dumps(summary['context_audit'].get('status_counts', {}), ensure_ascii=False)}`",
        "",
        "No gap is filled with a forward price. The context join is previous-or-equal UTC only; an observation after a bar cannot be used for that bar.",
        "",
        "## Environment/blocking boundary",
        "",
        f"- public source status: `{summary['source_status']}`",
        f"- output: `{json.dumps(summary.get('large_outputs', {}), ensure_ascii=False)}`",
        "- A future local network denial is an environment blocker, not evidence that BitMEX has no historical data. Rerun this script in a network-enabled environment or use the verified cached responses under the ignored market-data paths.",
        "- This package does not use account API keys, private endpoints, live balances, or order placement.",
        "",
        "## Next action",
        "",
        f"{summary['next_action']}",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def run(root: Path = ROOT) -> dict[str, Any]:
    root = Path(root)
    reports = root / "quant" / "reports"
    outputs = root / "quant" / "outputs"
    market_data_root = root / "quant" / "data" / "market"
    raw_dir = market_data_root / "raw"
    api_raw_dir = raw_dir / "bitmex_api"
    reports.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    before = hash_files(root, PROTECTED_FILES)
    symbol = "XBTUSD"
    start_time, end_time, account_trade_count = _execution_bounds(root, symbol)
    lineage: dict[str, Any] = {}
    selected_interval: str | None = None
    bars: list[dict[str, Any]] = []
    bars_1h: list[dict[str, Any]] = []
    bars_1h_audit: dict[str, Any] = {"normalized_row_count": 0, "status": "NOT_AVAILABLE"}
    requested_interval = "5m"
    for interval in ("5m",):
        rows, item = _fetch_windowed(
            "trade_bucketed",
            build_trade_bucketed_url,
            api_raw_dir,
            f"{symbol.lower()}_trade_bucketed_{interval}",
            symbol=symbol,
            interval=interval,
            start_time=start_time,
            end_time=end_time,
            window_days=7,
        )
        lineage[f"trade_bucketed_{interval}"] = item
        if rows:
            bars, bar_normalization = normalize_trade_bars(rows, symbol=symbol, interval=interval)
        if bars:
            selected_interval = interval
            bars_1h, bars_1h_audit = resample_trade_bars(bars, source_interval_minutes=5, target_interval_minutes=60)
            break
    archive_lineage: dict[str, Any] = {
        "status": "AVAILABLE_EXPLICIT_FALLBACK_NOT_AUTO_SELECTED",
        "row_count": 0,
        "endpoint": "https://s3-eu-west-1.amazonaws.com/public.bitmex.com/data/trade/YYYYMMDD.csv.gz",
        "note": "The official archive contains large daily raw-trade objects. It remains available through market.archive, but is not blindly downloaded after a transient REST failure; the REST window splitter must first exhaust bounded retries."
    }
    lineage["public_archive_trade"] = archive_lineage
    instrument_rows: list[dict[str, Any]] = []
    funding_rows: list[dict[str, Any]] = []
    instrument_normalization: dict[str, Any] = {"normalized_row_count": 0}
    funding_normalization: dict[str, Any] = {"normalized_row_count": 0}
    if bars:
        raw_funding, funding_lineage = _fetch_windowed(
            "funding",
            build_funding_url,
            api_raw_dir,
            f"{symbol.lower()}_funding",
            symbol=symbol,
            interval=None,
            start_time=start_time,
            end_time=end_time,
            window_days=90,
        )
        # /instrument returns the current instrument snapshot.  It is not a
        # historical time series: an old startTime/endTime query returns no
        # rows, and using today's mark/index for old bars would be look-ahead.
        raw_instrument = []
        instrument_lineage = {
            "provider": "BitMEX",
            "endpoint": build_instrument_url(symbol, start_time=start_time, end_time=end_time),
            "symbol": symbol,
            "interval": None,
            "credentials": "none",
            "status": "UNAVAILABLE_HISTORICAL_SNAPSHOT_SERIES",
            "row_count": 0,
            "note": "The public instrument endpoint exposes the current snapshot; no historical mark/index series was accepted for as-of joins.",
        }
        lineage["funding"] = funding_lineage
        lineage["instrument"] = instrument_lineage
        funding_rows, funding_normalization = normalize_funding(raw_funding, symbol=symbol)
        instrument_rows, instrument_normalization = normalize_instrument(raw_instrument, symbol=symbol)
    else:
        bar_normalization = {"normalized_row_count": 0, "rejected_counts": {}}
        lineage["funding"] = {"status": "NOT_ATTEMPTED_NO_BARS", "row_count": 0}
        lineage["instrument"] = {"status": "NOT_ATTEMPTED_NO_BARS", "row_count": 0}
    context_rows, context_audit = attach_market_context(bars, instrument_rows=instrument_rows, funding_rows=funding_rows)
    interval_seconds = {"5m": 300}.get(selected_interval or requested_interval, 300)
    bar_audit = audit_time_grid(context_rows, time_field="timestamp", interval_seconds=interval_seconds)
    bars_1h_audit["grid_audit"] = audit_time_grid(bars_1h, time_field="timestamp", interval_seconds=3600) if bars_1h else {"status": "BLOCKED"}
    gap_rows = build_gap_rows(context_rows, time_field="timestamp", interval_seconds=interval_seconds, series=f"{symbol}:{selected_interval or requested_interval}")
    after = hash_files(root, PROTECTED_FILES)
    changed = [name for name in PROTECTED_FILES if before.get(name) != after.get(name)]
    source_status = "PASS" if bars else "BLOCKED_PUBLIC_DATA_UNAVAILABLE"
    status = "READY_WITH_WARNINGS" if bars and (not funding_rows or not instrument_rows or gap_rows) else ("PASS" if bars else "BLOCKED")
    summary: dict[str, Any] = {
        "report_version": "M3-PUBLIC-MARKET-DATA-1.0",
        "analysis_commit": git_value(["rev-parse", "HEAD"]),
        "analysis_branch": git_value(["branch", "--show-current"]),
        "run_time_utc": utc_now(),
        "market_data_status": status,
        "source_status": source_status,
        "source": {
            "provider": "BitMEX",
            "credentials": "none",
            "base_url": "https://www.bitmex.com/api/v1",
            "archive_base_url": "https://public.bitmex.com/",
            "official_docs": {
                "trade_bucketed": "https://docs.bitmex.com/api-explorer/get-trade-bucketed",
                "funding": "https://docs.bitmex.com/api-explorer/get-funding",
                "instrument": "https://docs.bitmex.com/api-explorer/get-instruments.html",
                "public_archive": "https://public.bitmex.com/",
            },
        },
        "symbol": symbol,
        "requested_interval": requested_interval,
        "selected_interval": selected_interval,
        "requested_start_time_utc": start_time.isoformat().replace("+00:00", "Z") if start_time else "",
        "requested_end_time_utc": end_time.isoformat().replace("+00:00", "Z") if end_time else "",
        "account_trade_count": account_trade_count,
        "lineage": lineage,
        "bar_normalization": bar_normalization,
        "funding_normalization": funding_normalization,
        "instrument_normalization": instrument_normalization,
        "bar_audit": bar_audit,
        "bar_1h_audit": bars_1h_audit,
        "context_audit": context_audit,
        "gap_row_count": len(gap_rows),
        "raw_account_inputs_unchanged": not changed,
        "changed_protected_files": changed,
        "large_outputs": {},
        "warnings": [
            "Trade bucketed timestamps are treated as BitMEX bucket end/write timestamps; no timezone conversion beyond explicit UTC normalization.",
            "Mark/index and funding are retained as as-of context only and are never substituted for a missing canonical trade price.",
        ],
        "next_action": "Market data is READY_WITH_WARNINGS: inspect the explicit mark/index warning and 1h child coverage, then begin leakage-safe M4 features and labels. Do not use current instrument snapshots for historical bars.",
    }
    if context_rows:
        summary["large_outputs"] = {
            "market_bars": _output_large(bars, outputs / "market_bars.parquet"),
            "market_context": _output_large(context_rows, outputs / "market_context.parquet"),
            "market_bars_1h": _output_large(bars_1h, outputs / "market_bars_1h.parquet"),
        }
    _write_csv(reports / "market_data_gaps.csv", gap_rows, ["series", "gap_start_utc", "gap_end_utc", "missing_bar_count", "gap_seconds", "grid_status"])
    (reports / "market_data_lineage.json").write_text(json.dumps(jsonable(summary), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _report_markdown(summary, reports / "market_data_audit.md")
    return summary


if __name__ == "__main__":
    result = run()
    print(f"market_data_status={result['market_data_status']}")
    print(f"source_status={result['source_status']}")
    print(f"selected_interval={result['selected_interval']}")
    print(f"bar_audit={result['bar_audit']}")
    print(f"raw_account_inputs_unchanged={result['raw_account_inputs_unchanged']}")
