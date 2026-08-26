from __future__ import annotations

from datetime import datetime, timedelta, timezone
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cross_asset.hyperliquid import (
    HyperliquidSourceError,
    fetch_public_info,
    normalize_fills,
)
from features.market_features import build_market_features

REFRESH_PATH = ROOT / "quant" / "scripts" / "refresh_hyperliquid_public.py"
REFRESH_SPEC = importlib.util.spec_from_file_location("refresh_hyperliquid_public_test", REFRESH_PATH)
assert REFRESH_SPEC and REFRESH_SPEC.loader
refresh_public = importlib.util.module_from_spec(REFRESH_SPEC)
REFRESH_SPEC.loader.exec_module(refresh_public)


UTC = timezone.utc


def test_public_info_rejects_credential_shaped_payload_without_network() -> None:
    with pytest.raises(HyperliquidSourceError, match="credential"):
        fetch_public_info({"type": "userFillsByTime", "user": "wallet", "api_key": "should-never-be-accepted"})


def test_hyperliquid_fills_normalize_position_actions_and_keep_units() -> None:
    fills = [
        {"coin": "BTC", "time": 1_700_000_000_000, "tid": 1, "oid": 10, "side": "B", "sz": "0.10", "px": "30000", "startPosition": "0", "fee": "0.1", "feeToken": "USDC"},
        {"coin": "BTC", "time": 1_700_000_360_000, "tid": 2, "oid": 11, "side": "A", "sz": "0.04", "px": "30100", "startPosition": "0.10", "fee": "0.04", "feeToken": "USDC"},
        {"coin": "ETH", "time": 1_700_000_720_000, "tid": 3, "oid": 12, "side": "B", "sz": "1", "px": "2000", "startPosition": "0", "fee": "1", "feeToken": "USDC"},
    ]
    events = normalize_fills(fills)
    assert [event.action for event in events] == ["OPEN_LONG", "REDUCE_LONG"]
    assert events[0].fee_currency == "USDC"
    assert events[1].after_position == events[0].after_position - events[1].size


def test_market_features_never_use_a_bar_at_or_after_decision_time() -> None:
    start = datetime(2025, 1, 1, tzinfo=UTC)
    bars = []
    for index in range(100):
        timestamp = start + timedelta(hours=index)
        bars.append({
            "timestamp": timestamp,
            "open": 100 + index,
            "high": 101 + index,
            "low": 99 + index,
            "close": 100 + index,
            "volume": 10 + index,
            "funding_rate": None,
            "funding_source_time": None,
        })
    decision = start + timedelta(hours=80, minutes=30)
    result = build_market_features(bars, decision, timestamps=[row["timestamp"] for row in bars], bar_seconds=3600)
    assert result["feature_latest_bar_time"] == (start + timedelta(hours=80)).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    assert result["feature_latest_bar_time"] < decision.isoformat().replace("+00:00", "Z")


def test_public_api_refresh_is_bounded_and_never_reports_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(refresh_public, "fetch_recent_public_events", lambda *args, **kwargs: {"userFillsByTime": [{"tid": 1}], "userFunding": []})
    start = datetime(2025, 1, 1, tzinfo=UTC)
    summary = refresh_public.refresh(user="0xabc", start=start, end=start + timedelta(days=1), endpoint="https://api.hyperliquid.xyz/info", output=tmp_path / "refresh.json")
    assert summary["credentials_used"] is False
    assert summary["fills"] == 1
    assert "secret" not in (tmp_path / "refresh.json").read_text(encoding="utf-8").lower()
