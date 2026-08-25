from __future__ import annotations

import pytest

import quant_bot.multivenue_runtime as multivenue
from quant_bot.exchanges.http import AdapterError


def test_multivenue_normalizes_and_deduplicates_venues() -> None:
    assert multivenue._normalize_venues("okx-demo,binance-spot-testnet,okx-demo") == (
        "okx-demo",
        "binance-spot-testnet",
    )


def test_multivenue_rejects_unsupported_venue() -> None:
    with pytest.raises(AdapterError) as error:
        multivenue._normalize_venues("bybit-demo")
    assert error.value.code == "UNSUPPORTED_VENUE"


def test_multivenue_keeps_one_venue_blocked_without_hiding_other(monkeypatch: pytest.MonkeyPatch) -> None:
    def fake_run(*, venue: str, **_: object) -> dict[str, str]:
        if venue == "okx-demo":
            return {"status": "STOPPED_READ_ONLY", "venue": venue}
        raise AdapterError(venue, "DEMO_CREDENTIALS_REQUIRED", "local credentials required")

    monkeypatch.setattr(multivenue, "run_foreground_venue", fake_run)
    result = multivenue.run_foreground_multivenue(
        venues=("okx-demo", "binance-spot-testnet"),
        once=True,
    )
    assert result["status"] == "STOPPED_READ_ONLY"
    assert result["blocked_venues"] == ["binance-spot-testnet"]
    assert result["venues"]["okx-demo"]["status"] == "STOPPED_READ_ONLY"
    assert result["venues"]["binance-spot-testnet"]["status"] == "BLOCKED"
