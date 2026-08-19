from __future__ import annotations

import csv
import hashlib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterator


def clean(value: Any) -> str:
    return "" if value is None else str(value)


def is_missing(value: Any) -> bool:
    return clean(value).strip() == ""


def parse_int(value: Any) -> int | None:
    if is_missing(value):
        return None
    try:
        number = Decimal(clean(value).strip())
    except InvalidOperation:
        return None
    if not number.is_finite() or number != number.to_integral_value():
        return None
    return int(number)


def parse_float(value: Any) -> float | None:
    if is_missing(value):
        return None
    try:
        number = float(clean(value).strip())
    except (TypeError, ValueError):
        return None
    return number if number == number and number not in (float("inf"), float("-inf")) else None


def parse_datetime(value: Any) -> datetime | None:
    if is_missing(value):
        return None
    raw = clean(value).strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed.astimezone(timezone.utc)


def iso_datetime(value: datetime | None) -> str:
    if value is None:
        return ""
    text = value.astimezone(timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")
    if "." in text:
        prefix, fraction = text[:-1].split(".", 1)
        fraction = fraction.rstrip("0")
        text = f"{prefix}.{fraction}Z" if fraction else f"{prefix}Z"
    return text


def read_csv_header(path: Path) -> list[str]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        try:
            return [clean(value).strip() for value in next(reader)]
        except StopIteration:
            return []


def iter_csv_dicts(path: Path) -> Iterator[tuple[int, dict[str, str]]]:
    """Stream CSV rows and return physical file line numbers (header is line 1)."""

    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames is None:
            return
        for line_number, row in enumerate(reader, start=2):
            yield line_number, {key: clean(value) for key, value in row.items() if key is not None}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def hash_files(root: Path, filenames: list[str]) -> dict[str, str]:
    return {filename: sha256_file(root / filename) for filename in filenames}
