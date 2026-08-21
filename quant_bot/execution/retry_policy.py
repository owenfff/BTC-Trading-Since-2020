from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class RetryAction(StrEnum):
    QUERY_ORDER = "QUERY_ORDER"
    RETRY_SUBMIT = "RETRY_SUBMIT"
    STOP = "STOP"


@dataclass(frozen=True)
class RetryContext:
    attempts: int
    max_attempts: int = 3
    request_timed_out: bool = False
    order_state_known: bool = False
    order_rejected: bool = False


def decide_retry(context: RetryContext) -> RetryAction:
    if context.request_timed_out and not context.order_state_known:
        return RetryAction.QUERY_ORDER
    if context.order_rejected and context.attempts < context.max_attempts:
        return RetryAction.RETRY_SUBMIT
    return RetryAction.STOP
