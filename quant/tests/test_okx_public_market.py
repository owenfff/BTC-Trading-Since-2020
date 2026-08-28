from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from market.okx_public import (
    OkxPublicClient,
    attach_okx_context,
    audit_okx_grid,
    build_causal_indicator_rows,
    fetch_history_candles,
    infer_index_id,
)


def _iso(timestamp: datetime) -> str:
    return timestamp.isoformat(timespec="milliseconds").replace("+00:00", "Z")


class FakeOkxClient:
    base_url = "https://www.okx.com/api/v5"

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.pages = {
            "10800000": [["7200000", "102", "103", "101", "102.5", "10", "1", "1025", "1"], ["3600000", "101", "102", "100", "101", "9", "0.9", "909", "1"]],
            "3600000": [["0", "100", "101", "99", "100.5", "8", "0.8", "804", "1"]],
        }

    def build_url(self, endpoint: str, params: dict[str, object] | None = None) -> str:
        return f"{self.base_url}{endpoint}?{params}"

    def get_json(self, endpoint: str, params: dict[str, object] | None = None):
        params = dict(params or {})
        self.calls.append((endpoint, params))
        return {"code": "0", "msg": "", "data": self.pages.get(str(params.get("after")) if params.get("after") is not None else None, [])}, self.build_url(endpoint, params)


def test_public_client_rejects_non_okx_hosts() -> None:
    with pytest.raises(ValueError):
        OkxPublicClient(base_url="https://example.invalid/api/v5")


def test_public_client_does_not_have_credential_parameters() -> None:
    client = OkxPublicClient()
    url = client.build_url("/market/history-candles", {"instId": "BTC-USDT-SWAP", "bar": "1H", "limit": 300})
    assert "apiKey" not in url and "secret" not in url and "passphrase" not in url
    assert "history-candles" in url and "bar=1H" in url


def test_history_candles_paginates_backward_and_keeps_closed_rows() -> None:
    client = FakeOkxClient()
    rows, lineage = fetch_history_candles(
        client,
        inst_id="BTC-USDT-SWAP",
        bar="1H",
        start="1970-01-01T00:00:00Z",
        end="1970-01-01T03:00:00Z",
        limit=2,
        max_pages=5,
        sleep_seconds=0,
    )
    assert [row["source_timestamp_ms"] for row in rows] == ["0", "3600000", "7200000"]
    assert lineage["page_count"] == 2
    assert client.calls[0][1]["after"] == "10800000"
    assert client.calls[0][1]["bar"] == "1H"


def test_unclosed_candles_are_rejected_without_replacement() -> None:
    class OnePage(FakeOkxClient):
        def __init__(self) -> None:
            super().__init__()
            self.pages = {"3600000": [["0", "100", "101", "99", "100", "1", "1", "100", "0"]]}

    rows, lineage = fetch_history_candles(OnePage(), inst_id="BTC-USDT-SWAP", start="1970-01-01Z", end="1970-01-01T01:00:00Z", sleep_seconds=0)
    assert rows == []
    assert lineage["rejected_counts"] == {"unclosed_candle": 1}


def test_context_never_uses_future_mark_or_index() -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = [{"inst_id": "BTC-USDT-SWAP", "timestamp": _iso(base), "open": "100", "high": "101", "low": "99", "close": "100", "volume": "1"}]
    future_mark = [{"inst_id": "BTC-USDT-SWAP", "timestamp": _iso(base + timedelta(hours=1)), "close": "101"}]
    prior_funding = [{"inst_id": "BTC-USDT-SWAP", "timestamp": _iso(base - timedelta(hours=1)), "funding_rate": "0.001"}]
    joined, audit = attach_okx_context(candles, mark_rows=future_mark, funding_rows=prior_funding)
    assert joined[0]["mark_price"] is None
    assert joined[0]["index_price"] is None
    assert joined[0]["funding_rate"] == "0.001"
    assert joined[0]["feature_mark_missing"] is True
    assert audit["status_counts"] == {"MARK_INDEX_MISSING": 1}


def test_indicator_rows_use_closed_bars_and_shared_indicator_logic() -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    candles = []
    for index in range(100):
        close = 100 + index * 0.1
        timestamp = base + timedelta(hours=index + 1)
        candles.append({
            "inst_id": "BTC-USDT-SWAP",
            "timestamp": _iso(timestamp),
            "open": str(close - 0.1),
            "high": str(close + 0.2),
            "low": str(close - 0.2),
            "close": str(close),
            "volume": "10",
            "context_status": "FUNDING_MISSING",
        })
    rows, audit = build_causal_indicator_rows(candles, interval_seconds=3600)
    assert audit["causal_timestamp_violation_count"] == 0
    assert rows[-1]["feature_rsi_14"] is not None
    assert rows[-1]["feature_macd_histogram"] is not None
    assert rows[-1]["feature_bollinger_percent_b_20"] is not None
    assert rows[-1]["feature_volume_percentile_72bar"] is not None
    assert rows[-1]["feature_latest_bar_time"] < rows[-1]["decision_time_utc"]


def test_grid_audit_reports_missing_hour_without_filling() -> None:
    base = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rows = [{"timestamp": _iso(base)}, {"timestamp": _iso(base + timedelta(hours=2))}]
    audit = audit_okx_grid(rows, interval_seconds=3600)
    assert audit["status"] == "WARNING"
    assert audit["missing_grid_count"] == 1


def test_index_id_is_derived_without_changing_symbol_semantics() -> None:
    assert infer_index_id("BTC-USDT-SWAP") == "BTC-USDT"
    assert infer_index_id("BTC-USD-SWAP") == "BTC-USD"
    assert infer_index_id("BTC-USDT") == "BTC-USDT"
