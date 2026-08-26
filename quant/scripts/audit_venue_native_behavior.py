#!/usr/bin/env python3
"""Run a diagnostic walk-forward independently inside each venue.

The same trader can use the same behavioral intent while contract scale,
funding, tick size, liquidity, and execution semantics differ by venue. This
report therefore fits and replays each venue separately. It is deliberately
diagnostic-only and never promotes a model or changes the active Demo model.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
for path in (ROOT, SRC, ROOT / "quant" / "scripts"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from audit_cross_venue_probability_calibrated_stability import (  # noqa: E402
    DATASET_TEMPORAL,
    FEE_RATE,
    _behavior_metrics,
    _load_bars,
    _per_symbol_rows,
    _rates,
    _replay_portfolio,
    _read_temporal,
)
from audit_cross_venue_state_robust_model import _fit_candidate, _predictions  # noqa: E402
from quant_bot.strategy.feature_contract import strategy_input_from_row  # noqa: E402
from research.autonomous_replay import normalize_window_rows, roll_forward_predictions  # noqa: E402


VERSION = "behavioral-distillation-v4.1-venue-native-calibration"
REPORT = ROOT / "quant" / "reports" / "venue_native_behavior_audit.json"
REPORT_MD = ROOT / "quant" / "reports" / "venue_native_behavior_audit.md"
PER_SYMBOL = ROOT / "quant" / "reports" / "venue_native_behavior_by_symbol.csv"
UTC = timezone.utc


def chronological_split(rows: list[dict[str, Any]], train_fraction: float = 0.8) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Split one venue chronologically, never randomly."""

    ordered = sorted((dict(row) for row in rows), key=lambda row: str(row.get("decision_time")))
    if len(ordered) < 2:
        return ordered, []
    cut = max(1, min(len(ordered) - 1, int(len(ordered) * train_fraction)))
    return ordered[:cut], ordered[cut:]


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


def _venue_result(venue: str, rows: list[dict[str, Any]], bars: Mapping[str, Any], opens: Mapping[str, Any]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    train_raw, test_raw = chronological_split(rows)
    train, scales = normalize_window_rows(train_raw, train_raw)
    test, _ = normalize_window_rows(test_raw, train_raw)
    train = [row for row in train if str(row.get("model_eligible")).lower() == "true"]
    test = [row for row in test if str(row.get("model_eligible")).lower() == "true"]
    if not train or not test:
        return {
            "venue": venue,
            "status": "INSUFFICIENT_NATIVE_COVERAGE",
            "train_rows": len(train),
            "test_rows": len(test),
            "active_model_unchanged": True,
        }, []
    model, stages = _fit_candidate(train, scales)
    model.version = VERSION
    model.timing_model.version = f"{VERSION}:timing"
    model.action_model.version = f"{VERSION}:action"
    conditional = _predictions(model, test)
    autonomous = roll_forward_predictions(model, test, scales, market_bar_opens=opens, include_state_overrides=False)
    first = datetime.fromisoformat(str(test[0]["decision_time"]).replace("Z", "+00:00")).astimezone(UTC)
    last = datetime.fromisoformat(str(test[-1]["decision_time"]).replace("Z", "+00:00")).astimezone(UTC) + timedelta(hours=1)
    replay = _replay_portfolio(autonomous["merged_events"], bars, start=first, end=last, fee_rate=FEE_RATE)
    behavior = {
        "conditional": {**_behavior_metrics(test, conditional), **_rates(test, conditional)},
        "strict_autonomous": {**_behavior_metrics(test, autonomous["row_predictions"]), **_rates(test, autonomous["row_predictions"])},
    }
    result = {
        "venue": venue,
        "status": "DIAGNOSTIC_ONLY",
        "candidate_model_version": VERSION,
        "active_model_unchanged": True,
        "train_rows": len(train),
        "test_rows": len(test),
        "train_first_time": train[0].get("decision_time"),
        "train_last_time": train[-1].get("decision_time"),
        "test_first_time": test[0].get("decision_time"),
        "test_last_time": test[-1].get("decision_time"),
        "nested_stages": stages,
        "behavior": behavior,
        "performance": {key: value for key, value in replay.items() if key != "per_symbol"},
        "teacher_state_fields_consumed": autonomous["teacher_state_fields_consumed"],
        "promotion_allowed": False,
    }
    per_symbol = _per_symbol_rows(test, autonomous["row_predictions"], replay, f"NATIVE_{venue}")
    return result, per_symbol


def build(*, dataset_path: Path = DATASET_TEMPORAL, report_path: Path = REPORT, markdown_path: Path = REPORT_MD, per_symbol_path: Path = PER_SYMBOL) -> dict[str, Any]:
    rows = _read_temporal(dataset_path)
    bars, opens = _load_bars()
    venues = sorted({str(row.get("source_venue") or "UNKNOWN") for row in rows})
    results: list[dict[str, Any]] = []
    per_symbol: list[dict[str, Any]] = []
    for venue in venues:
        venue_rows = [row for row in rows if str(row.get("source_venue") or "UNKNOWN") == venue]
        result, details = _venue_result(venue, venue_rows, bars, opens)
        results.append(result)
        per_symbol.extend(details)
    output = {
        "report_version": "M15-VENUE-NATIVE-BEHAVIOR-AUDIT-1.0",
        "status": "DIAGNOSTIC_ONLY",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "candidate_model_version": VERSION,
        "dataset": str(dataset_path.relative_to(ROOT)),
        "dataset_rows": len(rows),
        "venue_results": results,
        "promotion_allowed": False,
        "conclusion": "Venue-native calibration is descriptive evidence about platform-specific generalization. It cannot replace shared global walk-forward validation or prove exact strategy recovery.",
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(output, indent=2, ensure_ascii=False, default=str) + "\n", encoding="utf-8")
    _write_csv(per_symbol_path, per_symbol)
    lines = [
        "# Venue-Native Behavior Audit",
        "",
        "> Diagnostic only. Each venue is split chronologically and calibrated independently. No result authorizes a Demo model switch or order.",
        "",
        "| venue | train rows | test rows | autonomous net return | profit factor | autonomous action rate |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for result in results:
        behavior = result.get("behavior", {}).get("strict_autonomous", {})
        performance = result.get("performance", {})
        net = performance.get("net_return")
        pf = performance.get("profit_factor")
        rate = 1.0 - float(behavior.get("predicted_no_trade_rate", 1.0))
        fmt = lambda value: "—" if value is None else f"{float(value):.6f}"
        lines.append(f"| `{result['venue']}` | {result.get('train_rows', 0)} | {result.get('test_rows', 0)} | {fmt(net)} | {fmt(pf)} | {rate:.2%} |")
    lines += [
        "",
        "## Interpretation",
        "",
        "A positive native holdout is not evidence of cross-venue generalization; a negative one does not prove the trader changed strategy. Contract scale, funding, liquidity and market coverage are venue-specific. The shared model remains blocked until global causal and costed gates pass.",
        "",
        "## Boundary",
        "",
        "No credentials, private endpoint, mainnet connection, or order was used. Raw CSV/JSON files remain read-only.",
    ]
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, default=DATASET_TEMPORAL)
    args = parser.parse_args()
    try:
        result = build(dataset_path=args.dataset.resolve())
    except (FileNotFoundError, OSError, ValueError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "VENUE_NATIVE_AUDIT_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": result["status"], "report": str(REPORT), "venues": [item["venue"] for item in result["venue_results"]]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
