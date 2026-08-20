from __future__ import annotations

from datetime import datetime, timezone

from market.context import attach_market_context
from market.download import build_trade_bucketed_url, parse_utc
from market.gaps import audit_time_grid, build_gap_rows
from market.normalize import normalize_trade_bars


def _bar(timestamp: str, close: float = 100.0) -> dict[str, object]:
    return {
        "timestamp": timestamp,
        "symbol": "XBTUSD",
        "open": close - 1,
        "high": close + 1,
        "low": close - 2,
        "close": close,
        "volume": 10,
        "turnover": 100,
    }


def test_public_url_has_no_credentials_and_uses_utc_filters() -> None:
    url = build_trade_bucketed_url("XBTUSD", "5m", start_time="2020-01-01T00:00:00Z", end_time="2020-01-01T01:00:00Z")
    assert "apiKey" not in url and "apiSecret" not in url
    assert "startTime=2020-01-01T00%3A00%3A00.000Z" in url
    assert "binSize=5m" in url


def test_normalization_rejects_invalid_bars_without_filling() -> None:
    rows, stats = normalize_trade_bars([_bar("2020-01-01T00:05:00Z"), _bar("bad"), {**_bar("2020-01-01T00:10:00Z"), "close": 0}])
    assert len(rows) == 1
    assert stats["rejected_counts"] == {"timestamp_parse_failed": 1, "non_positive_ohlc": 1}


def test_grid_audit_finds_missing_bar_and_duplicate() -> None:
    rows = [_bar("2020-01-01T00:05:00Z"), _bar("2020-01-01T00:05:00Z"), _bar("2020-01-01T00:15:00Z")]
    audit = audit_time_grid(rows, interval_seconds=300)
    gaps = build_gap_rows(rows, interval_seconds=300, series="XBTUSD:5m")
    assert audit["duplicate_timestamp_count"] == 1
    assert audit["missing_grid_count"] == 1
    assert gaps[0]["missing_bar_count"] == 1


def test_context_join_is_previous_or_equal_and_never_future() -> None:
    bars = [{"timestamp": "2020-01-01T00:05:00Z", "close": 100}]
    instrument = [{"timestamp": "2020-01-01T00:06:00Z", "mark_price": 101, "index_price": 100}]
    funding = [{"timestamp": "2020-01-01T00:00:00Z", "funding_rate": 0.001}]
    joined, audit = attach_market_context(bars, instrument_rows=instrument, funding_rows=funding)
    assert joined[0]["mark_price"] is None
    assert joined[0]["funding_rate"] == 0.001
    assert audit["status_counts"]["MARK_INDEX_MISSING"] == 1


def test_context_join_accepts_equal_timestamp() -> None:
    bars = [{"timestamp": "2020-01-01T00:05:00Z", "close": 100}]
    instrument = [{"timestamp": "2020-01-01T00:05:00Z", "mark_price": 101, "index_price": 100}]
    funding = [{"timestamp": "2020-01-01T00:05:00Z", "funding_rate": 0.001}]
    joined, _ = attach_market_context(bars, instrument_rows=instrument, funding_rows=funding)
    assert joined[0]["context_status"] == "COMPLETE"


def test_parse_utc_normalizes_naive_values_to_utc() -> None:
    parsed = parse_utc("2020-01-01T00:00:00")
    assert parsed == datetime(2020, 1, 1, tzinfo=timezone.utc)
