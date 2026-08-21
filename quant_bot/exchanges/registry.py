from __future__ import annotations

from .base import ExchangeAdapter
from .capabilities import ExchangeCapabilities


class ExchangeRegistry:
    def __init__(self) -> None:
        self._adapters: dict[str, ExchangeAdapter] = {}
        self._capabilities: dict[str, ExchangeCapabilities] = {}

    def register(self, name: str, adapter: ExchangeAdapter, capabilities: ExchangeCapabilities) -> None:
        key = name.strip().lower()
        if not key:
            raise ValueError("exchange name is required")
        self._adapters[key] = adapter
        self._capabilities[key] = capabilities

    def adapter(self, name: str) -> ExchangeAdapter:
        return self._adapters[name.strip().lower()]

    def capabilities(self) -> tuple[ExchangeCapabilities, ...]:
        return tuple(self._capabilities.values())
