#!/usr/bin/env python3
"""Build the leakage-safe BTC-first feature/label dataset.

This package creates one chronological row per XBTUSD decision, including the
existing synthetic HOLD/NO_TRADE observations.  Features are past-only; next
decision fields are labels and are never used to construct features.
"""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from features.account_features import build_account_features  # noqa: E402
from features.market_features import build_market_features, iso_utc, load_market_context, parse_utc  # noqa: E402
from labels.next_decision import build_next_decision_labels  # noqa: E402
from bitmex_replay.io_utils import hash_files  # noqa: E402
from bitmex_replay.reconciliation import write_csv, write_parquet  # noqa: E402


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


def git_value(args: list[str]) -> str:
    try:
        return subprocess.check_output(["git", *args], cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip()
    except (OSError, subprocess.CalledProcessError):
        return ""


def source_commit() -> str:
    path = ROOT / "quant" / "SOURCE_VERSION.md"
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lower().startswith("- source commit:"):
            return line.split(":", 1)[1].strip().strip("`")
    return ""


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fieldnames(rows: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                names.append(key)
    return names or ["empty"]


def _read_csv(path: Path, *, symbol: str | None = None) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if symbol is not None:
        rows = [row for row in rows if str(row.get("symbol", "")).upper() == symbol.upper()]
    return rows


def _write_large(rows: list[dict[str, Any]], parquet_path: Path) -> dict[str, Any]:
    try:
        write_parquet(rows, parquet_path)
        return {"format": "parquet", "path": str(parquet_path.relative_to(ROOT)), "row_count": len(rows)}
    except (ImportError, RuntimeError):
        fallback = parquet_path.with_suffix(".csv")
        write_csv(rows, fallback, _fieldnames(rows))
        return {
            "format": "csv_fallback_no_parquet_engine",
            "path": str(fallback.relative_to(ROOT)),
            "requested_path": str(parquet_path.relative_to(ROOT)),
            "row_count": len(rows),
        }


def _jsonable(value: Any) -> Any:
    if isinstance(value, datetime):
        return iso_utc(value)
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_jsonable(item) for item in value]
    return value


def _split_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ordered = sorted(rows, key=lambda row: parse_utc(row["decision_time"]) or datetime.max.replace(tzinfo=timezone.utc))
    total = len(ordered)
    train_end = max(1, int(total * 0.70))
    validation_end = max(train_end + 1, int(total * 0.85))
    for index, row in enumerate(ordered):
        row["dataset_split"] = "TRAIN" if index < train_end else ("VALIDATION" if index < validation_end else "TEST")
    split_rows: list[dict[str, Any]] = []
    for split in ("TRAIN", "VALIDATION", "TEST"):
        subset = [row for row in ordered if row["dataset_split"] == split]
        split_rows.append({
            "split": split,
            "row_count": len(subset),
            "first_decision_time_utc": subset[0]["decision_time"] if subset else "",
            "last_decision_time_utc": subset[-1]["decision_time"] if subset else "",
            "synthetic_row_count": sum(bool(row.get("synthetic_negative_sample")) for row in subset),
            "no_trade_or_hold_count": sum(row.get("observed_action") in {"NO_TRADE", "HOLD_LONG", "HOLD_SHORT"} for row in subset),
        })
    return ordered, split_rows


def _label_distribution(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    counts: Counter[tuple[str, str]] = Counter()
    for row in rows:
        counts[(str(row.get("label_next_action", "")), str(row.get("label_next_position_delta_bucket", "")))] += 1
    return [{"next_action": action, "next_position_delta_bucket": bucket, "row_count": count} for (action, bucket), count in sorted(counts.items())]


def _leakage_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    future_bar = 0
    future_funding = 0
    future_history = 0
    future_label = 0
    invalid_feature_time = 0
    for row in rows:
        decision_time = parse_utc(row.get("decision_time"))
        if decision_time is None:
            invalid_feature_time += 1
            continue
        feature_time = parse_utc(row.get("feature_latest_bar_time"))
        funding_time = parse_utc(row.get("feature_funding_source_time"))
        history_time = parse_utc(row.get("feature_history_last_decision_time"))
        label_time = parse_utc(row.get("label_next_decision_time"))
        future_bar += int(feature_time is not None and feature_time >= decision_time)
        future_funding += int(funding_time is not None and funding_time > decision_time)
        future_history += int(history_time is not None and history_time >= decision_time)
        future_label += int(label_time is not None and label_time <= decision_time)
    blockers = {
        "future_bar_observation_count": future_bar,
        "future_funding_observation_count": future_funding,
        "future_history_observation_count": future_history,
        "non_future_label_violation_count": future_label,
        "invalid_decision_time_count": invalid_feature_time,
    }
    return {"status": "PASS" if not any(blockers.values()) else "BLOCKED", "checks": blockers, "feature_rule": "bar_end_time < decision_time; funding_source_time <= decision_time; history_time < decision_time", "label_rule": "next_decision_time > decision_time; same-timestamp ties are skipped"}


def _write_feature_dictionary(path: Path) -> None:
    path.write_text("""# Feature Dictionary\n\nAll feature columns are computed at decision time `t` using only observations with timestamps strictly before `t`. No train/test normalization statistics are fitted in M4.\n\n## Market features\n\n| feature | definition | missing rule |\n| --- | --- | --- |\n| `feature_return_{1,3,6,12,24,72}bar` | Close-to-close return over prior closed 5m bars | null if the complete UTC grid window is unavailable |\n| `feature_realized_volatility_72bar` | Population standard deviation of prior 72 log returns | null if any child interval is incomplete |\n| `feature_atr_14bar` | 14-bar true-range average | null if prior close/child bar is missing |\n| `feature_volume_change_1bar` | Latest closed volume versus prior closed volume | null if prior volume is zero/missing |\n| `feature_volume_percentile_72bar` | Rank of latest volume within prior 72 closed bars | null if the window is incomplete |\n| `feature_ma_distance_24bar` | Close divided by prior 24-bar mean minus one | null if the window is incomplete |\n| `feature_trend_slope_24bar` | OLS slope of log close over prior 24 bars | null if the window is incomplete |\n| `feature_distance_rolling_high_72bar` | Close divided by prior 72-bar high minus one | null if the window is incomplete |\n| `feature_distance_rolling_low_72bar` | Close divided by prior 72-bar low minus one | null if the window is incomplete |\n| `feature_funding_rate` | Funding observation attached as-of to the latest prior bar | null if funding is unavailable |\n| `feature_mark_index_basis` | Mark/index minus one | null and `feature_mark_index_missing=1` because historical series is unavailable |\n| `feature_market_regime` | Deterministic trend/range bucket from past slope and MA distance | `UNKNOWN` until the windows are complete |\n| time features | UTC time-of-day and day-of-week encodings | always known from decision timestamp |\n\n## Account and behavior features\n\nThese use prior decisions, prior closed cycles, prior fills, and the position immediately before the decision. `feature_current_normalized_exposure` is contract quantity divided by the fixed XBTUSD contract scale of 10,000,000; it is not a BTC or USD notional claim.\n\n`feature_fee_accumulation_raw` uses prior `execComm_raw` values; `feature_funding_accumulation_raw` uses prior closed-cycle funding values. Current decision action/order confidence is not used as a feature; the previous strictly earlier decision is used instead.\n""", encoding="utf-8")


def _write_label_dictionary(path: Path) -> None:
    path.write_text("""# Label Dictionary\n\nLabels are future outcomes and are kept separate from feature construction.\n\n| label | definition |\n| --- | --- |\n| `label_next_target_exposure` | Next strictly later decision's target contract position divided by 10,000,000 |\n| `label_next_action` | Next strictly later decision action, including `NO_TRADE` and `HOLD_*` |\n| `label_next_position_delta_bucket` | Next position delta: `ZERO`, `SMALL` (<=1% scale), `MEDIUM` (<=10%), or `LARGE` |\n| `label_time_to_next_action_seconds` | Seconds until the next strictly later decision |\n| `label_status` | `AVAILABLE`, `NO_LATER_DECISION`, or `SAME_TIMESTAMP_TIE_ONLY` |\n\nRows with no later strictly timed decision retain null labels; same-timestamp order ties are not treated as future labels.\n""", encoding="utf-8")


def _write_leakage_report(path: Path, audit: dict[str, Any], summary: dict[str, Any]) -> None:
    checks = audit["checks"]
    lines = [
        "# Leakage Audit",
        "",
        f"- status: **{audit['status']}**",
        f"- analysis commit: `{summary['analysis_commit']}`",
        f"- rows audited: `{summary['row_count']}`",
        "",
        "## Checks",
        "",
        "| check | violations |",
        "| --- | ---: |",
    ]
    for key, value in checks.items():
        lines.append(f"| {key} | {value} |")
    lines.extend([
        "",
        "Feature rule: `bar_end_time < decision_time`; funding source timestamps must be `<= decision_time`; history timestamps must be strictly earlier. Labels use the next strictly later decision and skip same-timestamp ties.",
        "",
        "No future high/low, future cycle PnL, future action, or test-period normalization statistic is used as a feature. Historical mark/index context is missing by source limitation and is represented by an explicit missingness flag.",
        "",
        f"- dataset split: `{summary['split_policy']}`",
        f"- raw account inputs unchanged: `{summary['raw_inputs_unchanged']}`",
    ])
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _write_no_trade_audit(path: Path, rows: list[dict[str, Any]]) -> None:
    synthetic = [row for row in rows if row.get("synthetic_negative_sample")]
    no_trade = [row for row in rows if row.get("observed_action") in {"NO_TRADE", "HOLD_LONG", "HOLD_SHORT"}]
    path.write_text(f"""# NO_TRADE / HOLD Sampling Audit\n\n- total BTC decision rows: `{len(rows)}`\n- synthetic daily rows: `{len(synthetic)}`\n- observed NO_TRADE/HOLD rows: `{len(no_trade)}`\n- synthetic action distribution: `{dict(Counter(str(row.get('observed_action', '')) for row in synthetic))}`\n- time order: **chronological; no random shuffle**\n\nSynthetic rows come from the frozen behavior dataset and are retained as explicit carry/no-trade observations. They are not silently treated as real fills.\n""", encoding="utf-8")


def build(root: Path = ROOT) -> dict[str, Any]:
    root = Path(root)
    reports = root / "quant" / "reports"
    outputs = root / "quant" / "outputs"
    reports.mkdir(parents=True, exist_ok=True)
    outputs.mkdir(parents=True, exist_ok=True)
    before = hash_files(root, PROTECTED_FILES)
    decisions = _read_csv(outputs / "decision_episodes.csv", symbol="XBTUSD")
    decisions = [row for row in decisions if str(row.get("is_btc_first_scope", "")).lower() == "true"]
    decisions.sort(key=lambda row: (parse_utc(row.get("decision_time")) or datetime.max.replace(tzinfo=timezone.utc), str(row.get("decision_episode_id", ""))))
    cycles = _read_csv(outputs / "trade_cycles.csv", symbol="XBTUSD")
    actions = _read_csv(outputs / "trade_actions.csv", symbol="XBTUSD")
    orders = _read_csv(outputs / "order_episodes.csv", symbol="XBTUSD")
    market = load_market_context(outputs / "market_context.csv", symbol="XBTUSD")
    market_times = [row["timestamp"] for row in market]
    account_features = build_account_features(decisions, cycles=cycles, trade_actions=actions, order_episodes=orders)
    market_features = [{"decision_episode_id": row["decision_episode_id"], **build_market_features(market, parse_utc(row["decision_time"]), timestamps=market_times)} for row in decisions if parse_utc(row.get("decision_time")) is not None]
    labels = build_next_decision_labels(decisions)
    account_by_id = {row["decision_episode_id"]: row for row in account_features}
    market_by_id = {row["decision_episode_id"]: row for row in market_features}
    label_by_id = {row["decision_episode_id"]: row for row in labels}
    dataset: list[dict[str, Any]] = []
    for decision in decisions:
        decision_id = str(decision.get("decision_episode_id", ""))
        decision_time = parse_utc(decision.get("decision_time"))
        if decision_time is None or decision_id not in account_by_id:
            continue
        dataset.append({
            "decision_episode_id": decision_id,
            "decision_time": iso_utc(decision_time),
            "decision_type": decision.get("decision_type", ""),
            "observed_action": decision.get("action", ""),
            "observed_position_before_contracts": _number(decision.get("position_before")),
            "observed_target_position_contracts": _number(decision.get("target_position")),
            "observed_position_delta_contracts": _number(decision.get("position_delta")),
            "synthetic_negative_sample": str(decision.get("synthetic_negative_sample", "")).lower() == "true",
            "observed_overall_confidence": decision.get("overall_confidence", ""),
            **{key: value for key, value in market_by_id.get(decision_id, {}).items() if key != "decision_episode_id"},
            **{key: (iso_utc(value) if isinstance(value, datetime) else value) for key, value in account_by_id[decision_id].items() if key not in {"decision_episode_id", "decision_time"}},
            **{key: value for key, value in label_by_id.get(decision_id, {}).items() if key != "decision_episode_id"},
        })
    dataset, split_rows = _split_rows(dataset)
    leakage = _leakage_audit(dataset)
    after = hash_files(root, PROTECTED_FILES)
    changed = [name for name in PROTECTED_FILES if before.get(name) != after.get(name)]
    analysis = git_value(["rev-parse", "HEAD"])
    summary: dict[str, Any] = {
        "report_version": "M4-FEATURE-LABEL-1.0",
        "source_commit": source_commit(),
        "analysis_commit": analysis,
        "analysis_branch": git_value(["branch", "--show-current"]),
        "status": "READY_WITH_WARNINGS" if leakage["status"] == "PASS" else "BLOCKED",
        "row_count": len(dataset),
        "btc_decision_count": len(decisions),
        "synthetic_decision_count": sum(bool(row.get("synthetic_negative_sample")) for row in dataset),
        "market_bar_count": len(market),
        "market_data_range_utc": {"first": iso_utc(market[0]["timestamp"]) if market else "", "last": iso_utc(market[-1]["timestamp"]) if market else ""},
        "feature_missingness": {
            "market_data_unavailable": sum(not row.get("feature_market_data_available") for row in dataset),
            "mark_index_missing": sum(bool(row.get("feature_mark_index_missing")) for row in dataset),
            "funding_missing": sum(row.get("feature_funding_rate") in (None, "") for row in dataset),
        },
        "label_status_counts": dict(Counter(str(row.get("label_status", "")) for row in dataset)),
        "split_policy": "Chronological 70% TRAIN / 15% VALIDATION / 15% TEST by decision_time; no random shuffle; no fit statistics",
        "leakage_audit": leakage,
        "raw_account_inputs_unchanged": not changed,
        "changed_protected_files": changed,
        "large_output": _write_large(dataset, outputs / "model_dataset.parquet"),
    }
    write_csv(_label_distribution(dataset), reports / "label_distribution.csv", ["next_action", "next_position_delta_bucket", "row_count"])
    write_csv(split_rows, reports / "dataset_time_split.csv", ["split", "row_count", "first_decision_time_utc", "last_decision_time_utc", "synthetic_row_count", "no_trade_or_hold_count"])
    _write_feature_dictionary(reports / "feature_dictionary.md")
    _write_label_dictionary(reports / "label_dictionary.md")
    _write_leakage_report(reports / "leakage_audit.md", leakage, summary)
    _write_no_trade_audit(reports / "no_trade_sampling_audit.md", dataset)
    (reports / "model_dataset_manifest.json").write_text(json.dumps(_jsonable(summary), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return summary


if __name__ == "__main__":
    result = build()
    print(f"status={result['status']}")
    print(f"row_count={result['row_count']}")
    print(f"leakage_status={result['leakage_audit']['status']}")
    print(f"raw_account_inputs_unchanged={result['raw_account_inputs_unchanged']}")
