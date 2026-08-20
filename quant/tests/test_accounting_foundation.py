from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "quant" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from bitmex_replay.accounting_foundation import (  # noqa: E402
    build_accounting_foundation_manifest,
    render_accounting_foundation_markdown,
)


def test_foundation_manifest_uses_dual_ledgers() -> None:
    manifest = build_accounting_foundation_manifest(ROOT, analysis_commit="a" * 40, analysis_branch="test")
    assert set(manifest["ledgers"]) == {"exchange_reported_accounting", "analytical_accounting"}
    assert manifest["downstream_behavioral_research_status"] == "READY_WITH_KNOWN_ACCOUNTING_RESIDUALS"


def test_foundation_counts_and_raw_protection() -> None:
    manifest = build_accounting_foundation_manifest(ROOT, analysis_commit="b" * 40, analysis_branch="test")
    assert all(item["status"] == "PASS" for item in manifest["count_checks"].values())
    assert manifest["raw_inputs_unchanged"] is True


def test_foundation_markdown_preserves_residual_boundary() -> None:
    manifest = build_accounting_foundation_manifest(ROOT, analysis_commit="c" * 40, analysis_branch="test")
    text = render_accounting_foundation_markdown(manifest)
    assert "do not block downstream behavioral research" in text
    assert "Raw Execution" in text and "Derivative Trade" in text


def test_foundation_policy_is_valid_json() -> None:
    policy = json.loads((ROOT / "quant" / "config" / "downstream_accounting_policy.json").read_text(encoding="utf-8"))
    assert policy["accounting_eligibility"]["eligible_normalization_statuses"] == ["PASS", "WARNING"]
    assert policy["accounting_eligibility"]["blocked_normalization_statuses"] == ["BLOCKED"]
