#!/usr/bin/env python3
"""Create a descriptive, causal-input strategy behavior profile.

This report summarizes what the public teacher records did in relation to
already-closed market features.  It is not a classifier and it must not be
read as proof that the trader used any of these indicators.  Labels are used
only for post-hoc description; the output is not a deployable model artifact.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping


ROOT = Path(__file__).resolve().parents[2]
INPUT = ROOT / "quant" / "outputs" / "cross_venue_temporal_dataset_v3.csv"
REPORT = ROOT / "quant" / "reports" / "strategy_behavior_profile_v4.json"
REPORT_MD = ROOT / "quant" / "reports" / "strategy_behavior_profile_v4.md"
PER_SYMBOL = ROOT / "quant" / "reports" / "strategy_behavior_profile_v4_by_symbol.csv"
UTC = timezone.utc
IDLE_ACTIONS = frozenset({"NO_TRADE", "HOLD_LONG", "HOLD_SHORT"})


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        result = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (result if result.tzinfo else result.replace(tzinfo=UTC)).astimezone(UTC)


def bucket_rsi(value: Any) -> str:
    parsed = number(value)
    if parsed is None:
        return "MISSING"
    if parsed < 30:
        return "<30_OVERSOLD"
    if parsed < 45:
        return "30-45"
    if parsed < 55:
        return "45-55_NEUTRAL"
    if parsed < 70:
        return "55-70"
    return ">=70_OVERBOUGHT"


def bucket_macd(value: Any) -> str:
    parsed = number(value)
    if parsed is None:
        return "MISSING"
    if parsed < 0:
        return "NEGATIVE"
    return "NONNEGATIVE"


def bucket_bollinger(value: Any) -> str:
    parsed = number(value)
    if parsed is None:
        return "MISSING"
    if parsed < 0:
        return "<0_BELOW_LOWER"
    if parsed < 0.2:
        return "0-0.2_LOWER_ZONE"
    if parsed < 0.8:
        return "0.2-0.8_MIDDLE"
    if parsed <= 1:
        return "0.8-1_UPPER_ZONE"
    return ">1_ABOVE_UPPER"


def bucket_exposure(value: Any) -> str:
    parsed = number(value)
    if parsed is None or abs(parsed) <= 1e-12:
        return "FLAT_OR_MISSING"
    return "LONG" if parsed > 0 else "SHORT"


def bucket_return(value: Any) -> str:
    parsed = number(value)
    if parsed is None:
        return "MISSING"
    if parsed < -1e-12:
        return "NEGATIVE"
    if parsed > 1e-12:
        return "POSITIVE"
    return "ZERO"


def _empty_stats() -> dict[str, Any]:
    return {
        "rows": 0,
        "action_counts": Counter(),
        "target_sum": 0.0,
        "target_abs_sum": 0.0,
        "target_values": [],
        "non_idle_rows": 0,
    }


def _observe(stats: dict[str, Any], action: str, target: float | None) -> None:
    stats["rows"] += 1
    stats["action_counts"][action] += 1
    if action not in IDLE_ACTIONS:
        stats["non_idle_rows"] += 1
    if target is not None:
        stats["target_sum"] += target
        stats["target_abs_sum"] += abs(target)
        stats["target_values"].append(target)


def _finalize_stats(stats: Mapping[str, Any]) -> dict[str, Any]:
    rows = int(stats["rows"])
    values = sorted(float(value) for value in stats["target_values"])
    p95 = values[min(len(values) - 1, int(len(values) * 0.95))] if values else None
    return {
        "rows": rows,
        "non_idle_rows": int(stats["non_idle_rows"]),
        "non_idle_rate": (int(stats["non_idle_rows"]) / rows) if rows else None,
        "action_counts": dict(sorted(stats["action_counts"].items())),
        "target_mean": (float(stats["target_sum"]) / len(values)) if values else None,
        "target_abs_mean": (float(stats["target_abs_sum"]) / len(values)) if values else None,
        "target_abs_p95": abs(p95) if p95 is not None else None,
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _rank_lifts(table: Mapping[str, Mapping[str, Any]], base: Mapping[str, Any], *, limit: int = 20) -> list[dict[str, Any]]:
    base_rows = int(base["rows"])
    base_counts = base["action_counts"]
    candidates: list[dict[str, Any]] = []
    for bucket, stats in table.items():
        rows = int(stats["rows"])
        if rows < 50:
            continue
        for action, count in stats["action_counts"].items():
            if action in IDLE_ACTIONS or not base_rows or not base_counts.get(action):
                continue
            rate = count / rows
            baseline = base_counts[action] / base_rows
            candidates.append({
                "bucket": bucket,
                "action": action,
                "support": count,
                "bucket_rows": rows,
                "action_rate": rate,
                "baseline_rate": baseline,
                "lift": rate / baseline if baseline else None,
            })
    return sorted(candidates, key=lambda row: (-float(row["lift"] or 0), -int(row["support"]), str(row["bucket"]), str(row["action"])))[:limit]


def analyze_rows(rows: Iterable[Mapping[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    base = _empty_stats()
    dimensions: dict[str, defaultdict[str, dict[str, Any]]] = {
        "rsi14": defaultdict(_empty_stats),
        "macd_histogram": defaultdict(_empty_stats),
        "bollinger_percent_b": defaultdict(_empty_stats),
        "market_regime": defaultdict(_empty_stats),
        "current_exposure": defaultdict(_empty_stats),
        "return_24bar": defaultdict(_empty_stats),
    }
    by_venue: defaultdict[str, dict[str, Any]] = defaultdict(_empty_stats)
    by_symbol: defaultdict[tuple[str, str], dict[str, Any]] = defaultdict(_empty_stats)
    action_times: defaultdict[tuple[str, str], list[datetime]] = defaultdict(list)
    duration_values: list[float] = []
    eligible_rows = 0
    total_rows = 0
    first_time: datetime | None = None
    last_time: datetime | None = None
    for original in rows:
        row = dict(original)
        total_rows += 1
        when = parse_time(row.get("decision_time"))
        if when is not None:
            first_time = when if first_time is None or when < first_time else first_time
            last_time = when if last_time is None or when > last_time else last_time
        action = str(row.get("label_next_action") or "NO_TRADE")
        target = number(row.get("label_next_target_exposure"))
        venue = str(row.get("source_venue") or "UNKNOWN")
        symbol = str(row.get("canonical_asset") or row.get("feature_symbol") or row.get("symbol") or "UNKNOWN")
        is_eligible = str(row.get("model_eligible") or "").lower() == "true" or str(row.get("row_market_coverage_status") or row.get("market_coverage_status") or "") == "PASS"
        if not is_eligible:
            continue
        eligible_rows += 1
        _observe(base, action, target)
        _observe(by_venue[venue], action, target)
        _observe(by_symbol[(venue, symbol)], action, target)
        values = {
            "rsi14": bucket_rsi(row.get("feature_rsi_14")),
            "macd_histogram": bucket_macd(row.get("feature_macd_histogram")),
            "bollinger_percent_b": bucket_bollinger(row.get("feature_bollinger_percent_b_20")),
            "market_regime": str(row.get("feature_market_regime") or "UNKNOWN"),
            "current_exposure": bucket_exposure(row.get("feature_current_normalized_exposure")),
            "return_24bar": bucket_return(row.get("feature_return_24bar")),
        }
        for name, bucket in values.items():
            _observe(dimensions[name][bucket], action, target)
        duration = number(row.get("feature_cycle_duration_seconds"))
        if duration is not None and duration >= 0:
            duration_values.append(duration)
        if action not in IDLE_ACTIONS and when is not None:
            action_times[(venue, symbol)].append(when)

    sequence_intervals: list[float] = []
    for times in action_times.values():
        times.sort()
        sequence_intervals.extend((right - left).total_seconds() / 3600 for left, right in zip(times, times[1:]))
    summary = {
        "report_version": "STRATEGY-BEHAVIOR-PROFILE-V4",
        "total_rows_seen": total_rows,
        "eligible_rows": eligible_rows,
        "first_decision_time": first_time.isoformat().replace("+00:00", "Z") if first_time else None,
        "last_decision_time": last_time.isoformat().replace("+00:00", "Z") if last_time else None,
        "overall": _finalize_stats(base),
        "by_venue": {key: _finalize_stats(value) for key, value in sorted(by_venue.items())},
        "by_dimension": {
            name: {
                "buckets": {bucket: _finalize_stats(value) for bucket, value in sorted(table.items())},
                "top_action_lifts": _rank_lifts(table, base),
            }
            for name, table in dimensions.items()
        },
        "holding_period_observed": {
            "rows": len(duration_values),
            "mean_hours": sum(duration_values) / len(duration_values) / 3600 if duration_values else None,
            "p95_hours": sorted(duration_values)[min(len(duration_values) - 1, int(len(duration_values) * 0.95))] / 3600 if duration_values else None,
        },
        "action_interval_observed": {
            "series_count": len(action_times),
            "interval_count": len(sequence_intervals),
            "mean_hours": sum(sequence_intervals) / len(sequence_intervals) if sequence_intervals else None,
            "p95_hours": sorted(sequence_intervals)[min(len(sequence_intervals) - 1, int(len(sequence_intervals) * 0.95))] if sequence_intervals else None,
        },
        "interpretation_boundary": "Post-hoc association from causal, already-closed inputs; indicators are model-input candidates and are not evidence of the original trader's private decision rules.",
    }
    symbols = []
    for (venue, symbol), stats in sorted(by_symbol.items()):
        finalized = _finalize_stats(stats)
        symbols.append({"source_venue": venue, "canonical_asset": symbol, **finalized})
    return summary, symbols


def _markdown(summary: Mapping[str, Any]) -> str:
    overall = summary["overall"]
    lines = [
        "# Strategy Behavior Profile V4",
        "",
        "> This is a descriptive profile of public trade records. It is not proof of the original trader's indicators, a causal strategy explanation, a profitability claim, or a deployable model.",
        "",
        "## Data scope",
        "",
        f"- Rows seen: `{summary['total_rows_seen']}`; eligible rows with complete market context: `{summary['eligible_rows']}`.",
        f"- Decision range: `{summary['first_decision_time']}` to `{summary['last_decision_time']}`.",
        f"- Non-idle observed action rate: `{float(overall['non_idle_rate'] or 0):.2%}`.",
        "",
        "## What the record actually shows",
        "",
        "| action | count | share of eligible rows |",
        "|---|---:|---:|",
    ]
    for action, count in overall["action_counts"].items():
        lines.append(f"| `{action}` | {count} | {count / overall['rows']:.2%} |" if overall["rows"] else f"| `{action}` | {count} | — |")
    lines += [
        "",
        "## Cross-venue observation",
        "",
        "| venue | rows | non-idle rate | target abs mean |",
        "|---|---:|---:|---:|",
    ]
    for venue, stats in summary["by_venue"].items():
        target_mean = "—" if stats["target_abs_mean"] is None else f"{float(stats['target_abs_mean']):.6f}"
        lines.append(f"| `{venue}` | {stats['rows']} | {float(stats['non_idle_rate'] or 0):.2%} | {target_mean} |")
    lines += [
        "",
        "## Strongest observed associations",
        "",
        "Lift means action rate in the bucket divided by its overall eligible-row rate. It is descriptive, can be confounded by position state and time, and is not a trading rule.",
        "",
    ]
    for dimension, details in summary["by_dimension"].items():
        lines.append(f"### {dimension}")
        lines.append("")
        lifts = details["top_action_lifts"][:5]
        if not lifts:
            lines.append("- No bucket reached the minimum support threshold.")
        else:
            for item in lifts:
                lines.append(f"- `{item['bucket']}` → `{item['action']}`: rate `{item['action_rate']:.2%}`, baseline `{item['baseline_rate']:.2%}`, lift `{item['lift']:.2f}x`, support `{item['support']}`.")
        lines.append("")
    lines += [
        "## Holding and action timing",
        "",
        f"- Observed cycle-duration mean / P95: `{summary['holding_period_observed']['mean_hours']}` / `{summary['holding_period_observed']['p95_hours']}` hours.",
        f"- Same venue/instrument action-interval mean / P95: `{summary['action_interval_observed']['mean_hours']}` / `{summary['action_interval_observed']['p95_hours']}` hours.",
        "",
        "## Strategy interpretation boundary",
        "",
        "The defensible conclusion is a stateful, position-adjustment behavior pattern: most clock periods are idle, and non-idle actions are heavily conditioned by current exposure, instrument, and observed market context. The data does not identify a unique RSI/MACD rule or prove that indicators caused any action. The autonomous candidates remain separate and must pass strict walk-forward validation before Demo promotion.",
        "",
        "## Safety",
        "",
        "No credentials, private endpoint, mainnet connection, or order was used. Raw source CSV/JSON files remain read-only.",
    ]
    return "\n".join(lines) + "\n"


def build(*, input_path: Path = INPUT, report_path: Path = REPORT, markdown_path: Path = REPORT_MD, per_symbol_path: Path = PER_SYMBOL) -> dict[str, Any]:
    with input_path.open("r", encoding="utf-8", newline="") as handle:
        summary, symbols = analyze_rows(csv.DictReader(handle))
    summary["input"] = str(input_path.relative_to(ROOT))
    summary["input_sha256"] = _sha256(input_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    markdown_path.write_text(_markdown(summary), encoding="utf-8")
    fields = ["source_venue", "canonical_asset", "rows", "non_idle_rows", "non_idle_rate", "action_counts", "target_mean", "target_abs_mean", "target_abs_p95"]
    with per_symbol_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in symbols:
            output = dict(row)
            output["action_counts"] = json.dumps(output["action_counts"], ensure_ascii=False, sort_keys=True)
            writer.writerow(output)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=INPUT)
    args = parser.parse_args()
    try:
        summary = build(input_path=args.input.resolve())
    except (OSError, ValueError, KeyError) as error:
        print(json.dumps({"status": "BLOCKED", "error_code": "STRATEGY_PROFILE_FAILED", "message": str(error)}, ensure_ascii=False))
        return 2
    print(json.dumps({"status": "READY_WITH_BOUNDARY", "report": str(REPORT), "eligible_rows": summary["eligible_rows"], "action_counts": summary["overall"]["action_counts"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
