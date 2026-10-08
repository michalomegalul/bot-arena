"""Running a service against the log, including restarts.

A service is a `handle(event) -> list[Event]` function with state. On (re)start it reads the
whole log to rebuild that state. Outputs it would have produced for old events are usually
already in the log, so only the missing ones (e.g. lost in a crash) get appended.
"""

from collections.abc import Mapping
from typing import Protocol

from bot_arena.pipeline.events import Event
from bot_arena.pipeline.log import EventLog


class Service(Protocol):
    name: str
    # Everything in the log at startup, by event id. Lets a service reuse its own past
    # decisions instead of recomputing them (which matters once a decision costs a Claude call).
    recorded: Mapping[str, Event]

    def handle(self, event: Event) -> list[Event]: ...


def catch_up(service: Service, log: EventLog) -> int:
    """Rebuild state from the log and append any outputs that are missing. Returns the next offset."""
    end = log.end_offset()
    service.recorded = {event.id: event for _, event in log.read(0, end)}
    missing: dict[str, Event] = {}
    for _, event in log.read(0, end):
        for out in service.handle(event):
            if out.id not in service.recorded:
                missing[out.id] = out
    for out in missing.values():
        log.append(out)
    return end


def run_forever(service: Service, log: EventLog) -> None:
    """Catch up, then handle new events as they arrive. Own outputs come back and are ignored by id."""
    start = catch_up(service, log)
    seen = set(service.recorded)
    for _, event in log.read(start, follow=True):
        if event.id in seen:
            continue
        seen.add(event.id)
        for out in service.handle(event):
            if out.id not in seen:
                log.append(out)
