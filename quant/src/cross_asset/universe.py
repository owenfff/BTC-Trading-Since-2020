"""Cross-asset symbol and instrument metadata preparation."""

from __future__ import annotations

import csv
import math
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


UTC = timezone.utc


def parse_utc(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def load_decision_rows(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    for row in rows:
        row["_decision_dt"] = parse_utc(row.get("decision_time"))
    return [row for row in rows if row.get("symbol") and row.get("_decision_dt") is not None]


def split_by_global_time(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ordered = sorted(rows, key=lambda row: (row["_decision_dt"], str(row.get("decision_episode_id", ""))))
    total = len(ordered)
    train_end = max(1, int(total * 0.70))
    validation_end = max(train_end + 1, int(total * 0.85))
    for index, row in enumerate(ordered):
        row["dataset_split"] = "TRAIN" if index < train_end else ("VALIDATION" if index < validation_end else "TEST")
    return ordered


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def fit_position_scales(rows: list[dict[str, Any]]) -> dict[str, float]:
    """Fit per-symbol scales on chronological TRAIN rows only."""
    maxima: defaultdict[str, float] = defaultdict(float)
    for row in rows:
        if row.get("dataset_split") != "TRAIN":
            continue
        symbol = str(row["symbol"])
        for field in ("position_before", "target_position", "position_delta"):
            value = _number(row.get(field))
            if value is not None:
                maxima[symbol] = max(maxima[symbol], abs(value))
    return {symbol: max(1.0, scale) for symbol, scale in maxima.items()}


def _first_nonempty(target: dict[str, Any], key: str, value: Any) -> None:
    if target.get(key) in (None, "") and value not in (None, ""):
        target[key] = value


def load_instrument_metadata(mapping_path: Path, terms_path: Path) -> dict[str, dict[str, Any]]:
    """Read one deterministic historical spec row per symbol.

    The mapping is read in batches so the event-level Parquet artifact is not
    loaded wholesale. The temporal audit contributes the resolved lot size.
    """
    metadata: dict[str, dict[str, Any]] = {}
    try:
        import pyarrow.parquet as pq

        columns = [
            "event_time", "symbol", "instrument_class", "payout_model",
            "quote_currency", "settlement_currency", "multiplier_major",
        ]
        parquet = pq.ParquetFile(mapping_path)
        for batch in parquet.iter_batches(columns=columns, batch_size=25_000):
            for row in batch.to_pylist():
                symbol = str(row.get("symbol") or "")
                if not symbol:
                    continue
                item = metadata.setdefault(symbol, {"symbol": symbol})
                for key in columns:
                    if key != "symbol":
                        _first_nonempty(item, key, row.get(key))
    except (ImportError, OSError, ValueError):
        pass

    if terms_path.exists():
        with terms_path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                symbol = str(row.get("symbol") or "")
                if not symbol:
                    continue
                item = metadata.setdefault(symbol, {"symbol": symbol})
                _first_nonempty(item, "resolved_lot_size", row.get("resolved_lot_size"))
                _first_nonempty(item, "terms_resolution_status", row.get("terms_resolution_status"))

    for item in metadata.values():
        item.setdefault("instrument_class", "UNKNOWN")
        item.setdefault("payout_model", "UNKNOWN")
        item.setdefault("quote_currency", "UNKNOWN")
        item.setdefault("settlement_currency", "UNKNOWN")
        item.setdefault("multiplier_major", "")
        item.setdefault("resolved_lot_size", "")
        item.setdefault("terms_resolution_status", "UNKNOWN")
    return metadata


__all__ = [
    "fit_position_scales",
    "load_decision_rows",
    "load_instrument_metadata",
    "parse_utc",
    "split_by_global_time",
]
