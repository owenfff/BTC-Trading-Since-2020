from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class DecisionAuditJournalError(ValueError):
    """Raised when a prospective decision record is unsafe or malformed."""


_DATE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})T")
_SENSITIVE_KEY_PARTS = (
    "api_key",
    "api_secret",
    "access_token",
    "credential",
    "passphrase",
    "private_key",
    "secret",
)


def _assert_safe_keys(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, Mapping):
        for raw_key, child in value.items():
            key = str(raw_key)
            normalized = key.lower().replace("-", "_")
            if any(part in normalized for part in _SENSITIVE_KEY_PARTS):
                location = ".".join((*path, key))
                raise DecisionAuditJournalError(f"sensitive key is not allowed: {location}")
            _assert_safe_keys(child, (*path, key))
    elif isinstance(value, (list, tuple)):
        for index, child in enumerate(value):
            _assert_safe_keys(child, (*path, str(index)))


@dataclass(frozen=True)
class DecisionAuditJournal:
    """Append-only, credential-free journal for future decision evidence.

    The journal is deliberately separate from the compact runtime state file.
    One UTC date per JSONL file makes long Demo observations recoverable without
    allowing the state snapshot to grow without limit.
    """

    root: Path
    max_record_bytes: int = 128 * 1024

    def path_for(self, decision_time: str) -> Path:
        match = _DATE_RE.match(str(decision_time))
        if not match:
            raise DecisionAuditJournalError("decision_time must be an ISO-8601 timestamp")
        return self.root / f"decision_audit_{match.group(1)}.jsonl"

    def append(self, record: Mapping[str, Any]) -> Path:
        if not isinstance(record, Mapping):
            raise DecisionAuditJournalError("decision record must be a mapping")
        _assert_safe_keys(record)
        decision_time = record.get("decision_time")
        path = self.path_for(str(decision_time))
        try:
            serialized = json.dumps(
                dict(record),
                ensure_ascii=False,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as error:
            raise DecisionAuditJournalError(f"decision record is not JSON-safe: {error}") from error
        if len(serialized.encode("utf-8")) > self.max_record_bytes:
            raise DecisionAuditJournalError(
                f"decision record exceeds {self.max_record_bytes} bytes"
            )
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(serialized)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
        except OSError as error:
            raise DecisionAuditJournalError(f"cannot append decision journal: {error}") from error
        return path


__all__ = ["DecisionAuditJournal", "DecisionAuditJournalError"]
