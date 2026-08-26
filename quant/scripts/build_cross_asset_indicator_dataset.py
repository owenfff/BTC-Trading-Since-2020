#!/usr/bin/env python3
"""Build the independent v3 cross-asset dataset with technical indicators."""

from __future__ import annotations

import json

from build_cross_asset_dataset import build


if __name__ == "__main__":
    result = build(output_stem="cross_asset_model_dataset_v3", report_stem="cross_asset_v3_model_dataset_manifest")
    print(json.dumps({
        "status": result["leakage_audit"]["status"],
        "rows": result["row_count"],
        "eligible_rows": result["model_eligible_row_count"],
        "symbols": result["symbol_count"],
        "feature_contract_version": "m13-v3-cross-asset-indicators",
    }, ensure_ascii=False))
