"""Public Hyperliquid snapshot/API ingestion and causal behavior normalization.

The module deliberately uses Hyperliquid's public ``info`` endpoint only.  It
never accepts a private key, wallet signer, exchange secret, or order action.
The website snapshot is treated as a pinned, reproducible archive; the public
API helpers are for bounded recent refreshes and validation.
"""

from __future__ import annotations

import hashlib
import json
import time
import urllib.error
import urllib.request
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable, Mapping

from features.market_features import build_market_features, parse_utc


UTC = timezone.utc
PUBLIC_INFO_URL = "https://api.hyperliquid.xyz/info"
DEFAULT_WEBSITE_SOURCE_BASE = "https://paul.catseye.today/data/source/"
DEFAULT_WEBSITE_CANDLE_URL = "https://paul.catseye.today/data/archive/candles_1h.json"
DEFAULT_TARGET_USER = "0xdae4df7207feb3b350e4284c8efe5f7dac37f637"
DEFAULT_SOURCE_REPOSITORY = "pystashell/track_paul_btc_hyperliquid_trade"
DEFAULT_SOURCE_REVISION = "ace13c7a675a20d4932b430508a750d7ad7867e9"
SOURCE_FILES = (
    "historicalOrders.json",
    "userFillsByTime.json",
    "userFunding.json",
    "userNonFundingLedgerUpdates.json",
    "frontendOpenOrders.json",
    "clearinghouseState.json",
    "spotClearinghouseState.json",
)


class HyperliquidSourceError(RuntimeError):
    """Raised when a public source cannot be verified or normalized."""


@dataclass(frozen=True)
class HyperliquidBar:
    """A public 1h bar with separate open and close timestamps."""

    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str


@dataclass(frozen=True)
class HyperliquidBehaviorEvent:
    event_id: str
    time: datetime
    source_venue: str
    source_symbol: str
    canonical_asset: str
    before_position: Decimal
    after_position: Decimal
    action: str
    order_id: str
    fill_id: str
    price: Decimal
    size: Decimal
    fee: Decimal
    fee_currency: str


def sha256_bytes(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _decimal(value: Any, default: Decimal | None = None) -> Decimal | None:
    if value in (None, ""):
        return default
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _iso(value: datetime | None) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z") if value else ""


def _json_bytes(url: str, *, timeout: float = 60.0, user_agent: str = "quant-behavior-audit/1.0") -> bytes:
    last_error: BaseException | None = None
    for attempt in range(3):
        request = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": user_agent})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read()
            if not payload:
                raise HyperliquidSourceError(f"public source returned an empty body: {url}")
            return payload
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, HyperliquidSourceError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise HyperliquidSourceError(f"public source fetch failed after 3 attempts: {url}: {last_error}") from last_error


def fetch_public_info(payload: Mapping[str, Any], *, endpoint: str = PUBLIC_INFO_URL, timeout: float = 30.0) -> Any:
    """Call Hyperliquid's public info endpoint without credentials."""

    if any("key" in str(key).lower() or "secret" in str(key).lower() for key in payload):
        raise HyperliquidSourceError("private credential-shaped fields are forbidden")
    body = json.dumps(dict(payload), separators=(",", ":")).encode("utf-8")
    request = urllib.request.Request(
        endpoint,
        data=body,
        method="POST",
        headers={"Accept": "application/json", "Content-Type": "application/json", "User-Agent": "quant-behavior-audit/1.0"},
    )
    last_error: BaseException | None = None
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, urllib.error.HTTPError, UnicodeDecodeError, json.JSONDecodeError) as error:
            last_error = error
            if attempt < 2:
                time.sleep(0.5 * (attempt + 1))
    raise HyperliquidSourceError(f"public info request failed: {payload.get('type')}: {last_error}") from last_error


