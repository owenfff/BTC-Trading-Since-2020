from __future__ import annotations

from datetime import datetime, timezone

from market.archive import aggregate_trade_rows, archive_trade_url
from market.context import attach_market_context
from market.download import build_trade_bucketed_url, parse_utc
from market.gaps import audit_time_grid, build_gap_rows
from market.normalize import normalize_trade_bars, resample_trade_bars


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


def test_resample_derives_one_hour_bars_without_filling_missing_children() -> None:
    source = [_bar(f"2020-01-01T00:{minute:02d}:00Z", close=100 + minute) for minute in (5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 0)]
    source[-1]["timestamp"] = "2020-01-01T01:00:00Z"
    rows, audit = resample_trade_bars(source, source_interval_minutes=5, target_interval_minutes=60)
    assert len(rows) == 1
    assert rows[0]["bar_interval"] == "1h"
    assert rows[0]["child_bar_count"] == 12
    assert rows[0]["expected_child_bar_count"] == 12
    assert audit["incomplete_target_bar_count"] == 0


def test_parse_utc_normalizes_naive_values_to_utc() -> None:
    parsed = parse_utc("2020-01-01T00:00:00")
    assert parsed == datetime(2020, 1, 1, tzinfo=timezone.utc)


def test_official_archive_url_is_date_partitioned_and_public() -> None:
    assert archive_trade_url(datetime(2020, 1, 2, tzinfo=timezone.utc).date()) == "https://s3-eu-west-1.amazonaws.com/public.bitmex.com/data/trade/20200102.csv.gz"


def test_archive_trade_aggregation_uses_closed_utc_bucket_without_fill() -> None:
    rows = [
        {"timestamp": "2020-01-01T00:00:01Z", "symbol": "XBTUSD", "price": "100", "size": "2", "foreignNotional": "2"},
        {"timestamp": "2020-01-01T00:04:59Z", "symbol": "XBTUSD", "price": "101", "size": "3", "foreignNotional": "3"},
        {"timestamp": "2020-01-01T00:10:01Z", "symbol": "XBTUSD", "price": "99", "size": "1", "foreignNotional": "1"},
    ]
    bars = aggregate_trade_rows(rows)
    assert len(bars) == 2
    assert bars[0]["timestamp"] == "2020-01-01T00:05:00.000Z"
    assert bars[0]["open"] == 100 and bars[0]["close"] == 101
    assert bars[0]["volume"] == 5
    assert bars[1]["timestamp"] == "2020-01-01T00:15:00.000Z"
