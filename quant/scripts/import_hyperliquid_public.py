#!/usr/bin/env python3
"""Import and verify the pinned public Hyperliquid teacher snapshot."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cross_asset.hyperliquid import (  # noqa: E402
    DEFAULT_SOURCE_REVISION,
    DEFAULT_WEBSITE_CANDLE_URL,
    DEFAULT_WEBSITE_SOURCE_BASE,
    HyperliquidSourceError,
    build_hyperliquid_feature_rows,
    import_website_snapshot,
)
from build_hyperliquid_replay_dashboard import build as build_replay_dashboard  # noqa: E402


def parse_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def write_normalized_outputs(source_dir: Path, cutoff: datetime | None, *, build_dashboard: bool = True) -> dict[str, int | dict[str, object]]:
    rows, bars, funding = build_hyperliquid_feature_rows(source_dir, cutoff=cutoff)
    output_dir = ROOT / "quant" / "outputs"
    output_dir.mkdir(parents=True, exist_ok=True)
    feature_path = output_dir / "hyperliquid_btc_feature_rows.csv"
    import csv

    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with feature_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    summary = {
        "status": "PASS",
        "feature_rows": len(rows),
        "eligible_rows": sum(bool(row.get("model_eligible")) for row in rows),
        "bars": len(bars),
        "funding_records": len(funding),
        "cutoff": cutoff.isoformat().replace("+00:00", "Z") if cutoff else None,
        "feature_output": "quant/outputs/hyperliquid_btc_feature_rows.csv (ignored)",
    }
    if build_dashboard:
        summary["replay_dashboard"] = build_replay_dashboard(
            source_dir,
            ROOT / "quant" / "outputs" / "replay_dashboard_hyperliquid_btc.json",
            cutoff,
        )
    (ROOT / "quant" / "reports" / "hyperliquid_feature_summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default=DEFAULT_SOURCE_REVISION)
    parser.add_argument("--source-base", default=DEFAULT_WEBSITE_SOURCE_BASE)
    parser.add_argument("--candle-url", default=DEFAULT_WEBSITE_CANDLE_URL)
    parser.add_argument("--destination", type=Path, default=ROOT / "quant" / "data" / "external" / "hyperliquid" / "paul")
    parser.add_argument("--cutoff", type=parse_utc, help="optional inclusive UTC cutoff for normalized rows")
    parser.add_argument("--skip-candles", action="store_true")
    parser.add_argument("--skip-dashboard", action="store_true", help="do not build the ignored local replay payload")
    args = parser.parse_args()
    destination = args.destination / args.revision
    try:
        result = import_website_snapshot(
            destination,
            revision=args.revision,
            source_base=args.source_base,
            candle_url=args.candle_url,
            include_candles=not args.skip_candles,
        )
        result["normalized"] = write_normalized_outputs(destination, args.cutoff, build_dashboard=not args.skip_dashboard)
    except (HyperliquidSourceError, OSError, ValueError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "HYPERLIQUID_SOURCE_IMPORT_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
