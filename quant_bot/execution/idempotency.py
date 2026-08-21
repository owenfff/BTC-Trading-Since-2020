from __future__ import annotations

import uuid
from decimal import Decimal


NAMESPACE = uuid.UUID("f5bb8c1e-7b7e-5d37-bdc1-1ab0f6f5d7d2")


def client_order_id(strategy_version: str, signal_timestamp: str, symbol: str, side: str, quantity: Decimal) -> str:
    value = f"{strategy_version}|{signal_timestamp}|{symbol.upper()}|{side.upper()}|{quantity}"
    return f"cb-{uuid.uuid5(NAMESPACE, value).hex[:24]}"
