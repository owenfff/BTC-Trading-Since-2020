from __future__ import annotations

from quant_bot.domain.events import DomainEvent


class InMemoryEventStore:
    def __init__(self) -> None:
        self._events: dict[str, DomainEvent] = {}

    def append(self, event: DomainEvent) -> bool:
        if event.id in self._events:
            return False
        self._events[event.id] = event
        return True

    def get(self, event_id: str) -> DomainEvent | None:
        return self._events.get(event_id)

    def all(self) -> tuple[DomainEvent, ...]:
        return tuple(self._events.values())
