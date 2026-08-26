#!/usr/bin/env python3
"""Fetch a bounded, credential-free Hyperliquid public API refresh.

This is deliberately not a historical backfill.  Hyperliquid's public API
has bounded response/history windows, so the result is stored as a dated,
ignored observation that can be compared with the pinned website snapshot.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cross_asset.hyperliquid import (  # noqa: E402
    DEFAULT_TARGET_USER,
    HyperliquidSourceError,
    fetch_recent_public_events,
)

UTC = timezone.utc


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)


def _compact(value: object) -> object:
    if isinstance(value, list):
        return [_compact(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _compact(item) for key, item in value.items()}
    return value


def refresh(*, user: str, start: datetime, end: datetime, endpoint: str, output: Path) -> dict[str, object]:
    if end <= start:
        raise ValueError("end time must be after start time")
    payload = fetch_recent_public_events(user, start_time=start, end_time=end, endpoint=endpoint)
    normalized = _compact(payload)
    serialized = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    result = {
        "status": "PASS",
        "source": "Hyperliquid official public info endpoint",
        "endpoint": endpoint,
        "target_user": user,
        "window_start": start.isoformat().replace("+00:00", "Z"),
        "window_end": end.isoformat().replace("+00:00", "Z"),
        "sha256": hashlib.sha256(serialized).hexdigest(),
        "fills": len(normalized.get("userFillsByTime", [])) if isinstance(normalized, dict) else 0,
        "funding": len(normalized.get("userFunding", [])) if isinstance(normalized, dict) else 0,
        "credentials_used": False,
        "payload": normalized,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return {key: value for key, value in result.items() if key != "payload"}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--user", default=DEFAULT_TARGET_USER)
    parser.add_argument("--start", type=parse_utc, help="UTC ISO timestamp; defaults to 7 days ago")
    parser.add_argument("--end", type=parse_utc, help="UTC ISO timestamp; defaults to now")
    parser.add_argument("--endpoint", default="https://api.hyperliquid.xyz/info")
    parser.add_argument("--output", type=Path, default=ROOT / "quant" / "outputs" / "hyperliquid_public_api_refresh.json")
    args = parser.parse_args()
    end = args.end or datetime.now(UTC)
    start = args.start or end - timedelta(days=7)
    try:
        result = refresh(user=args.user, start=start, end=end, endpoint=args.endpoint, output=args.output.resolve())
    except (HyperliquidSourceError, OSError, ValueError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "HYPERLIQUID_PUBLIC_API_REFRESH_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
