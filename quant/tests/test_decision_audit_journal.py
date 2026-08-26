from __future__ import annotations

import json
from pathlib import Path

import pytest

from quant_bot.decision_audit_journal import DecisionAuditJournal, DecisionAuditJournalError


def _record(timestamp: str = "2026-08-27T01:02:03Z") -> dict[str, object]:
    return {
        "decision_time": timestamp,
        "venue_symbol": "BTC-USDT-SWAP",
        "pre_action": {"features": {"rsi14": "52.1"}},
        "model_output": {"action": "HOLD", "target_exposure": "0"},
    }


def test_journal_appends_jsonl_and_partitions_by_utc_date(tmp_path: Path) -> None:
    journal = DecisionAuditJournal(tmp_path / "decision_audit")

    first_path = journal.append(_record())
    second_path = journal.append(_record("2026-08-28T00:00:00Z"))

    assert first_path.name == "decision_audit_2026-08-27.jsonl"
    assert second_path.name == "decision_audit_2026-08-28.jsonl"
    rows = [json.loads(line) for line in first_path.read_text(encoding="utf-8").splitlines()]
    assert rows == [_record()]


def test_journal_rejects_sensitive_keys_before_writing(tmp_path: Path) -> None:
    journal = DecisionAuditJournal(tmp_path / "decision_audit")

    with pytest.raises(DecisionAuditJournalError, match="sensitive key"):
        journal.append({**_record(), "credentials": {"api_secret": "never-write"}})

    assert not list((tmp_path / "decision_audit").glob("*.jsonl"))


def test_journal_rejects_oversized_records(tmp_path: Path) -> None:
    journal = DecisionAuditJournal(tmp_path / "decision_audit", max_record_bytes=64)

    with pytest.raises(DecisionAuditJournalError, match="exceeds"):
        journal.append(_record())

    assert not list((tmp_path / "decision_audit").glob("*.jsonl"))
