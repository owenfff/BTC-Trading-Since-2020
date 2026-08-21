from __future__ import annotations

from dataclasses import dataclass


@dataclass
class CircuitBreaker:
    failure_limit: int = 3
    failures: int = 0
    open: bool = False

    def record_failure(self) -> None:
        self.failures += 1
        if self.failures >= self.failure_limit:
            self.open = True

    def record_success(self) -> None:
        self.failures = 0

    def reset(self) -> None:
        self.failures = 0
        self.open = False
