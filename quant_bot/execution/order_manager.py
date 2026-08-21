from __future__ import annotations

from dataclasses import dataclass

from .retry_policy import RetryAction, RetryContext, decide_retry
from .state_machine import OrderLifecycle, transition
from quant_bot.domain.order import Order


@dataclass
class ManagedOrder:
    order: Order
    state: OrderLifecycle = OrderLifecycle.CREATED
    exchange_order_id: str | None = None
    query_required: bool = False


class OrderManager:
    """Local lifecycle manager; an adapter is required for any external I/O."""

    def __init__(self) -> None:
        self.orders: dict[str, ManagedOrder] = {}

    def register(self, order: Order) -> ManagedOrder:
        if order.client_order_id in self.orders:
            return self.orders[order.client_order_id]
        managed = ManagedOrder(order)
        self.orders[order.client_order_id] = managed
        return managed

    def mark_submitted(self, client_order_id: str, exchange_order_id: str | None = None) -> ManagedOrder:
        managed = self.orders[client_order_id]
        managed.state = transition(managed.state, OrderLifecycle.SUBMITTED)
        managed.exchange_order_id = exchange_order_id
        return managed

    def on_timeout(self, client_order_id: str, attempts: int = 0) -> RetryAction:
        managed = self.orders[client_order_id]
        managed.state = transition(managed.state, OrderLifecycle.UNKNOWN)
        managed.query_required = True
        return decide_retry(RetryContext(attempts=attempts, request_timed_out=True, order_state_known=False))

    def apply_query_state(self, client_order_id: str, state: OrderLifecycle) -> ManagedOrder:
        managed = self.orders[client_order_id]
        managed.state = transition(managed.state, state)
        managed.query_required = False
        return managed
