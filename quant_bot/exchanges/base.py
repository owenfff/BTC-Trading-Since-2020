from __future__ import annotations

from typing import Protocol

from quant_bot.domain.order import Order


class ExchangeAdapter(Protocol):
    """Capability boundary; implementations are intentionally absent in Phase 8."""

    def submit_order(self, order: Order) -> object: ...
    def get_order(self, client_order_id: str) -> object: ...
    def cancel_order(self, client_order_id: str) -> object: ...
    def portfolio_snapshot(self) -> object: ...
