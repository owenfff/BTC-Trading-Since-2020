from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
for path in (ROOT / "quant" / "scripts", ROOT / "quant" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from summarize_strategy_behavior import (  # noqa: E402
    analyze_rows,
    bucket_bollinger,
    bucket_rsi,
)


def test_indicator_buckets_have_explicit_boundaries_and_missing_state() -> None:
    assert bucket_rsi(29.9) == "<30_OVERSOLD"
    assert bucket_rsi(30) == "30-45"
    assert bucket_rsi(70) == ">=70_OVERBOUGHT"
    assert bucket_rsi(None) == "MISSING"
    assert bucket_bollinger(0.1) == "0-0.2_LOWER_ZONE"
    assert bucket_bollinger(1.1) == ">1_ABOVE_UPPER"


def test_profile_is_descriptive_and_keeps_venue_symbol_separate() -> None:
    rows = [
        {
            "decision_time": "2021-01-01T00:00:00Z",
            "source_venue": "BITMEX",
            "canonical_asset": "BTC-PERP",
            "model_eligible": "true",
            "label_next_action": "OPEN_LONG",
            "label_next_target_exposure": "0.2",
            "feature_rsi_14": "25",
            "feature_bollinger_percent_b_20": "0.1",
            "feature_current_normalized_exposure": "0",
            "feature_market_regime": "TREND_UP",
            "feature_return_24bar": "0.1",
            "feature_cycle_duration_seconds": "0",
        },
        {
            "decision_time": "2021-01-01T01:00:00Z",
            "source_venue": "HYPERLIQUID",
            "canonical_asset": "BTC-PERP",
            "model_eligible": "true",
            "label_next_action": "NO_TRADE",
            "label_next_target_exposure": "0.2",
            "feature_rsi_14": "55",
            "feature_bollinger_percent_b_20": "0.5",
            "feature_current_normalized_exposure": "0.2",
            "feature_market_regime": "RANGE_OR_MIXED",
            "feature_return_24bar": "-0.1",
            "feature_cycle_duration_seconds": "3600",
        },
    ]
    summary, symbols = analyze_rows(rows)
    assert summary["eligible_rows"] == 2
    assert set(summary["by_venue"]) == {"BITMEX", "HYPERLIQUID"}
    assert len(symbols) == 2
    assert summary["interpretation_boundary"]
