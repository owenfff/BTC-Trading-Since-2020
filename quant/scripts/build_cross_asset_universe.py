#!/usr/bin/env python3
"""Build the all-symbol behavior universe and public market coverage cache."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bitmex_replay.io_utils import hash_files  # noqa: E402
from cross_asset.market import build_cross_asset_market  # noqa: E402
from cross_asset.universe import (  # noqa: E402
    fit_position_scales,
    load_decision_rows,
    load_instrument_metadata,
    split_by_global_time,
)


PROTECTED_FILES = [
    "api-v1-execution-tradeHistory.csv",
    "api-v1-order.csv",
    "api-v1-user-walletHistory.csv",
    "api-v1-position.snapshot.csv",
    "api-v1-user-wallet.snapshot-all.csv",
    "api-v1-user-margin.snapshot-all.csv",
    "api-v1-instrument.all.csv",
    "api-v1-wallet-assets.csv",
    "derived-equity-curve.csv",
    "manifest.json",
]


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def build(*, skip_market: bool = False) -> dict[str, object]:
    outputs = ROOT / "quant" / "outputs"
    reports = ROOT / "quant" / "reports"
    before = hash_files(ROOT, PROTECTED_FILES)
    decisions = split_by_global_time(load_decision_rows(outputs / "decision_episodes.csv"))
    metadata = load_instrument_metadata(
        outputs / "execution_spec_mapping.parquet",
        outputs / "instrument_terms_temporal_audit.csv",
    )
    scales = fit_position_scales(decisions)
    grouped: dict[str, list[dict[str, object]]] = {}
    for row in decisions:
        grouped.setdefault(str(row["symbol"]), []).append(row)
    ranges = {
        symbol: (min(row["_decision_dt"] for row in rows), max(row["_decision_dt"] for row in rows))
        for symbol, rows in grouped.items()
    }
    coverage = None if skip_market else build_cross_asset_market(ROOT, ranges)
    coverage_by_symbol = {item["symbol"]: item for item in (coverage or {}).get("coverage", [])}
    coverage_summary = None
    if coverage is not None:
        coverage_summary = {key: value for key, value in coverage.items() if key != "coverage"}
        coverage_summary["coverage"] = [
            {key: value for key, value in item.items() if key != "market_lineage"}
            for item in coverage.get("coverage", [])
        ]

    inventory: list[dict[str, object]] = []
    for symbol, rows in sorted(grouped.items()):
        item = metadata.get(symbol, {})
        market = coverage_by_symbol.get(symbol, {})
        inventory.append({
            "symbol": symbol,
            "decision_row_count": len(rows),
            "order_row_count": sum(row.get("decision_type") == "ORDER" for row in rows),
            "synthetic_row_count": sum(str(row.get("synthetic_negative_sample", "")).lower() == "true" for row in rows),
            "first_decision_time_utc": min(row["_decision_dt"] for row in rows).isoformat().replace("+00:00", "Z"),
            "last_decision_time_utc": max(row["_decision_dt"] for row in rows).isoformat().replace("+00:00", "Z"),
            "instrument_class": item.get("instrument_class", "UNKNOWN"),
            "payout_model": item.get("payout_model", "UNKNOWN"),
            "quote_currency": item.get("quote_currency", "UNKNOWN"),
            "settlement_currency": item.get("settlement_currency", "UNKNOWN"),
            "multiplier_major": item.get("multiplier_major", ""),
            "resolved_lot_size": item.get("resolved_lot_size", ""),
            "terms_resolution_status": item.get("terms_resolution_status", "UNKNOWN"),
            "train_position_scale_contracts": scales.get(symbol, 1.0),
            "market_coverage_status": market.get("coverage_status", "NOT_RUN"),
            "market_bar_count": market.get("row_count", 0),
            "market_grid_gap_count": market.get("hour_grid_gap_count", 0),
        })

    after = hash_files(ROOT, PROTECTED_FILES)
    changed = [name for name in PROTECTED_FILES if before.get(name) != after.get(name)]
    report = {
        "report_version": "M13-CROSS-ASSET-UNIVERSE-1.0",
        "analysis_commit": _git_head(),
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "decision_row_count": len(decisions),
        "symbol_count": len(inventory),
        "symbols": [row["symbol"] for row in inventory],
        "instrument_class_counts": dict(Counter(str(row["instrument_class"]) for row in inventory)),
        "payout_model_counts": dict(Counter(str(row["payout_model"]) for row in inventory)),
        "settlement_currency_counts": dict(Counter(str(row["settlement_currency"]) for row in inventory)),
        "total_synthetic_rows": sum(int(row["synthetic_row_count"]) for row in inventory),
        "market_coverage": coverage_summary,
        "position_scales_fit_on": "TRAIN rows only using global chronological 70/15/15 split",
        "position_scales": scales,
        "raw_account_inputs_unchanged": not changed,
        "changed_protected_files": changed,
        "spot_policy": "Spot rows remain auditable but are not mixed with derivative position semantics without explicit instrument-type handling.",
        "public_data_policy": "Only public no-key data; no synthetic market history; coverage failures remain explicit.",
    }
    reports.mkdir(parents=True, exist_ok=True)
    with (reports / "cross_asset_universe.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(inventory[0]) if inventory else ["symbol"])
        writer.writeheader()
        writer.writerows(inventory)
    (reports / "cross_asset_universe.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    lines = [
        "# Cross-Asset Behavior Universe",
        "",
        f"- symbols: `{len(inventory)}`",
        f"- decision rows: `{len(decisions)}`",
        f"- analysis commit: `{report['analysis_commit']}`",
        f"- strategy fidelity: **{report['strategy_fidelity']}**",
        f"- raw account inputs unchanged: `{report['raw_account_inputs_unchanged']}`",
        "",
        "The inventory includes every symbol present in the behavior decision export. Position scales are fitted from chronological TRAIN rows only. Spot and derivative semantics remain explicitly separated.",
        "",
        "Market coverage is sourced from public, no-key BitMEX market endpoints at hourly resolution. No synthetic bars are generated; symbols with insufficient or failed coverage remain outside model eligibility and are listed in the JSON/CSV reports.",
    ]
    (reports / "cross_asset_universe.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-market", action="store_true", help="Only build the symbol inventory; do not download public market data")
    args = parser.parse_args()
    report = build(skip_market=args.skip_market)
    print(json.dumps({
        "status": "PASS" if report["raw_account_inputs_unchanged"] else "FAIL_PROTECTED_INPUT_CHANGED",
        "symbols": report["symbol_count"],
        "decision_rows": report["decision_row_count"],
        "market_coverage_status": (report.get("market_coverage") or {}).get("coverage_status", "NOT_RUN"),
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
