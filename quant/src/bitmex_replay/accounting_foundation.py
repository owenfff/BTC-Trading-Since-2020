from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def build_accounting_foundation_manifest(root: Path, *, analysis_commit: str, analysis_branch: str) -> dict[str, Any]:
    root = Path(root)
    policy = _read_json(root / "quant" / "config" / "downstream_accounting_policy.json")
    accounting = _read_json(root / "quant" / "reports" / "position_accounting.json")
    counts = accounting.get("input_counts", {})
    required = {
        "raw_execution_count": 173434,
        "derivative_execution_count": 173226,
        "raw_trade_count": 160510,
        "derivative_trade_count": 160302,
        "funding_count": 12905,
        "settlement_count": 19,
        "spot_execution_count": 208,
    }
    count_checks = {
        key: {"expected": value, "actual": counts.get(key), "status": "PASS" if counts.get(key) == value else "BLOCKED"}
        for key, value in required.items()
    }
    all_counts_pass = all(item["status"] == "PASS" for item in count_checks.values())
    protected = accounting.get("protected_files", {})
    raw_unchanged = protected.get("unchanged") is True
    return {
        "manifest_version": "M0-AUTONOMOUS-1.0",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "analysis_commit": analysis_commit,
        "analysis_branch": analysis_branch,
        "source_commit": accounting.get("source_commit", ""),
        "source_position_accounting_report_analysis_commit": accounting.get("analysis_commit", ""),
        "teacher_data_type": "TRADE_RECORDS_ONLY",
        "downstream_behavioral_research_status": "READY_WITH_KNOWN_ACCOUNTING_RESIDUALS" if all_counts_pass and raw_unchanged else "BLOCKED",
        "accounting_status": "HIGH_CONFIDENCE_WITH_RESIDUALS" if all_counts_pass and raw_unchanged else "BLOCKED",
        "count_checks": count_checks,
        "raw_inputs_unchanged": raw_unchanged,
        "ledgers": policy["ledgers"],
        "fidelity": policy["fidelity"],
        "accounting_eligibility": policy["accounting_eligibility"],
        "reported_pnl_decomposition": accounting.get("reported_pnl_decomposition", {}),
        "execution_order": accounting.get("execution_order", {}),
        "known_residuals": {
            "current_cost": "Closest analytical cost candidate differs from snapshot by about 2 raw units.",
            "aep": "Displayed analytical AEP differs from snapshot by 0.2974; exchange engine semantics remain unresolved.",
        },
        "next_action": "Build wallet ledger with raw/major currency separation and day/hour/terminal reconciliation.",
    }


def render_accounting_foundation_markdown(manifest: dict[str, Any]) -> str:
    lines = [
        "# Accounting Foundation Manifest",
        "",
        f"- Status: **{manifest['accounting_status']}**",
        f"- Downstream behavioral research: **{manifest['downstream_behavioral_research_status']}**",
        f"- Teacher data: `{manifest['teacher_data_type']}`",
        f"- Analysis commit: `{manifest['analysis_commit']}`",
        f"- Source position-accounting report analysis commit: `{manifest['source_position_accounting_report_analysis_commit']}`",
        f"- Raw inputs unchanged: **{manifest['raw_inputs_unchanged']}**",
        "",
        "## Dual ledger boundary",
        "",
        "The exchange-reported ledger preserves exchange and wallet values. The analytical ledger reconstructs quantity, execution cost, gross PnL, AEP, cycles, and confidence flags. They are never silently summed or substituted for one another.",
        "",
        "## Count checks",
        "",
        "| Dataset | Expected | Actual | Status |",
        "| --- | ---: | ---: | --- |",
    ]
    labels = {
        "raw_execution_count": "Raw Execution",
        "derivative_execution_count": "Derivative Execution",
        "raw_trade_count": "Raw Trade",
        "derivative_trade_count": "Derivative Trade",
        "funding_count": "Funding",
        "settlement_count": "Settlement",
        "spot_execution_count": "Spot Trade",
    }
    for key, label in labels.items():
        item = manifest["count_checks"][key]
        lines.append(f"| {label} | {item['expected']} | {item['actual']} | {item['status']} |")
    lines.extend([
        "",
        "## Fidelity contract",
        "",
    ])
    for key, value in manifest["fidelity"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend([
        "",
        "## Known residuals",
        "",
        f"- {manifest['known_residuals']['current_cost']}",
        f"- {manifest['known_residuals']['aep']}",
        "- These residuals remain explicit limitations and do not block downstream behavioral research.",
        "",
        f"## Next action\n\n{manifest['next_action']}",
    ])
    return "\n".join(lines) + "\n"


__all__ = ["build_accounting_foundation_manifest", "render_accounting_foundation_markdown"]
