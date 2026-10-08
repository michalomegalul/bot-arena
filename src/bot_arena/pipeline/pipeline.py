"""Driving services over a log, and replaying history through them.

In production every service is its own process following the Redpanda log. Here they run
in one process, taking turns until nobody has anything left to do. Same services, same log
order, so the result is identical.
"""

from collections.abc import Iterable, Iterator

import pandas as pd

from bot_arena.pipeline import events as ev
from bot_arena.pipeline.events import Event
from bot_arena.pipeline.log import EventLog, MemoryLog
from bot_arena.pipeline.runner import Service, catch_up


class Pipeline:
    def __init__(self, log: EventLog, services: list[Service]):
        self.log = log
        self.services = services
        self.cursors = {id(s): catch_up(s, log) for s in services}
        self.seen = {id(s): set(s.recorded) for s in services}

    def append(self, events: Iterable[Event]) -> None:
        for event in events:
            self.log.append(event)

    def drain(self) -> None:
        """Let every service handle every event, until the log stops growing."""
        progress = True
        while progress:
            progress = False
            for service in self.services:
                key = id(service)
                for offset, event in self.log.read(self.cursors[key]):
                    self.cursors[key] = offset + 1
                    progress = True
                    if event.id in self.seen[key]:
                        continue
                    self.seen[key].add(event.id)
                    for out in service.handle(event):
                        if out.id not in self.seen[key]:
                            self.log.append(out)


def history_days(opens: pd.DataFrame, closes: pd.DataFrame) -> Iterator[tuple[str, list[Event]]]:
    """Turn price tables into one (day, [bar events..., close event]) per trading day."""
    for ts in closes.index:
        day = ev.day(ts)
        symbols = [s for s in sorted(closes.columns) if not pd.isna(closes.at[ts, s])]
        bars = [ev.bar(s, day, opens.at[ts, s], closes.at[ts, s]) for s in symbols]
        yield day, [*bars, ev.close(day, symbols)]


def replay(
    services: list[Service],
    opens: pd.DataFrame,
    closes: pd.DataFrame,
    run_event: Event,
    log: EventLog | None = None,
) -> EventLog:
    """Feed history through the services one day at a time, letting them finish each day."""
    pipeline = Pipeline(log or MemoryLog(), services)
    pipeline.append([run_event])
    pipeline.drain()
    for _, day_events in history_days(opens, closes):
        pipeline.append(day_events)
        pipeline.drain()
    return pipeline.log


def equity_curves(log: EventLog) -> dict[str, pd.Series]:
    """Each bot's end-of-day equity, from the portfolio events in the log."""
    points: dict[str, dict[pd.Timestamp, float]] = {}
    for _, event in log.read():
        if event.type == ev.PORTFOLIO:
            points.setdefault(event.key, {})[event.timestamp] = event.data["equity"]
    return {bot: pd.Series(values) for bot, values in points.items()}


def statuses(log: EventLog) -> dict[str, str]:
    out = {}
    for _, event in log.read():
        if event.type == ev.DECISION:
            out[event.key] = event.data["status"]
    return out
