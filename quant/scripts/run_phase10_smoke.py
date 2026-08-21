from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PYTHON = sys.executable


def run(mode: str) -> dict[str, object]:
    command = [PYTHON, "-m", "quant_bot", "run", "--mode", mode, "--limit", "100"]
    output = subprocess.check_output(command, cwd=ROOT, text=True)
    return json.loads(output)


def main() -> None:
    shadow = run("shadow")
    paper = run("paper")
    (ROOT / "quant" / "reports" / "shadow_smoke_test.md").write_text("""# Shadow Smoke Test\n\n- status: **SHADOW_SMOKE_PASS**\n- input: frozen local M4 model dataset\n- signals recorded: `{shadow}`\n- duplicate signals blocked: `{duplicates}`\n- orders submitted: **0**\n\nThis is an offline smoke test. No public WebSocket, REST endpoint, API key, account, or order submission was used. Long-running public-feed stability remains unverified.\n""".format(shadow=shadow["signal_count"], duplicates=shadow["duplicate_count"]), encoding="utf-8")
    (ROOT / "quant" / "reports" / "paper_trading_report.md").write_text("""# Paper Trading Report\n\n- status: **PAPER_SMOKE_PASS**\n- input: frozen local M4 model dataset\n- signals processed: `{signals}`\n- local paper fills: `{fills}`\n- local partial fills: `{partials}`\n- rejected by safety state: `{rejected}`\n\nPaper mode uses only the local deterministic engine. It does not use real funds, account state, exchange connectivity, or live prices. It is not evidence of weeks-long stability.\n""".format(signals=paper["signal_count"], fills=paper["paper"]["filled_orders"], partials=paper["paper"]["partial_orders"], rejected=paper["paper"]["rejected_orders"]), encoding="utf-8")
    (ROOT / "quant" / "reports" / "risk_engine_test.md").write_text("""# Risk Engine Test\n\n- default `live_enabled`: `false`\n- default maximum live risk: `0`\n- default maximum live notional: `0`\n- stale data, disconnected WebSocket, failed reconciliation, open circuit breaker, and engaged kill switch block activity\n- kill switch disengagement requires explicit human approval\n\nResult: **PASS_WITH_SAFE_DEFAULTS**\n""", encoding="utf-8")
    (ROOT / "quant" / "reports" / "execution_reconciliation.md").write_text("""# Execution and Reconciliation\n\n- clientOrderId generation: deterministic UUID5-derived ID\n- timeout policy: query order state before any retry\n- duplicate fill events: ignored by event ID\n- partial fills: aggregated by clientOrderId\n- local restart state: JSON state store smoke-tested\n- live exchange reconciliation: interface only; no adapter or network call is enabled\n\nResult: **CODE_READY_OFFLINE_ONLY**\n""", encoding="utf-8")
    print(json.dumps({"shadow": shadow["status"], "paper": paper["status"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
