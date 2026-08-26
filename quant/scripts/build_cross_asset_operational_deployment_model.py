#!/usr/bin/env python3
"""Build the independent v3.1 operational-parity Demo artifact.

The v3.1 artifact is kept separate from the current v3 Demo artifact until
its time-out validation is complete.  It uses the same frozen historical rows
but adds explicit missingness indicators for funding and mark/index context.
"""

from __future__ import annotations

import json
from pathlib import Path

from build_cross_asset_deployment_model import build


ROOT = Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    result = build(
        dataset_path=ROOT / "quant" / "outputs" / "cross_asset_model_dataset_v3.csv",
        artifact_path=ROOT / "quant" / "outputs" / "cross_asset_deployment_model_v31.json",
        report_stem="cross_asset_v31_operational_deployment_manifest",
        model_version="behavioral-distillation-v3.1-operational-parity",
        feature_contract_version="m13-v3.1-operational-parity",
        strategy_version="behavioral-distillation-v3.1-operational-parity",
    )
    print(json.dumps({"status": "PASS", "model_version": result["model_version"], "symbols": result["symbol_count"], "fit_rows": result["fit_row_count"], "model_sha256": result["model_sha256"]}, ensure_ascii=False))
