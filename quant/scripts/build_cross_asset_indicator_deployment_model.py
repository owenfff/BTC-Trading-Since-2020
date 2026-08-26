#!/usr/bin/env python3
"""Build the independent v3 indicator deployment artifact."""

from __future__ import annotations

import json
from pathlib import Path

from build_cross_asset_deployment_model import build


ROOT = Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    result = build(
        dataset_path=ROOT / "quant" / "outputs" / "cross_asset_model_dataset_v3.csv",
        artifact_path=ROOT / "quant" / "outputs" / "cross_asset_deployment_model_v3.json",
        report_stem="cross_asset_v3_deployment_manifest",
        model_version="behavioral-distillation-v3-cross-asset-indicators",
        feature_contract_version="m13-v3-cross-asset-indicators",
        strategy_version="behavioral-distillation-v3-cross-asset-indicators",
    )
    print(json.dumps({"status": "PASS", "model_version": result["model_version"], "symbols": result["symbol_count"], "fit_rows": result["fit_row_count"]}, ensure_ascii=False))
