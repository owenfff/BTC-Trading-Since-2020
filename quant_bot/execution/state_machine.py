from __future__ import annotations

from enum import StrEnum


class OrderLifecycle(StrEnum):
    CREATED = "CREATED"
    SUBMITTED = "SUBMITTED"
    OPEN = "OPEN"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_REQUESTED = "CANCEL_REQUESTED"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


ALLOWED_TRANSITIONS = {
    OrderLifecycle.CREATED: {OrderLifecycle.SUBMITTED, OrderLifecycle.REJECTED},
    OrderLifecycle.SUBMITTED: {OrderLifecycle.OPEN, OrderLifecycle.PARTIALLY_FILLED, OrderLifecycle.FILLED, OrderLifecycle.REJECTED, OrderLifecycle.UNKNOWN},
    OrderLifecycle.OPEN: {OrderLifecycle.PARTIALLY_FILLED, OrderLifecycle.FILLED, OrderLifecycle.CANCEL_REQUESTED, OrderLifecycle.UNKNOWN},
    OrderLifecycle.PARTIALLY_FILLED: {OrderLifecycle.PARTIALLY_FILLED, OrderLifecycle.FILLED, OrderLifecycle.CANCEL_REQUESTED, OrderLifecycle.UNKNOWN},
    OrderLifecycle.CANCEL_REQUESTED: {OrderLifecycle.CANCELED, OrderLifecycle.PARTIALLY_FILLED, OrderLifecycle.FILLED, OrderLifecycle.UNKNOWN},
    OrderLifecycle.UNKNOWN: {OrderLifecycle.OPEN, OrderLifecycle.PARTIALLY_FILLED, OrderLifecycle.FILLED, OrderLifecycle.CANCELED, OrderLifecycle.REJECTED},
}


def transition(current: OrderLifecycle, next_state: OrderLifecycle) -> OrderLifecycle:
    if next_state not in ALLOWED_TRANSITIONS.get(current, set()):
        raise ValueError(f"invalid order transition: {current} -> {next_state}")
    return next_state
