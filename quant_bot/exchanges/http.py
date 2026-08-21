from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol


class AdapterError(RuntimeError):
    def __init__(self, exchange: str, code: str, message: str, *, retryable: bool = False) -> None:
        super().__init__(f"{exchange}:{code}:{message}")
        self.exchange = exchange
        self.code = code
        self.retryable = retryable


class Transport(Protocol):
    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None, private: bool = False) -> dict[str, Any]: ...


@dataclass
class FakeTransport:
    responses: dict[tuple[str, str], dict[str, Any]]
    calls: list[tuple[str, str, bool, dict[str, Any] | None]] = field(default_factory=list)

    def request(self, method: str, path: str, *, body: dict[str, Any] | None = None, private: bool = False) -> dict[str, Any]:
        self.calls.append((method, path, private, body))
        return self.responses[(method.upper(), path)]
