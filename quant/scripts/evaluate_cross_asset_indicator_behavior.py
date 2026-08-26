#!/usr/bin/env python3
"""Evaluate the v3 indicator-enhanced model without exchange access."""

from __future__ import annotations

import json
from pathlib import Path

from evaluate_cross_asset_behavior import build


ROOT = Path(__file__).resolve().parents[2]


if __name__ == "__main__":
    result = build(
        dataset_path=ROOT / "quant" / "outputs" / "cross_asset_model_dataset_v3.csv",
        report_suffix="v3",
        strategy_version="behavioral-distillation-v3-cross-asset-indicators",
    )
    print(json.dumps(result, ensure_ascii=False))
