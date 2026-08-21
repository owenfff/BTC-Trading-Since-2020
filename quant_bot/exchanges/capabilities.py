from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ExchangeCapabilities:
    exchange: str
    rest_public: bool
    rest_private: bool
    websocket_public: bool
    websocket_private: bool
    demo_or_testnet: str
    supports_spot: bool
    supports_linear: bool
    supports_inverse: bool
    notes: str = ""
