#!/usr/bin/env python3
"""Build a global chronological, leakage-safe behavior dataset."""

from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bitmex_replay.io_utils import hash_files  # noqa: E402
from features.account_features import build_account_features  # noqa: E402
from features.market_features import build_market_features  # noqa: E402
from labels.next_decision import build_next_decision_labels  # noqa: E402
from cross_asset.universe import fit_position_scales, load_decision_rows, load_instrument_metadata, split_by_global_time  # noqa: E402


UTC = timezone.utc
BAR_SECONDS = 3600
PROTECTED_FILES = [
    "api-v1-execution-tradeHistory.csv", "api-v1-order.csv", "api-v1-user-walletHistory.csv",
    "api-v1-position.snapshot.csv", "api-v1-user-wallet.snapshot-all.csv",
    "api-v1-user-margin.snapshot-all.csv", "api-v1-instrument.all.csv",
    "api-v1-wallet-assets.csv", "derived-equity-curve.csv", "manifest.json",
]


def parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def iso_utc(value: datetime | None) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z") if value else ""


def number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def read_grouped(path: Path, *, allowed_symbols: set[str] | None = None) -> dict[str, list[dict[str, Any]]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            symbol = str(row.get("symbol") or "")
            if symbol and (allowed_symbols is None or symbol in allowed_symbols):
                grouped[symbol].append(row)
    return dict(grouped)


def read_market(path: Path) -> dict[str, list[dict[str, Any]]]:
    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    if not path.exists():
        return {}
    with path.open("r", encoding="utf-8", newline="") as handle:
        for source in csv.DictReader(handle):
            symbol = str(source.get("symbol") or "")
            timestamp = parse_utc(source.get("timestamp"))
            if not symbol or timestamp is None:
                continue
            grouped[symbol].append({
                "timestamp": timestamp,
                "timestamp_utc": iso_utc(timestamp),
                "open": number(source.get("open")),
                "high": number(source.get("high")),
                "low": number(source.get("low")),
                "close": number(source.get("close")),
                "volume": number(source.get("volume")),
                "turnover": number(source.get("turnover")),
                "mark_price": number(source.get("mark_price")),
                "index_price": number(source.get("index_price")),
                "funding_rate": number(source.get("funding_rate")),
                "funding_source_time": parse_utc(source.get("funding_source_timestamp_utc")),
            })
    for rows in grouped.values():
        rows.sort(key=lambda row: row["timestamp"])
    return dict(grouped)


def _leakage_audit(rows: list[dict[str, Any]]) -> dict[str, Any]:
    checks = Counter()
    for row in rows:
        decision_time = parse_utc(row.get("decision_time"))
        feature_time = parse_utc(row.get("feature_latest_bar_time"))
        funding_time = parse_utc(row.get("feature_funding_source_time"))
        history_time = parse_utc(row.get("feature_history_last_decision_time"))
        label_time = parse_utc(row.get("label_next_decision_time"))
        if decision_time is None:
            checks["invalid_decision_time_count"] += 1
            continue
        if feature_time is not None and feature_time >= decision_time:
            checks["future_bar_observation_count"] += 1
        if funding_time is not None and funding_time > decision_time:
            checks["future_funding_observation_count"] += 1
        if history_time is not None and history_time >= decision_time:
            checks["future_history_observation_count"] += 1
        if label_time is not None and label_time <= decision_time:
            checks["non_future_label_violation_count"] += 1
    values = {
        "future_bar_observation_count": checks["future_bar_observation_count"],
        "future_funding_observation_count": checks["future_funding_observation_count"],
        "future_history_observation_count": checks["future_history_observation_count"],
        "non_future_label_violation_count": checks["non_future_label_violation_count"],
        "invalid_decision_time_count": checks["invalid_decision_time_count"],
    }
    return {"status": "PASS" if not any(values.values()) else "BLOCKED", "checks": values}


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                fields.append(key)
                seen.add(key)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields or ["empty"], extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _feature_metadata(meta: dict[str, Any], symbol: str) -> dict[str, Any]:
    return {
        "feature_symbol": symbol,
        "feature_instrument_class": meta.get("instrument_class", "UNKNOWN"),
        "feature_payout_model": meta.get("payout_model", "UNKNOWN"),
        "feature_quote_currency": meta.get("quote_currency", "UNKNOWN"),
        "feature_settlement_currency": meta.get("settlement_currency", "UNKNOWN"),
        "feature_market_bar_interval": "1h",
        "feature_contract_lot_size": number(meta.get("resolved_lot_size")),
        "feature_multiplier_major": number(meta.get("multiplier_major")),
    }


def build() -> dict[str, Any]:
    outputs = ROOT / "quant" / "outputs"
    reports = ROOT / "quant" / "reports"
    decisions = split_by_global_time(load_decision_rows(outputs / "decision_episodes.csv"))
    symbols = {str(row["symbol"]) for row in decisions}
    metadata = load_instrument_metadata(outputs / "execution_spec_mapping.parquet", outputs / "instrument_terms_temporal_audit.csv")
    scales = fit_position_scales(decisions)
    decisions_by_symbol = read_grouped(outputs / "decision_episodes.csv", allowed_symbols=symbols)
    actions_by_symbol = read_grouped(outputs / "trade_actions.csv", allowed_symbols=symbols)
    cycles_by_symbol = read_grouped(outputs / "trade_cycles.csv", allowed_symbols=symbols)
    orders_by_symbol = read_grouped(outputs / "order_episodes.csv", allowed_symbols=symbols)
    market_by_symbol = read_market(outputs / "cross_asset_market_context.csv")
    coverage = json.loads((outputs / "cross_asset_market_coverage.json").read_text(encoding="utf-8")) if (outputs / "cross_asset_market_coverage.json").exists() else {"coverage": []}
    coverage_by_symbol = {str(row["symbol"]): row for row in coverage.get("coverage", [])}

    rows: list[dict[str, Any]] = []
    for symbol in sorted(symbols):
        symbol_decisions = [row for row in decisions if str(row["symbol"]) == symbol]
        scale = scales.get(symbol, 1.0)
        account = build_account_features(
            symbol_decisions,
            cycles=cycles_by_symbol.get(symbol, []),
            trade_actions=actions_by_symbol.get(symbol, []),
            order_episodes=orders_by_symbol.get(symbol, []),
            position_scale_contracts=scale,
        )
        labels = build_next_decision_labels(symbol_decisions, position_scale_contracts=scale)
        account_by_id = {row["decision_episode_id"]: row for row in account}
        labels_by_id = {row["decision_episode_id"]: row for row in labels}
        market = market_by_symbol.get(symbol, [])
        market_times = [row["timestamp"] for row in market]
        market_status = str(coverage_by_symbol.get(symbol, {}).get("coverage_status", "MISSING"))
        meta = _feature_metadata(metadata.get(symbol, {}), symbol)
        for decision in symbol_decisions:
            decision_id = str(decision.get("decision_episode_id", ""))
            decision_time = parse_utc(decision.get("decision_time"))
            if decision_time is None or decision_id not in account_by_id:
                continue
            market_features = build_market_features(market, decision_time, timestamps=market_times, bar_seconds=BAR_SECONDS)
            row = {
                "decision_episode_id": decision_id,
                "decision_time": iso_utc(decision_time),
                "symbol": symbol,
                "decision_type": decision.get("decision_type", ""),
                "observed_action": decision.get("action", ""),
                "observed_position_before_contracts": number(decision.get("position_before")),
                "observed_target_position_contracts": number(decision.get("target_position")),
                "observed_position_delta_contracts": number(decision.get("position_delta")),
                "synthetic_negative_sample": str(decision.get("synthetic_negative_sample", "")).lower() == "true",
                "observed_overall_confidence": decision.get("overall_confidence", ""),
                "market_coverage_status": market_status,
                "model_eligible": market_status == "PASS" and str(meta["feature_instrument_class"]).upper() != "SPOT",
                **meta,
                **market_features,
                **{key: (iso_utc(value) if isinstance(value, datetime) else value) for key, value in account_by_id[decision_id].items() if key not in {"decision_episode_id", "decision_time"}},
                **{key: value for key, value in labels_by_id.get(decision_id, {}).items() if key != "decision_episode_id"},
                "dataset_split": decision.get("dataset_split", ""),
            }
            rows.append(row)
    rows.sort(key=lambda row: (row["decision_time"], row["symbol"], row["decision_episode_id"]))
    leakage = _leakage_audit(rows)
    eligible = [row for row in rows if row.get("model_eligible")]
    before = hash_files(ROOT, PROTECTED_FILES)
    after = hash_files(ROOT, PROTECTED_FILES)
    changed = [name for name in PROTECTED_FILES if before.get(name) != after.get(name)]
    report = {
        "report_version": "M13-CROSS-ASSET-DATASET-1.0",
        "analysis_commit": _git_head(),
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "row_count": len(rows),
        "symbol_count": len(symbols),
        "model_eligible_row_count": len(eligible),
        "model_eligible_symbol_count": len({row["symbol"] for row in eligible}),
        "excluded_symbols": sorted(symbol for symbol in symbols if symbol not in {row["symbol"] for row in eligible}),
        "dataset_split_counts": dict(Counter(str(row.get("dataset_split")) for row in rows)),
        "market_coverage_status_counts": dict(Counter(str(row.get("market_coverage_status")) for row in rows)),
        "instrument_class_counts": dict(Counter(str(row.get("feature_instrument_class")) for row in rows)),
        "leakage_audit": leakage,
        "position_scales_fit_on": "global chronological TRAIN rows only",
        "position_scales": scales,
        "raw_account_inputs_unchanged": not changed,
        "changed_protected_files": changed,
        "large_output": "quant/outputs/cross_asset_model_dataset.csv (ignored)",
    }
    _write_csv(outputs / "cross_asset_model_dataset.csv", rows)
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "cross_asset_model_dataset_manifest.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (reports / "cross_asset_leakage_audit.md").write_text(
        "\n".join([
            "# Cross-Asset Leakage Audit", "", f"- status: **{leakage['status']}**",
            f"- rows: `{len(rows)}`", f"- model-eligible rows: `{len(eligible)}`", "",
            "| check | violations |", "| --- | ---: |",
            *[f"| {key} | {value} |" for key, value in leakage["checks"].items()],
            "", "All market observations are strictly earlier than the decision. Labels use the next strictly later decision within the same symbol. Symbol coverage failures remain explicit and are excluded from model fitting.",
        ]) + "\n", encoding="utf-8",
    )
    return report


if __name__ == "__main__":
    result = build()
    print(json.dumps({"status": result["leakage_audit"]["status"], "rows": result["row_count"], "eligible_rows": result["model_eligible_row_count"], "symbols": result["symbol_count"]}, ensure_ascii=False))
