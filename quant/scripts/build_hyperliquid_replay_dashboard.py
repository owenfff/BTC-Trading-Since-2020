#!/usr/bin/env python3
"""Build an ignored, compact Hyperliquid replay payload for the local panel."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cross_asset.hyperliquid import (  # noqa: E402
    DEFAULT_SOURCE_REVISION,
    HyperliquidSourceError,
    bars_for_features,
    build_market_features,
    load_candle_archive,
    load_funding,
    load_json,
    normalize_fills,
)
from features.market_features import build_market_features  # noqa: E402

UTC = timezone.utc


def _ms(value: datetime) -> int:
    return int(value.timestamp() * 1000)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def build(source_dir: Path, output: Path, cutoff: datetime | None = None) -> dict[str, object]:
    bars = load_candle_archive(source_dir / "candles_1h.json")
    if cutoff is not None:
        bars = [bar for bar in bars if bar.close_time <= cutoff]
    if not bars:
        raise HyperliquidSourceError("no Hyperliquid 1h bars are available")
    funding = load_funding(source_dir / "userFunding.json", cutoff=cutoff)
    feature_bars = bars_for_features(bars, funding)
    fills = load_json(source_dir / "userFillsByTime.json")
    events = normalize_fills(fills, cutoff=cutoff)
    output_bars: list[dict[str, object]] = []
    for index, bar in enumerate(bars):
        # This is a display snapshot at the close of a bar. The strategy audit
        # itself uses the prior closed bar and next-bar execution convention.
        decision_time = bar.close_time + timedelta(microseconds=1)
        indicators = build_market_features(feature_bars, decision_time, timestamps=[row["timestamp"] for row in feature_bars], bar_seconds=3600)
        output_bars.append({
            "ts": _ms(bar.close_time),
            "open_ts": _ms(bar.open_time),
            "open": bar.open,
            "high": bar.high,
            "low": bar.low,
            "close": bar.close,
            "volume": bar.volume,
            "indicators": {
                "rsi14": indicators.get("feature_rsi_14"),
                "macd_histogram": indicators.get("feature_macd_histogram"),
                "bollinger_percent_b": indicators.get("feature_bollinger_percent_b_20"),
                "volume_percentile_72": indicators.get("feature_volume_percentile_72bar"),
                "funding_rate": indicators.get("feature_funding_rate"),
                "mark_index_basis": indicators.get("feature_mark_index_basis"),
                "coverage": "COMPLETE" if all(indicators.get(key) is not None for key in ("feature_rsi_14", "feature_macd_histogram", "feature_bollinger_percent_b_20", "feature_volume_percentile_72bar")) else "PARTIAL",
            },
        })

    orders: list[dict[str, object]] = []
    pnl: list[dict[str, object]] = []
    running_pnl = 0.0
    for event in events:
        timestamp = _ms(event.time)
        side = "Buy" if event.action.endswith("LONG") or event.action in {"OPEN_LONG", "ADD_LONG", "FLIP_LONG"} else "Sell"
        raw_fill = next((row for row in fills if str(row.get("tid") or "") == event.fill_id), {})
        try:
            closed_pnl = float(raw_fill.get("closedPnl") or 0.0)
        except (TypeError, ValueError):
            closed_pnl = 0.0
        running_pnl += closed_pnl
        orders.append({
            "start_ts": timestamp,
            "end_ts": timestamp,
            "side": side,
            "action": event.action,
            "status": "Filled",
            "filled": float(event.size),
            "order_qty": float(event.size),
            "leaves": 0.0,
            "price": float(event.price),
            "position_before": float(event.before_position),
            "position_after": float(event.after_position),
            "order_id": event.order_id,
            "fill_id": event.fill_id,
            "is_filled": True,
        })
        pnl.append({"ts": timestamp, "value": running_pnl})
    all_timestamps = [row["ts"] for row in output_bars] + [row["start_ts"] for row in orders]
    payload = {
        "schema": "quant.replay-dashboard.v2",
        "venue": "HYPERLIQUID",
        "symbol": "HL-BTC-PERP",
        "source": "Hyperliquid public candleSnapshot archive + public user fills",
        "source_repository": "pystashell/track_paul_btc_hyperliquid_trade",
        "source_revision": DEFAULT_SOURCE_REVISION,
        "target_user": "0xdae4df7207feb3b350e4284c8efe5f7dac37f637",
        "strategy_replay_boundary": "display only; strict autonomous model audit uses prior closed bar and next-bar open",
        "pnl_unit": "USDC observed closedPnl from public fills",
        "available": True,
        "full_start_ts": min(all_timestamps) if all_timestamps else None,
        "full_end_ts": max(all_timestamps) if all_timestamps else None,
        "bars": output_bars,
        "orders": orders,
        "pnl": pnl,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    return {"status": "PASS", "output": str(output.relative_to(ROOT)), "bars": len(output_bars), "orders": len(orders), "pnl_points": len(pnl), "source_revision": DEFAULT_SOURCE_REVISION}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=ROOT / "quant" / "data" / "external" / "hyperliquid" / "paul" / DEFAULT_SOURCE_REVISION)
    parser.add_argument("--output", type=Path, default=ROOT / "quant" / "outputs" / "replay_dashboard_hyperliquid_btc.json")
    parser.add_argument("--cutoff", type=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")))
    args = parser.parse_args()
    try:
        result = build(args.source_dir.resolve(), args.output.resolve(), args.cutoff)
    except (HyperliquidSourceError, OSError, ValueError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "HYPERLIQUID_REPLAY_BUILD_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
