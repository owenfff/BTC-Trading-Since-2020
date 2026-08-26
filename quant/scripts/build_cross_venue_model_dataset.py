#!/usr/bin/env python3
"""Build a rowwise, venue-separated BitMEX + Hyperliquid model dataset."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from cross_asset.hyperliquid import (  # noqa: E402
    DEFAULT_SOURCE_REPOSITORY,
    DEFAULT_SOURCE_REVISION,
    build_hyperliquid_feature_rows,
)


UTC = timezone.utc
REQUIRED_V2_FEATURES = (
    "feature_return_24bar",
    "feature_return_72bar",
    "feature_realized_volatility_72bar",
    "feature_atr_14bar",
    "feature_ma_distance_24bar",
    "feature_trend_slope_24bar",
)
REQUIRED_V3_FEATURES = REQUIRED_V2_FEATURES + (
    "feature_volume_percentile_72bar",
    "feature_rsi_14",
    "feature_macd_histogram",
    "feature_bollinger_percent_b_20",
)


def _read_csv(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _number(value: Any) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)).astimezone(UTC)


def _source_revision() -> str:
    path = ROOT / "quant" / "SOURCE_VERSION.md"
    for line in path.read_text(encoding="utf-8").splitlines():
        if "Source commit:" in line:
            return line.split(":", 1)[1].strip()
    return "UNKNOWN"


def _rowwise_status(row: dict[str, Any], *, indicators_required: bool) -> str:
    if str(row.get("feature_instrument_class", "")).upper() == "SPOT":
        return "NON_DERIVATIVE"
    if str(row.get("position_scale_fit_available", "")).lower() != "true":
        return "POSITION_SCALE_MISSING"
    latest = _parse_time(row.get("feature_latest_bar_time"))
    decision = _parse_time(row.get("decision_time"))
    if latest is None or decision is None:
        return "MISSING_MARKET_DATA"
    if latest >= decision:
        return "FUTURE_MARKET_DATA"
    required = REQUIRED_V3_FEATURES if indicators_required else REQUIRED_V2_FEATURES
    if any(_number(row.get(key)) is None for key in required):
        return "WARMUP_INSUFFICIENT"
    if str(row.get("feature_market_data_available", "")).lower() != "true":
        return "MISSING_MARKET_DATA"
    return "PASS"


def _enrich_bitmex(rows: list[dict[str, Any]], *, indicators_required: bool) -> list[dict[str, Any]]:
    revision = _source_revision()
    for row in rows:
        row["source_venue"] = "BITMEX"
        row["source_repository"] = "bwjoke/BTC-Trading-Since-2020"
        row["source_revision"] = revision
        row["source_symbol"] = row.get("symbol", "")
        row["canonical_asset"] = "BTC-PERP" if str(row.get("symbol")) in {"XBTUSD", "XBTM21", "XBTU21"} else str(row.get("symbol"))
        row["raw_current_position_contracts"] = row.get("observed_position_before_contracts", "")
        row["raw_target_position_contracts"] = row.get("observed_target_position_contracts", "")
        row["raw_next_target_position_contracts"] = row.get("label_next_target_position_contracts", "")
        row["row_market_coverage_status"] = _rowwise_status(row, indicators_required=indicators_required)
        row["model_eligible"] = row["row_market_coverage_status"] == "PASS" and str(row.get("label_status")) == "AVAILABLE"
    return rows


def _read_revision_from_import(source_dir: Path) -> str:
    try:
        payload = json.loads((source_dir / "import-manifest.json").read_text(encoding="utf-8"))
        return str(payload.get("source_revision") or DEFAULT_SOURCE_REVISION)
    except (OSError, json.JSONDecodeError):
        return DEFAULT_SOURCE_REVISION


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    for row in rows:
        for key in row:
            if key not in fields:
                fields.append(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["status"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def build(
    *,
    bitmex_path: Path,
    output_path: Path,
    report_path: Path,
    hyperliquid_dir: Path,
    cutoff: datetime | None,
    indicators_required: bool,
) -> dict[str, Any]:
    if not bitmex_path.exists():
        raise FileNotFoundError(bitmex_path)
    bitmex_rows = _enrich_bitmex(_read_csv(bitmex_path), indicators_required=indicators_required)
    hyperliquid_rows: list[dict[str, Any]] = []
    hyperliquid_bars = 0
    hyperliquid_funding = 0
    if hyperliquid_dir.exists():
        hyperliquid_rows, bars, funding = build_hyperliquid_feature_rows(hyperliquid_dir, cutoff=cutoff)
        revision = _read_revision_from_import(hyperliquid_dir)
        for row in hyperliquid_rows:
            row["source_revision"] = revision
            row["model_eligible"] = row.get("row_market_coverage_status") == "PASS" and row.get("label_status") == "AVAILABLE"
        hyperliquid_bars = len(bars)
        hyperliquid_funding = len(funding)
    rows = bitmex_rows + hyperliquid_rows
    rows.sort(key=lambda row: (str(row.get("decision_time")), str(row.get("source_venue")), str(row.get("decision_episode_id"))))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _write_csv(output_path, rows)
    eligible = [row for row in rows if row.get("model_eligible")]
    coverage_rows = [
        {"source_venue": row.get("source_venue"), "source_symbol": row.get("source_symbol"), "symbol": row.get("symbol"), "row_market_coverage_status": row.get("row_market_coverage_status"), "model_eligible": row.get("model_eligible"), "decision_time": row.get("decision_time")}
        for row in rows
    ]
    coverage_path = report_path.with_name("cross_venue_rowwise_coverage.csv")
    _write_csv(coverage_path, coverage_rows)
    report = {
        "report_version": "M15-CROSS-VENUE-DATASET-1.0",
        "status": "PASS",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "output": str(output_path.relative_to(ROOT)),
        "rows": len(rows),
        "eligible_rows": len(eligible),
        "eligible_symbols": sorted({str(row.get("symbol")) for row in eligible}),
        "source_counts": dict(Counter(str(row.get("source_venue")) for row in rows)),
        "coverage_status_counts": dict(Counter(str(row.get("row_market_coverage_status")) for row in rows)),
        "eligible_source_counts": dict(Counter(str(row.get("source_venue")) for row in eligible)),
        "hyperliquid": {"source_repository": DEFAULT_SOURCE_REPOSITORY, "source_revision": _read_revision_from_import(hyperliquid_dir), "feature_bars": hyperliquid_bars, "funding_records": hyperliquid_funding},
        "position_normalization": "raw contract fields retained; walk-forward evaluator fits scales on each training window only",
        "indicator_contract": "m13-v3-cross-asset-indicators" if indicators_required else "m13-v2-cross-asset",
        "cutoff": cutoff.isoformat().replace("+00:00", "Z") if cutoff else None,
        "rowwise_coverage_report": str(coverage_path.relative_to(ROOT)),
    }
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bitmex", type=Path, help="optional BitMEX dataset; defaults according to --contract")
    parser.add_argument("--output", type=Path, help="optional output CSV; defaults according to --contract")
    parser.add_argument("--report", type=Path, help="optional manifest path; defaults according to --contract")
    parser.add_argument("--hyperliquid-dir", type=Path, default=ROOT / "quant" / "data" / "external" / "hyperliquid" / "paul" / DEFAULT_SOURCE_REVISION)
    parser.add_argument("--cutoff", type=lambda value: datetime.fromisoformat(value.replace("Z", "+00:00")), default=datetime(2026, 7, 18, 21, 17, 31, 514000, tzinfo=UTC))
    parser.add_argument("--contract", choices=("v2", "v3"), default="v3", help="market warmup contract used for row eligibility")
    args = parser.parse_args()
    default_bitmex = ROOT / "quant" / "outputs" / ("cross_asset_model_dataset.csv" if args.contract == "v2" else "cross_asset_model_dataset_v3.csv")
    default_output = ROOT / "quant" / "outputs" / f"cross_venue_model_dataset_{args.contract}.csv"
    default_report = ROOT / "quant" / "reports" / f"cross_venue_model_dataset_{args.contract}_manifest.json"
    args.bitmex = (args.bitmex or default_bitmex).resolve()
    args.output = (args.output or default_output).resolve()
    args.report = (args.report or default_report).resolve()
    args.hyperliquid_dir = args.hyperliquid_dir.resolve()
    try:
        result = build(bitmex_path=args.bitmex, output_path=args.output, report_path=args.report, hyperliquid_dir=args.hyperliquid_dir, cutoff=args.cutoff, indicators_required=args.contract == "v3")
    except (FileNotFoundError, OSError, ValueError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "CROSS_VENUE_DATASET_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": result["status"], "rows": result["rows"], "eligible_rows": result["eligible_rows"], "report": str(args.report)}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
