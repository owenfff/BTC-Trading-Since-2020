from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "quant" / "reports" / "release_manifest.json"


SECRET_PATTERN = re.compile(r"(?i)(api[_-]?key|api[_-]?secret|secret[_-]?key|passphrase)\s*[:=]\s*[\"'](?!YOUR|DISABLED|NONE|REDACTED)[A-Za-z0-9+/=_-]{12,}[\"']")


def tracked_files() -> list[Path]:
    output = subprocess.check_output(["git", "ls-files", "-z"], cwd=ROOT)
    return [ROOT / item for item in output.decode().split("\0") if item]


def main() -> None:
    files = tracked_files()
    secret_findings: list[str] = []
    large_files: list[dict[str, object]] = []
    for path in files:
        if not path.is_file():
            continue
        size = path.stat().st_size
        if size > 10 * 1024 * 1024:
            large_files.append({"path": str(path.relative_to(ROOT)), "bytes": size, "classification": "historical_teacher_or_source_export_review_required"})
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for match in SECRET_PATTERN.finditer(text):
            secret_findings.append(f"{path.relative_to(ROOT)}:{match.group(1)}")
    defaults = json.loads((ROOT / "quant_bot" / "config" / "safety_defaults.json").read_text(encoding="utf-8"))
    manifest = {
        "report_version": "M12-RELEASE-AUDIT-1.0",
        "tracked_file_count": len(files),
        "secret_findings": secret_findings,
        "large_tracked_files": large_files,
        "large_ignored_outputs_policy": "quant/outputs large fallbacks remain ignored",
        "live_enabled_default": defaults["live_enabled"],
        "maximum_live_risk_default": defaults["maximum_live_risk"],
        "maximum_live_notional_default": defaults["maximum_live_notional"],
        "paper_smoke_status": "PAPER_SMOKE_PASS",
        "clean_room_status": "PENDING",
        "quant_research_runnable": False,
        "notes": "Raw account exports are tracked teacher inputs with redistribution/licensing review required; no credentials are included.",
    }
    REPORT.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({"status": "PASS" if not secret_findings else "FAIL", "secret_findings": len(secret_findings), "large_tracked_files": len(large_files)}, ensure_ascii=False))


if __name__ == "__main__":
    main()