def fetch_recent_public_events(
    user: str = DEFAULT_TARGET_USER,
    *,
    start_time: datetime,
    end_time: datetime | None = None,
    endpoint: str = PUBLIC_INFO_URL,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Fetch bounded recent public events for a wallet.

    The API has response/history limits; callers must use a bounded window and
    keep the returned payload as an explicitly dated refresh rather than
    pretending it is a complete account history.
    """

    start_ms = int(start_time.astimezone(UTC).timestamp() * 1000)
    end_ms = int(end_time.astimezone(UTC).timestamp() * 1000) if end_time else None
    fills_payload: dict[str, Any] = {"type": "userFillsByTime", "user": user, "startTime": start_ms}
    funding_payload: dict[str, Any] = {"type": "userFunding", "user": user, "startTime": start_ms}
    if end_ms is not None:
        fills_payload["endTime"] = end_ms
        funding_payload["endTime"] = end_ms
    return {
        "target_user": user,
        "window_start": _iso(start_time),
        "window_end": _iso(end_time),
        "userFillsByTime": fetch_public_info(fills_payload, endpoint=endpoint, timeout=timeout),
        "userFunding": fetch_public_info(funding_payload, endpoint=endpoint, timeout=timeout),
    }


def _expected_file(manifest: Mapping[str, Any], name: str) -> dict[str, Any]:
    files = manifest.get("files") if isinstance(manifest, Mapping) else None
    item = files.get(name) if isinstance(files, Mapping) else None
    return dict(item) if isinstance(item, Mapping) else {}


def verify_snapshot_directory(data_dir: Path, manifest_path: Path) -> dict[str, Any]:
    """Verify the website's snapshot files byte-for-byte against its manifest."""

    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HyperliquidSourceError(f"invalid source manifest: {manifest_path}") from error
    if manifest.get("schema") != "paulwei.source-snapshot.v1":
        raise HyperliquidSourceError("unsupported Hyperliquid source manifest schema")
    checks: list[dict[str, Any]] = []
    for name in SOURCE_FILES:
        path = data_dir / name
        expected = _expected_file(manifest, name)
        actual = {"bytes": path.stat().st_size, "sha256": sha256_file(path)} if path.exists() else {}
        passed = bool(actual) and actual == {"bytes": expected.get("bytes"), "sha256": expected.get("sha256")}
        checks.append({"file": name, "status": "PASS" if passed else "FAIL", "actual": actual, "expected": expected})
    return {
        "status": "PASS" if all(item["status"] == "PASS" for item in checks) else "FAIL",
        "schema": manifest.get("schema"),
        "target_user": manifest.get("targetUser"),
        "source_repository": (manifest.get("source") or {}).get("repository"),
        "source_revision": (manifest.get("source") or {}).get("revision"),
        "synced_at": manifest.get("syncedAt"),
        "files": checks,
    }


def import_website_snapshot(
    destination: Path,
    *,
    revision: str = DEFAULT_SOURCE_REVISION,
    source_base: str = DEFAULT_WEBSITE_SOURCE_BASE,
    candle_url: str = DEFAULT_WEBSITE_CANDLE_URL,
    timeout: float = 60.0,
    include_candles: bool = True,
) -> dict[str, Any]:
    """Download and verify a pinned public snapshot into an ignored directory."""

    destination.mkdir(parents=True, exist_ok=True)
    base = source_base.rstrip("/") + "/"
    manifest_bytes = _json_bytes(base + "source-manifest.json", timeout=timeout)
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise HyperliquidSourceError("source manifest is not valid JSON") from error
    actual_revision = str((manifest.get("source") or {}).get("revision") or "")
    if actual_revision != revision:
        raise HyperliquidSourceError(f"source revision mismatch: requested {revision}, received {actual_revision}")
    if str(manifest.get("targetUser") or "").lower() != DEFAULT_TARGET_USER.lower():
        raise HyperliquidSourceError("source manifest belongs to an unexpected wallet")
    if str((manifest.get("source") or {}).get("repository") or "") != DEFAULT_SOURCE_REPOSITORY:
        raise HyperliquidSourceError("source manifest belongs to an unexpected repository")
    (destination / "source-manifest.json").write_bytes(manifest_bytes)
    for name in SOURCE_FILES:
        payload = _json_bytes(base + name, timeout=timeout)
        expected = _expected_file(manifest, name)
        actual = {"bytes": len(payload), "sha256": sha256_bytes(payload)}
        if actual != {"bytes": expected.get("bytes"), "sha256": expected.get("sha256")}:
            raise HyperliquidSourceError(f"source file hash mismatch: {name}")
        (destination / name).write_bytes(payload)
    candle_report: dict[str, Any] = {"status": "SKIPPED"}
    if include_candles:
        payload = _json_bytes(candle_url, timeout=timeout)
        try:
            candle_doc = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise HyperliquidSourceError("candle archive is not valid JSON") from error
        if candle_doc.get("schema") != "paulwei.candle-archive.v1" or candle_doc.get("interval") != "1h" or not isinstance(candle_doc.get("bars"), list):
            raise HyperliquidSourceError("unsupported Hyperliquid candle archive")
        (destination / "candles_1h.json").write_bytes(payload)
        candle_report = {"status": "PASS", "bytes": len(payload), "sha256": sha256_bytes(payload), "bars": len(candle_doc["bars"]), "source": candle_doc.get("source")}
    verification = verify_snapshot_directory(destination, destination / "source-manifest.json")
    result = {
        "status": "PASS" if verification["status"] == "PASS" and candle_report["status"] in {"PASS", "SKIPPED"} else "FAIL",
        "target_user": DEFAULT_TARGET_USER,
        "source_repository": DEFAULT_SOURCE_REPOSITORY,
        "source_revision": revision,
        "source_base": source_base,
        "destination": str(destination),
        "source_verification": verification,
        "candle_verification": candle_report,
    }
    (destination / "import-manifest.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return result


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise HyperliquidSourceError(f"invalid JSON source: {path}") from error


def load_candle_archive(path: Path) -> list[HyperliquidBar]:
    document = load_json(path)
    if document.get("schema") != "paulwei.candle-archive.v1" or document.get("interval") != "1h":
        raise HyperliquidSourceError("unsupported 1h candle archive")
    bars: list[HyperliquidBar] = []
    for raw in document.get("bars", []):
        try:
            open_ms = int(raw["t"])
            close_ms = int(raw["T"])
            values = tuple(float(raw[key]) for key in ("o", "h", "l", "c", "v"))
        except (KeyError, TypeError, ValueError):
            continue
        if values[0] <= 0 or values[1] <= 0 or values[2] <= 0 or values[3] <= 0 or values[4] < 0:
            continue
        bars.append(HyperliquidBar(
            datetime.fromtimestamp(open_ms / 1000, tz=UTC),
            datetime.fromtimestamp((close_ms + 1) / 1000, tz=UTC),
            values[0], values[1], values[2], values[3], values[4],
            str(document.get("source") or "Hyperliquid candleSnapshot"),
        ))
    bars.sort(key=lambda item: item.open_time)
    return bars


def bars_for_features(bars: Iterable[HyperliquidBar], funding: Iterable[Mapping[str, Any]] = ()) -> list[dict[str, Any]]:
    """Convert bars to the shared causal feature schema.

    Funding is carried as an as-of observation with its source timestamp.  It
    is not imputed to zero and must be charged separately by a replay engine.
    """

    funding_events: list[tuple[datetime, float]] = []
    for row in funding:
        timestamp = datetime.fromtimestamp(int(row.get("time", 0)) / 1000, tz=UTC) if row.get("time") else None
        delta = row.get("delta") if isinstance(row.get("delta"), Mapping) else {}
        rate = _decimal(delta.get("fundingRate"))
        if timestamp is not None and rate is not None:
            funding_events.append((timestamp, float(rate)))
    funding_events.sort()
    output: list[dict[str, Any]] = []
    funding_index = 0
    latest_funding: tuple[datetime, float] | None = None
    for bar in sorted(bars, key=lambda item: item.open_time):
        while funding_index < len(funding_events) and funding_events[funding_index][0] <= bar.close_time:
            latest_funding = funding_events[funding_index]
            funding_index += 1
        output.append({
            "timestamp": bar.close_time,
            "timestamp_utc": _iso(bar.close_time),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "turnover": None,
            "mark_price": None,
            "index_price": None,
            "funding_rate": latest_funding[1] if latest_funding else None,
            "funding_source_time": latest_funding[0] if latest_funding else None,
            "market_source": bar.source,
        })
    return output


def _classify_action(before: Decimal, after: Decimal) -> str:
    if before == 0 and after > 0:
        return "OPEN_LONG"
    if before == 0 and after < 0:
        return "OPEN_SHORT"
    if before > 0 and after > before:
        return "ADD_LONG"
    if before < 0 and after < before:
        return "ADD_SHORT"
    if before > 0 and after == 0:
        return "CLOSE_LONG"
    if before < 0 and after == 0:
        return "CLOSE_SHORT"
    if before > 0 and 0 < after < before:
        return "REDUCE_LONG"
    if before < 0 and before < after < 0:
        return "REDUCE_SHORT"
    if before > 0 and after < 0:
        return "FLIP_SHORT"
    if before < 0 and after > 0:
        return "FLIP_LONG"
    return "NO_POSITION_CHANGE"


def normalize_fills(fills: Iterable[Mapping[str, Any]], *, cutoff: datetime | None = None) -> list[HyperliquidBehaviorEvent]:
    """Normalize BTC perpetual fills into venue-neutral behavior events."""

    ordered = sorted(
        (row for row in fills if str(row.get("coin") or "") == "BTC"),
        key=lambda row: (int(row.get("time") or 0), int(row.get("tid") or 0)),
    )
    current = Decimal("0")
    output: list[HyperliquidBehaviorEvent] = []
    for row in ordered:
        timestamp = datetime.fromtimestamp(int(row.get("time", 0)) / 1000, tz=UTC)
        if cutoff is not None and timestamp > cutoff:
            continue
        size = _decimal(row.get("sz"))
        price = _decimal(row.get("px"))
        if size is None or price is None or size < 0 or price <= 0:
            continue
        reported_before = _decimal(row.get("startPosition"))
        before = reported_before if reported_before is not None else current
        after = before + (size if str(row.get("side")) == "B" else -size)
        current = after
        tid = str(row.get("tid") or "")
        output.append(HyperliquidBehaviorEvent(
            event_id=f"HL-BTC-FILL-{tid}",
            time=timestamp,
            source_venue="HYPERLIQUID",
            source_symbol="BTC",
            canonical_asset="BTC-PERP",
            before_position=before,
            after_position=after,
            action=_classify_action(before, after),
            order_id=str(row.get("oid") or ""),
            fill_id=tid,
            price=price,
            size=size,
            fee=_decimal(row.get("fee"), Decimal("0")) or Decimal("0"),
            fee_currency=str(row.get("feeToken") or "USDC"),
        ))
    return output


def next_strictly_later_event(events: list[HyperliquidBehaviorEvent], index: int) -> HyperliquidBehaviorEvent | None:
    """Return the next event after a timestamp, skipping same-time fill ties."""

    current_time = events[index].time
    next_index = index + 1
    while next_index < len(events) and events[next_index].time <= current_time:
        next_index += 1
    return events[next_index] if next_index < len(events) else None


def load_funding(path: Path, *, cutoff: datetime | None = None) -> list[dict[str, Any]]:
    rows = load_json(path)
    if not isinstance(rows, list):
        raise HyperliquidSourceError("userFunding must be an array")
    return [
        row for row in rows
        if isinstance(row, Mapping)
        and (cutoff is None or datetime.fromtimestamp(int(row.get("time", 0)) / 1000, tz=UTC) <= cutoff)
    ]


def build_hyperliquid_feature_rows(
    source_dir: Path,
    *,
    cutoff: datetime | None = None,
    position_scale: float = 1.0,
) -> tuple[list[dict[str, Any]], list[HyperliquidBar], list[dict[str, Any]]]:
    """Build indicator-enhanced feature/label rows from the public snapshot."""

    fills = load_json(source_dir / "userFillsByTime.json")
    funding = load_funding(source_dir / "userFunding.json", cutoff=cutoff)
    events = normalize_fills(fills, cutoff=cutoff)
    bars = load_candle_archive(source_dir / "candles_1h.json")
    bars = [bar for bar in bars if cutoff is None or bar.close_time <= cutoff + timedelta(hours=1)]
    feature_bars = bars_for_features(bars, funding)
    feature_times = [row["timestamp"] for row in feature_bars]
    rows: list[dict[str, Any]] = []
    for index, event in enumerate(events):
        market = build_market_features(feature_bars, event.time, timestamps=feature_times, bar_seconds=3600)
        next_event = next_strictly_later_event(events, index)
        row = {
            "decision_episode_id": event.event_id,
            "decision_time": _iso(event.time),
            "symbol": "HL-BTC-PERP",
            "decision_type": "FILL",
            "observed_action": event.action,
            "observed_position_before_contracts": float(event.before_position),
            "observed_target_position_contracts": float(event.after_position),
            "observed_position_delta_contracts": float(event.after_position - event.before_position),
            "synthetic_negative_sample": False,
            "observed_overall_confidence": "HIGH",
            "source_venue": "HYPERLIQUID",
            "source_repository": DEFAULT_SOURCE_REPOSITORY,
            "source_revision": "",
            "source_symbol": event.source_symbol,
            "canonical_asset": event.canonical_asset,
            "market_coverage_status": "PASS" if market.get("feature_market_data_available") and market.get("feature_volume_percentile_72bar") is not None else ("WARMUP_INSUFFICIENT" if market.get("feature_latest_bar_time") else "MISSING_MARKET_DATA"),
            "row_market_coverage_status": "PASS" if market.get("feature_volume_percentile_72bar") is not None and market.get("feature_rsi_14") is not None and market.get("feature_macd_histogram") is not None and market.get("feature_bollinger_percent_b_20") is not None else ("WARMUP_INSUFFICIENT" if market.get("feature_latest_bar_time") else "MISSING_MARKET_DATA"),
            "position_scale_fit_available": True,
            "model_eligible": False,
            "feature_symbol": "HYPERLIQUID:BTC-PERP",
            "feature_instrument_class": "DERIVATIVE",
            "feature_payout_model": "LINEAR",
            "feature_quote_currency": "USDC",
            "feature_settlement_currency": "USDC",
            "feature_market_bar_interval": "1h",
            "feature_contract_lot_size": 0.00001,
            "feature_multiplier_major": 1.0,
            "feature_current_net_position_contracts": float(event.before_position),
            "feature_current_normalized_exposure": float(event.before_position) / position_scale,
            "feature_position_scale_contracts": position_scale,
            "raw_current_position_contracts": float(event.before_position),
            "raw_target_position_contracts": float(event.after_position),
            "raw_next_target_position_contracts": float(next_event.after_position) if next_event else "",
            "source_order_id": event.order_id,
            "source_fill_id": event.fill_id,
            "source_fill_price": str(event.price),
            "source_fee": str(event.fee),
            "source_fee_currency": event.fee_currency,
            **market,
        }
        for key, value in ("label_next_decision_time", _iso(next_event.time) if next_event else ""), ("label_next_target_position_contracts", float(next_event.after_position) if next_event else ""), ("label_next_target_exposure", float(next_event.after_position) / position_scale if next_event else ""), ("label_next_action", next_event.action if next_event else ""), ("label_status", "AVAILABLE" if next_event else "UNAVAILABLE"):
            row[key] = value
        row["model_eligible"] = row["row_market_coverage_status"] == "PASS" and bool(next_event)
        rows.append(row)
    return rows, bars, funding


__all__ = [
    "DEFAULT_SOURCE_REVISION",
    "DEFAULT_TARGET_USER",
    "HyperliquidBar",
    "HyperliquidBehaviorEvent",
    "HyperliquidSourceError",
    "SOURCE_FILES",
    "bars_for_features",
    "build_hyperliquid_feature_rows",
    "fetch_public_info",
    "fetch_recent_public_events",
    "import_website_snapshot",
    "load_candle_archive",
    "load_funding",
    "normalize_fills",
    "next_strictly_later_event",
    "sha256_file",
    "verify_snapshot_directory",
]
