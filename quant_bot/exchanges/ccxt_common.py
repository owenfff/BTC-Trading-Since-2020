from __future__ import annotations

from typing import Any


class CcxtCommonAdapter:
    """Dependency-neutral placeholder for future REST normalization.

    It deliberately has no constructor that accepts credentials and performs
    no network calls. Native adapters remain necessary for private WebSocket,
    position/margin modes, reduce-only, post-only, conditional/batch orders,
    exchange errors, rate limits, and timeout recovery.
    """

    def __init__(self, exchange_name: str) -> None:
        self.exchange_name = exchange_name

    def normalize_public_instrument(self, payload: dict[str, Any]) -> dict[str, Any]:
        return {"exchange": self.exchange_name, "raw": payload}
