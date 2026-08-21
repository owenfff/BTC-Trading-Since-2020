from __future__ import annotations

from datetime import datetime, timezone


def market_data_is_fresh(last_timestamp: datetime, now: datetime, stale_after_seconds: int) -> bool:
    if last_timestamp.tzinfo is None or now.tzinfo is None:
        raise ValueError("timestamps must be timezone-aware")
    age = (now.astimezone(timezone.utc) - last_timestamp.astimezone(timezone.utc)).total_seconds()
    return age <= stale_after_seconds
