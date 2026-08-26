#!/usr/bin/env python3
"""Build a numerical-stability candidate; never activate it automatically."""

from __future__ import annotations

import json
from pathlib import Path

from build_cross_asset_deployment_model import build


ROOT = Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    result = build(
        dataset_path=ROOT / "quant" / "outputs" / "cross_asset_model_dataset_v3.csv",
        artifact_path=ROOT / "quant" / "outputs" / "cross_asset_deployment_model_v32.json",
        report_stem="cross_asset_v32_stable_target_manifest",
        model_version="behavioral-distillation-v3.2-stable-target",
        feature_contract_version="m13-v3.1-operational-parity",
        strategy_version="behavioral-distillation-v3.2-stable-target",
        target_l2=1.0,
    )
    print(json.dumps({"status": "PASS", "model_version": result["model_version"], "symbols": result["symbol_count"], "fit_rows": result["fit_row_count"], "model_sha256": result["model_sha256"], "rollout_status": result["rollout_status"]}, ensure_ascii=False))
