#!/usr/bin/env python3
"""Build the frozen, all-history deployment model used by Testnet only.

This is deliberately separate from the M13 evaluator. M13 keeps its global
time split and untouched holdout results; this artifact is refit once from the
already frozen historical export and is never retrained by the bot.
"""

from __future__ import annotations

import csv
import json
import math
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from statistics import quantiles
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from quant_bot.strategy.deployment import (  # noqa: E402
    DEPLOYMENT_MODEL_VERSION,
    LEGACY_DEPLOYMENT_MODEL_VERSION,
    DeploymentBundle,
    save_deployment_bundle,
    sha256_file,
    utc_now,
)
from quant_bot.strategy.feature_contract import FEATURE_CONTRACT_VERSION, LEGACY_FEATURE_CONTRACT_VERSION, OPERATIONAL_FEATURE_CONTRACT_VERSION  # noqa: E402
from quant_bot.strategy.supervised_models import CrossAssetNumpyLogisticStrategy  # noqa: E402


def _float(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _p99(values: list[float]) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return abs(values[0])
    return float(quantiles([abs(value) for value in values], n=100, method="inclusive")[98])


def _git_head() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return "UNKNOWN"


def _full_scales(rows: list[dict[str, Any]]) -> dict[str, float]:
    maxima: defaultdict[str, float] = defaultdict(float)
    for row in rows:
        symbol = str(row.get("symbol") or "")
        if not symbol:
            continue
        for key in ("observed_position_before_contracts", "observed_target_position_contracts", "observed_position_delta_contracts"):
            value = _float(row.get(key))
            if value is not None:
                maxima[symbol] = max(maxima[symbol], abs(value))
    return {symbol: max(1.0, value) for symbol, value in maxima.items()}


def _risk_envelope(rows: list[dict[str, Any]], scales: dict[str, float]) -> dict[str, Any]:
    targets_by_symbol: defaultdict[str, list[float]] = defaultdict(list)
    adjustments: list[float] = []
    current_by_time: defaultdict[str, float] = defaultdict(float)
    for row in rows:
        symbol = str(row.get("symbol") or "")
        scale = max(scales.get(symbol, 1.0), 1.0)
        target_contracts = _float(row.get("label_next_target_position_contracts"))
        current_contracts = _float(row.get("observed_position_before_contracts"))
        target = target_contracts / scale if target_contracts is not None else None
        current = current_contracts / scale if current_contracts is not None else None
        if symbol and target is not None:
            targets_by_symbol[symbol].append(target)
        if target is not None and current is not None:
            adjustments.append(target - current)
        timestamp = str(row.get("decision_time") or "")
        if timestamp and current is not None:
            current_by_time[timestamp] += abs(current)
    per_symbol = {
        symbol: {"p99_abs_target_exposure": _p99(values), "max_abs_target_exposure": max(abs(value) for value in values)}
        for symbol, values in sorted(targets_by_symbol.items())
    }
    simultaneous = list(current_by_time.values())
    return {
        "method": "full-history-behavioral-envelope",
        "per_symbol_target_exposure": per_symbol,
        "historical_simultaneous_total_exposure_cap": max(simultaneous, default=0.0),
        "historical_single_adjustment_p99": _p99(adjustments),
        "historical_single_adjustment_max": max((abs(value) for value in adjustments), default=0.0),
        "units": "normalized exposure; runtime converts through current settlement equity and instrument terms",
        "fail_closed_if_missing": True,
    }


def build(
    *,
    dataset_path: Path | None = None,
    artifact_path: Path | None = None,
    report_stem: str = "cross_asset_deployment_manifest",
    model_version: str = LEGACY_DEPLOYMENT_MODEL_VERSION,
    feature_contract_version: str = LEGACY_FEATURE_CONTRACT_VERSION,
    strategy_version: str = "behavioral-distillation-v2-cross-asset-logistic",
) -> dict[str, Any]:
    dataset_path = dataset_path or (ROOT / "quant" / "outputs" / "cross_asset_model_dataset.csv")
    if not dataset_path.exists():
        raise FileNotFoundError(dataset_path)
    with dataset_path.open("r", encoding="utf-8", newline="") as handle:
        source_rows = list(csv.DictReader(handle))
    if not source_rows:
        raise ValueError("deployment dataset is empty")

    rows = [
        dict(row)
        for row in source_rows
        if str(row.get("feature_instrument_class", "")).upper() != "SPOT"
        and str(row.get("label_status", "")) == "AVAILABLE"
        and str(row.get("label_next_action", ""))
    ]
    if not rows:
        raise ValueError("deployment dataset has no labelled derivative rows")
    scales = _full_scales(source_rows)
    # The model class intentionally trains only rows marked TRAIN. A private
    # copy is marked TRAIN here; the M13 dataset and its split are untouched.
    fit_rows: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source, dataset_split="TRAIN")
        symbol = str(row["symbol"])
        scale = max(scales.get(symbol, 1.0), 1.0)
        current_contracts = _float(row.get("observed_position_before_contracts"))
        target_contracts = _float(row.get("label_next_target_position_contracts"))
        row["feature_position_scale_contracts"] = scale
        row["feature_current_normalized_exposure"] = (current_contracts / scale) if current_contracts is not None else ""
        row["label_next_target_exposure"] = (target_contracts / scale) if target_contracts is not None else ""
        if feature_contract_version == OPERATIONAL_FEATURE_CONTRACT_VERSION:
            funding_raw = row.get("feature_funding_rate")
            mark_missing = str(row.get("feature_mark_index_missing", "")).strip().lower() in {"1", "true", "yes"}
            row["feature_funding_rate_missing"] = "0" if funding_raw not in (None, "") else "1"
            row["feature_mark_index_basis_missing"] = "1" if mark_missing or row.get("feature_mark_index_basis") in (None, "") else "0"
        fit_rows.append(row)
    model = CrossAssetNumpyLogisticStrategy().fit(fit_rows)
    model.version = strategy_version
    symbols = sorted({str(row["symbol"]) for row in source_rows if row.get("symbol")})
    policy: dict[str, dict[str, Any]] = {}
    for symbol in symbols:
        class_name = next((str(row.get("feature_instrument_class", "UNKNOWN")) for row in source_rows if row.get("symbol") == symbol), "UNKNOWN")
        policy[symbol] = {
            "historical_behavior": True,
            "instrument_class": class_name,
            "derivative_trading_allowed": class_name.upper() != "SPOT",
            "spot_policy": "MONITOR_ONLY" if class_name.upper() == "SPOT" else "NOT_SPOT",
        }
    parsed_times = [str(row.get("decision_time")) for row in source_rows if row.get("decision_time")]
    cutoff = max(parsed_times) if parsed_times else ""
    model_payload = model.to_dict()
    model_sha256 = __import__("hashlib").sha256(json.dumps(model_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()
    bundle = DeploymentBundle(
        model=model,
        model_version=model_version,
        feature_contract_version=feature_contract_version,
        training_data_sha256=sha256_file(dataset_path),
        code_commit=_git_head(),
        deployment_time=utc_now(),
        frozen_cutoff=cutoff,
        symbols=tuple(symbols),
        position_scales=scales,
        risk_envelope=_risk_envelope(rows, scales),
        symbol_policy=policy,
        model_sha256=model_sha256,
    )
    outputs = ROOT / "quant" / "outputs"
    reports = ROOT / "quant" / "reports"
    artifact_path = artifact_path or (outputs / "cross_asset_deployment_model.json")
    save_deployment_bundle(bundle, artifact_path)
    rollout_status = (
        "CANDIDATE_PENDING_TIME_OUT_VALIDATION"
        if "v3.1" in model_version
        else "ACTIVE_BASELINE_FOR_DEMO"
    )
    report = {
        "report_version": "M13-DEPLOYMENT-MODEL-1.0",
        "strategy_fidelity": "BEHAVIORAL_APPROXIMATION",
        "model_version": model_version,
        "feature_contract_version": feature_contract_version,
        "training_data_sha256": bundle.training_data_sha256,
        "model_sha256": bundle.model_sha256,
        "code_commit": bundle.code_commit,
        "deployment_time": bundle.deployment_time,
        "frozen_cutoff": bundle.frozen_cutoff,
        "source_row_count": len(source_rows),
        "fit_row_count": len(fit_rows),
        "symbol_count": len(symbols),
        "symbols": symbols,
        "position_scales_fit_on": "all historical rows before the frozen deployment cutoff; no online retraining",
        "spot_policy": "monitor-only; never mixed with derivative position semantics",
        "risk_envelope": bundle.risk_envelope,
        "artifact": f"{artifact_path.as_posix()} (tracked deployment artifact)",
        "rollout_status": rollout_status,
    }
    reports.mkdir(parents=True, exist_ok=True)
    (reports / f"{report_stem}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (reports / f"{report_stem}.md").write_text(
        "\n".join([
            "# Cross-Asset Deployment Model",
            "",
            f"- model: **{model_version}**",
            "- fidelity: **BEHAVIORAL_APPROXIMATION**",
            f"- source rows: `{len(source_rows)}`; fit rows: `{len(fit_rows)}`",
            f"- symbols: `{len(symbols)}`",
            f"- frozen cutoff: `{bundle.frozen_cutoff}`",
            f"- training data SHA256: `{bundle.training_data_sha256}`",
            f"- model SHA256: `{bundle.model_sha256}`",
            f"- code commit: `{bundle.code_commit}`",
            f"- rollout status: **{rollout_status}**",
            "- runtime training: **disabled**",
            "- Spot: **monitor-only**",
            "",
            "The artifact is tracked for reproducible Demo deployment only; it is never a mainnet credential or endpoint. It is a behavioral approximation and is not a claim of exact strategy recovery or future profitability.",
        ]) + "\n",
        encoding="utf-8",
    )
    return report


if __name__ == "__main__":
    result = build()
    print(json.dumps({"status": "PASS", "model_version": result["model_version"], "symbols": result["symbol_count"], "fit_rows": result["fit_row_count"]}, ensure_ascii=False))
