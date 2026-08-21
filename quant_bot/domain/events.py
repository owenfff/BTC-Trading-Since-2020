from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .common import canonical_symbol, utc_datetime


EVENT_NAMESPACE = uuid.UUID("0f936d16-0aa5-5c07-9dc0-9848a2a9bb5f")


def event_id(event_type: str, client_order_id: str, payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return str(uuid.uuid5(EVENT_NAMESPACE, f"{event_type}|{client_order_id}|{canonical}"))


@dataclass(frozen=True)
class DomainEvent:
    id: str
    event_type: str
    timestamp: datetime
    symbol: str
    payload: dict[str, Any]

    def __post_init__(self) -> None:
        if not self.id or not self.event_type:
            raise ValueError("event id and type are required")
        object.__setattr__(self, "timestamp", utc_datetime(self.timestamp))
        object.__setattr__(self, "symbol", canonical_symbol(self.symbol))
