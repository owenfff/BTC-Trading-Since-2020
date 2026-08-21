from __future__ import annotations

from pathlib import Path

from quant.scripts import run_quant_research


def test_research_preflight_fails_closed_when_inputs_are_missing(monkeypatch, tmp_path: Path, capsys) -> None:
    missing = tuple(tmp_path / name for name in ("bars.csv", "context.csv", "decisions.csv", "actions.csv", "cycles.csv"))
    monkeypatch.setattr(run_quant_research, "RESEARCH_INPUTS", missing)

    assert run_quant_research.main() == 2
    output = capsys.readouterr().out
    assert '"status": "BLOCKED_INPUTS_MISSING"' in output
    assert '"quant_research_runnable": false' in output
