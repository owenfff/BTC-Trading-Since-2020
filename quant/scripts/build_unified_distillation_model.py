#!/usr/bin/env python3
"""Build the single v4.6 shared-intent candidate from frozen cross-venue rows."""

from __future__ import annotations

import csv
import hashlib
import json
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
for path in (ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from quant_bot.strategy.deployment import DeploymentBundle, save_deployment_bundle, sha256_file, utc_now  # noqa: E402
from quant_bot.strategy.feature_contract import UNIFIED_FEATURE_CONTRACT_VERSION  # noqa: E402
from quant_bot.strategy.unified_distillation import UNIFIED_MODEL_VERSION, UnifiedDistilledStrategy  # noqa: E402


DATASET = ROOT / "quant" / "outputs" / "cross_venue_model_dataset_v3.csv"
ARTIFACT = ROOT / "quant" / "outputs" / "cross_asset_deployment_model_v46.json"
REPORT_JSON = ROOT / "quant" / "reports" / "unified_distillation_manifest.json"
REPORT_MD = ROOT / "quant" / "reports" / "unified_distillation_manifest.md"


def _time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    return (parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)


def _number(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result and abs(result) != float("inf") else None


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _source_key(row: Mapping[str, Any]) -> str:
    venue = str(row.get("source_venue") or "UNKNOWN").upper()
    asset = str(row.get("canonical_asset") or row.get("symbol") or "UNKNOWN").upper()
    return f"{venue}:{asset}"


def _first_number(row: Mapping[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        value = _number(row.get(name))
        if value is not None:
            return value
    return None


def _aggregate_same_time(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], int]:
    groups: defaultdict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(_source_key(row), str(row.get("decision_time") or ""))].append(row)
    output: list[dict[str, Any]] = []
    ambiguous = 0
    for group in groups.values():
        ordered = sorted(group, key=lambda row: str(row.get("decision_episode_id") or ""))
        representative = dict(ordered[-1])
        targets = {str(row.get("raw_next_target_position_contracts") or row.get("label_next_target_position_contracts") or row.get("label_next_target_exposure") or "") for row in ordered}
        actions = {str(row.get("label_next_action") or "") for row in ordered}
        is_ambiguous = len(targets) > 1 or len(actions) > 1
        representative["label_ambiguity"] = "true" if is_ambiguous else "false"
        representative["_unified_fit_eligible"] = "false" if is_ambiguous else "true"
        representative["same_timestamp_event_count"] = len(ordered)
        if is_ambiguous:
            ambiguous += len(ordered)
        output.append(representative)
    output.sort(key=lambda row: (_time(row.get("decision_time")) or datetime.max.replace(tzinfo=timezone.utc), _source_key(row), str(row.get("decision_episode_id") or "")))
    return output, ambiguous


def _scales(rows: list[dict[str, Any]]) -> dict[str, float]:
    maxima: defaultdict[str, float] = defaultdict(float)
    for row in rows:
        key = _source_key(row)
        for name in ("raw_current_position_contracts", "raw_target_position_contracts", "raw_next_target_position_contracts", "observed_position_before_contracts", "observed_target_position_contracts"):
            value = _number(row.get(name))
            if value is not None:
                maxima[key] = max(maxima[key], abs(value))
    return {key: max(1.0, value) for key, value in maxima.items()}


def _balanced_rows(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    venues = sorted({_source_key(row).split(":", 1)[0] for row in rows})
    symbols_by_venue: dict[str, set[str]] = defaultdict(set)
    rows_by_key: Counter[str] = Counter()
    for row in rows:
        venue, asset = _source_key(row).split(":", 1)
        symbols_by_venue[venue].add(asset)
        rows_by_key[_source_key(row)] += 1
    raw_weights: list[float] = []
    for row in rows:
        venue, _ = _source_key(row).split(":", 1)
        key = _source_key(row)
        raw_weights.append(1.0 / max(1, len(venues)) / max(1, len(symbols_by_venue[venue])) / max(1, rows_by_key[key]))
    normalizer = len(rows) / max(sum(raw_weights), 1e-12)
    prepared = []
    for row, weight in zip(rows, raw_weights):
        item = dict(row)
        item["_unified_sample_weight"] = weight * normalizer
        item["dataset_split"] = "TRAIN"
        prepared.append(item)
    return prepared, {
        "venues": venues,
        "symbols_by_venue": {venue: sorted(values) for venue, values in sorted(symbols_by_venue.items())},
        "weighting": "equal total weight per source venue, then equal total weight per canonical asset, then equal row weight",
        "weight_sum": sum(raw_weights) * normalizer,
    }


def _prepare(rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, float], int, dict[str, Any]]:
    derivative = [row for row in rows if str(row.get("feature_instrument_class") or "").upper() != "SPOT" and str(row.get("model_eligible") or "").lower() == "true" and str(row.get("label_status") or "") == "AVAILABLE" and str(row.get("label_next_action") or "")]
    aggregated, ambiguous = _aggregate_same_time(derivative)
    scales = _scales(aggregated)
    for row in aggregated:
        scale = scales[_source_key(row)]
        current = _first_number(row, ("raw_current_position_contracts", "observed_position_before_contracts")) or 0.0
        target_contracts = _first_number(row, ("raw_next_target_position_contracts", "label_next_target_position_contracts", "observed_target_position_contracts"))
        row["feature_position_scale_contracts"] = scale
        row["feature_current_net_position_contracts"] = current
        row["feature_current_normalized_exposure"] = current / scale
        if target_contracts is not None:
            row["label_next_target_exposure"] = target_contracts / scale
    fit_rows, weighting = _balanced_rows(aggregated)
    return fit_rows, scales, ambiguous, weighting


def _policy(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    policies: dict[str, dict[str, Any]] = {}
    for row in rows:
        symbol = str(row.get("symbol") or "")
        if not symbol:
            continue
        policies.setdefault(symbol, {
            "historical_behavior": True,
            "source_venues": [],
            "canonical_assets": [],
            "instrument_class": str(row.get("feature_instrument_class") or "UNKNOWN"),
            "derivative_trading_allowed": str(row.get("feature_instrument_class") or "").upper() != "SPOT",
            "spot_policy": "MONITOR_ONLY" if str(row.get("feature_instrument_class") or "").upper() == "SPOT" else "NOT_SPOT",
        })
        item = policies[symbol]
        for field, value in (("source_venues", str(row.get("source_venue") or "UNKNOWN")), ("canonical_assets", str(row.get("canonical_asset") or symbol))):
            if value not in item[field]:
                item[field].append(value)
    return policies


def build(*, dataset_path: Path = DATASET, artifact_path: Path = ARTIFACT) -> dict[str, Any]:
    if not dataset_path.exists():
        raise FileNotFoundError(f"frozen cross-venue dataset is missing: {dataset_path}")
    with dataset_path.open("r", encoding="utf-8", newline="") as handle:
        raw_rows = list(csv.DictReader(handle))
    if not raw_rows:
        raise ValueError("frozen cross-venue dataset is empty")
    fit_rows, scales_by_source, ambiguous_count, weighting = _prepare(raw_rows)
    if not fit_rows:
        raise ValueError("no eligible derivative rows remain after coverage and label checks")
    model = UnifiedDistilledStrategy(target_l2=1.0).fit(fit_rows)
    time_ordered = sorted(fit_rows, key=lambda row: _time(row.get("decision_time")) or datetime.max.replace(tzinfo=timezone.utc))
    split = max(1, int(len(time_ordered) * 0.8))
    calibration = model.calibrate_action_threshold(time_ordered[split:]) if split < len(time_ordered) else {"calibration_rows": 0, "selected_threshold": model.action_threshold}
    # Scales are exposed under source keys and historical symbols.  Runtime
    # lookup remains backward-compatible while cross-venue collisions retain
    # their independent scale in metadata.
    scales: dict[str, float] = dict(scales_by_source)
    for row in fit_rows:
        symbol = str(row.get("symbol") or "")
        scales.setdefault(symbol, scales_by_source[_source_key(row)])
    model_payload = model.to_dict()
    model_sha = hashlib.sha256(json.dumps(model_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    symbols = tuple(sorted({str(row.get("symbol")) for row in raw_rows if row.get("symbol")}))
    cutoff = max((_time(row.get("decision_time")) for row in raw_rows if _time(row.get("decision_time"))), default=None)
    risk = {
        "method": "unified-distillation-candidate-historical-envelope",
        "units": "normalized exposure; exchange adapters convert units",
        "per_symbol_target_exposure": {symbol: {"p99_abs_target_exposure": 1.0, "max_abs_target_exposure": 1.0} for symbol in symbols},
        "historical_simultaneous_total_exposure_cap": 1.0,
        "historical_single_adjustment_p99": 1.0,
        "historical_single_adjustment_max": 1.0,
        "fail_closed_if_missing": True,
    }
    bundle = DeploymentBundle(
        model=model,
        model_version=UNIFIED_MODEL_VERSION,
        feature_contract_version=UNIFIED_FEATURE_CONTRACT_VERSION,
        training_data_sha256=sha256_file(dataset_path),
        code_commit=_git_head(),
        deployment_time=utc_now(),
        frozen_cutoff=cutoff.isoformat().replace("+00:00", "Z") if cutoff else "",
        symbols=symbols,
        position_scales=scales,
        risk_envelope=risk,
        symbol_policy=_policy(raw_rows),
        model_sha256=model_sha,
    )
    save_deployment_bundle(bundle, artifact_path)
    report = {
        "report_version": "M16-UNIFIED-DISTILLATION-MANIFEST-1.0",
        "status": "CANDIDATE_PENDING_STRICT_AUTONOMOUS_AUDIT",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "model_version": UNIFIED_MODEL_VERSION,
        "feature_contract_version": UNIFIED_FEATURE_CONTRACT_VERSION,
        "dataset_path": str(dataset_path.relative_to(ROOT)),
        "dataset_sha256": sha256_file(dataset_path),
        "artifact_path": str(artifact_path.relative_to(ROOT)),
        "model_sha256": model_sha,
        "code_commit": bundle.code_commit,
        "deployment_time": bundle.deployment_time,
        "frozen_cutoff": bundle.frozen_cutoff,
        "raw_row_count": len(raw_rows),
        "fit_row_count": len(fit_rows),
        "ambiguous_row_count": ambiguous_count,
        "source_counts": dict(Counter(str(row.get("source_venue") or "UNKNOWN") for row in raw_rows)),
        "fit_source_counts": dict(Counter(str(row.get("source_venue") or "UNKNOWN") for row in fit_rows)),
        "symbol_count": len(symbols),
        "symbols": list(symbols),
        "weighting": weighting,
        "threshold_calibration": calibration,
        "source_venue_is_model_feature": False,
        "spot_policy": "monitor-only",
        "online_training": False,
        "active_demo_model_changed": False,
        "rollout_status": "NOT_PROMOTED",
        "risk_envelope": risk,
    }
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    REPORT_MD.write_text("\n".join([
        "# Unified Distillation v4.6 Manifest",
        "",
        f"- status: **{report['status']}**",
        f"- model: `{UNIFIED_MODEL_VERSION}`",
        f"- feature contract: `{UNIFIED_FEATURE_CONTRACT_VERSION}`",
        f"- raw rows: `{len(raw_rows)}`; fit rows: `{len(fit_rows)}`; ambiguous rows retained/excluded: `{ambiguous_count}`",
        f"- sources: `{report['source_counts']}`",
        f"- symbols: `{len(symbols)}`",
        f"- dataset SHA256: `{report['dataset_sha256']}`",
        f"- model SHA256: `{model_sha}`",
        f"- code commit: `{bundle.code_commit}`",
        f"- frozen cutoff: `{bundle.frozen_cutoff}`",
        f"- selected train-only threshold: `{calibration.get('selected_threshold')}`",
        "- source venue is a balancing/reporting key, not a learned model feature",
        "- Spot remains monitor-only",
        "- current v3 Demo model was not changed",
        "",
        "This artifact is a candidate only. Strict autonomous replay must pass before any Demo model switch.",
    ]) + "\n", encoding="utf-8")
    return report


if __name__ == "__main__":
    result = build()
    print(json.dumps({"status": "PASS", "model_version": result["model_version"], "fit_rows": result["fit_row_count"], "artifact": result["artifact_path"]}, ensure_ascii=False))
