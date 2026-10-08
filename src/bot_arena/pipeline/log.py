"""The ordered event log every service reads and appends to.

Production uses one single-partition Redpanda topic (Kafka only orders messages within a
partition). Tests and quick replays use MemoryLog. Both behave the same.
"""

from collections.abc import Iterator
from typing import Protocol

from bot_arena.pipeline.events import Event


class EventLog(Protocol):
    def append(self, event: Event) -> None: ...

    def end_offset(self) -> int:
        """Offset the next appended event will get (= number of events so far)."""
        ...

    def read(
        self, start: int = 0, stop: int | None = None, follow: bool = False
    ) -> Iterator[tuple[int, Event]]:
        """Events from `start` (inclusive) to `stop` (exclusive; None = current end).

        With `follow=True`, keeps waiting for new events forever and ignores `stop`.
        """
        ...


class MemoryLog:
    def __init__(self, events: list[Event] | None = None):
        self.events: list[Event] = list(events or [])

    def append(self, event: Event) -> None:
        self.events.append(event)

    def end_offset(self) -> int:
        return len(self.events)

    def read(
        self, start: int = 0, stop: int | None = None, follow: bool = False
    ) -> Iterator[tuple[int, Event]]:
        if follow:
            raise NotImplementedError("MemoryLog can't wait for new events; use Pipeline to drive services")
        stop = len(self.events) if stop is None else stop
        for offset in range(start, stop):
            yield offset, self.events[offset]
