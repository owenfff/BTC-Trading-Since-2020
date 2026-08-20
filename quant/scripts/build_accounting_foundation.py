#!/usr/bin/env python3
"""Freeze the downstream dual-ledger accounting boundary."""

from __future__ import annotations

import json
import subprocess
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


def git_value(args: list[str]) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def run(root: Path = ROOT) -> dict[str, object]:
    analysis_commit = git_value(["rev-parse", "HEAD"])
    branch = git_value(["branch", "--show-current"])
    manifest = build_accounting_foundation_manifest(root, analysis_commit=analysis_commit, analysis_branch=branch)
    reports = root / "quant" / "reports"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "accounting_foundation_manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (reports / "accounting_foundation_manifest.md").write_text(render_accounting_foundation_markdown(manifest), encoding="utf-8")
    return manifest


if __name__ == "__main__":
    result = run()
    print(f"accounting_status={result['accounting_status']}")
    print(f"downstream_behavioral_research_status={result['downstream_behavioral_research_status']}")
    print(f"analysis_commit={result['analysis_commit']}")
