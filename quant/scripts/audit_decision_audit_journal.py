from __future__ import annotations

import json
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
JOURNAL_ROOT = ROOT / "quant" / "outputs" / "decision_audit"
REPORT_JSON = ROOT / "quant" / "reports" / "decision_audit_journal.json"
REPORT_MD = ROOT / "quant" / "reports" / "decision_audit_journal.md"
DATE_RE = re.compile(r"^decision_audit_(\d{4}-\d{2}-\d{2})\.jsonl$")
SENSITIVE_KEY_PARTS = (
    "api_key",
    "api_secret",
    "access_token",
    "credential",
    "passphrase",
    "private_key",
    "secret",
)


def _sensitive_paths(value: Any, path: tuple[str, ...] = ()) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized = key.lower().replace("-", "_")
            if any(part in normalized for part in SENSITIVE_KEY_PARTS):
                found.append(".".join((*path, key)))
            found.extend(_sensitive_paths(child, (*path, key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_sensitive_paths(child, (*path, str(index))))
    return found


def audit_journal(journal_root: Path = JOURNAL_ROOT) -> dict[str, Any]:
    files = sorted(journal_root.glob("decision_audit_*.jsonl")) if journal_root.exists() else []
    file_counts: Counter[str] = Counter()
    malformed_lines = 0
    invalid_dates = 0
    sensitive_paths: list[str] = []
    total_records = 0
    for path in files:
        match = DATE_RE.match(path.name)
        if not match:
            invalid_dates += 1
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            malformed_lines += 1
            continue
        for line_number, line in enumerate(lines, start=1):
            if not line.strip():
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                malformed_lines += 1
                continue
            if not isinstance(record, dict) or not isinstance(record.get("decision_time"), str):
                malformed_lines += 1
                continue
            total_records += 1
            file_counts[path.name] += 1
            sensitive_paths.extend(f"{path.name}:{line_number}:{item}" for item in _sensitive_paths(record))
    status = "PASS" if not malformed_lines and not invalid_dates and not sensitive_paths else "FAIL"
    if not files:
        status = "READY_NO_RUNTIME_RECORDS"
    return {
        "status": status,
        "journal_root": str(journal_root),
        "file_count": len(files),
        "record_count": total_records,
        "records_by_file": dict(file_counts),
        "malformed_lines": malformed_lines,
        "invalid_date_filenames": invalid_dates,
        "sensitive_key_paths": sorted(sensitive_paths),
        "retention": {
            "runtime_state_ring_rows": 5000,
            "journal": "append-only JSONL partitioned by UTC decision date",
            "maximum_record_bytes": 131072,
        },
        "historical_strategy_recovery": "NOT_PROVEN_BY_THIS_JOURNAL",
        "generated_at_utc": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


def _markdown(payload: dict[str, Any]) -> str:
    lines = [
        "# Prospective Decision Audit Journal",
        "",
        f"- Status: **{payload['status']}**",
        f"- Journal files: `{payload['file_count']}`",
        f"- Valid decision records: `{payload['record_count']}`",
        f"- Malformed lines: `{payload['malformed_lines']}`",
        f"- Sensitive key paths: `{len(payload['sensitive_key_paths'])}`",
        "",
        "## Purpose",
        "",
        "This journal preserves future robot observations before order cancellation or submission. The compact runtime state keeps the latest 5,000 records; this UTC-partitioned JSONL journal is append-only and retained under ignored `quant/outputs/`.",
        "",
        "## Files",
        "",
    ]
    if payload["records_by_file"]:
        lines.extend(f"- `{name}`: `{count}` records" for name, count in payload["records_by_file"].items())
    else:
        lines.append("- No Demo decision records have been captured yet.")
    lines.extend([
        "",
        "## Safety boundary",
        "",
        "- Records are allowlisted market context, strategy features, and model output only.",
        "- Sensitive key names, non-JSON values, invalid timestamps, and oversized records are rejected before append.",
        "- This journal is prospective evidence only; it does not recover missing historical pre-action context or prove exact strategy recovery.",
        "- No model promotion, new Demo order, private credential, or mainnet connection is performed by this audit.",
        "",
    ])
    return "\n".join(lines)


def main() -> int:
    payload = audit_journal()
    REPORT_JSON.parent.mkdir(parents=True, exist_ok=True)
    REPORT_JSON.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    REPORT_MD.write_text(_markdown(payload), encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False))
    return 0 if payload["status"] in {"PASS", "READY_NO_RUNTIME_RECORDS"} else 2


if __name__ == "__main__":
    sys.exit(main())
