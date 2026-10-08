"""KafkaLog against a real Redpanda. Skipped unless KAFKA_BROKERS is set (it is in CI)."""

import os
import threading
import uuid

import pytest

if not os.getenv("KAFKA_BROKERS"):
    pytest.skip("KAFKA_BROKERS not set", allow_module_level=True)

from confluent_kafka.admin import AdminClient, NewTopic

from bot_arena.pipeline import events as ev
from bot_arena.pipeline.kafka_log import KafkaLog, delete_topic
from bot_arena.pipeline.runner import catch_up

BROKERS = os.environ["KAFKA_BROKERS"]


@pytest.fixture
def topic():
    name = f"arena.test.{uuid.uuid4().hex[:12]}"
    yield name
    delete_topic(name, BROKERS)


@pytest.fixture
def log(topic):
    log = KafkaLog(topic, BROKERS)
    yield log
    log.close()


def sample(n: int) -> list[ev.Event]:
    return [ev.bar(f"S{i % 3}", f"2026-01-{i + 1:02d}", 100.0 + i / 3, 101.25 + i) for i in range(n)]


def test_append_and_read_round_trip_in_order(log):
    events = sample(5) + [ev.close("2026-01-05", ["S0", "S1", "S2"])]
    for e in events:
        log.append(e)
    assert log.end_offset() == len(events)
    read = list(log.read())
    assert [offset for offset, _ in read] == list(range(len(events)))
    assert [e for _, e in read] == events  # exact equality, floats included


def test_read_slices_by_offset(log):
    events = sample(6)
    for e in events:
        log.append(e)
    assert [e for _, e in log.read(2, 5)] == events[2:5]
    assert list(log.read(6)) == []
    assert list(log.read(3, 3)) == []


def test_empty_topic(log):
    assert log.end_offset() == 0
    assert list(log.read()) == []


def test_follow_sees_events_appended_later(log):
    log.append(sample(1)[0])
    received: list[ev.Event] = []
    done = threading.Event()

    def reader():
        for _, e in log.read(0, follow=True):
            received.append(e)
            if len(received) == 2:
                done.set()
                return

    thread = threading.Thread(target=reader, daemon=True)
    thread.start()
    late = ev.close("2026-01-01", ["S0"])
    KafkaLog(log.topic, BROKERS).append(late)  # from another producer
    assert done.wait(timeout=30), "follow mode never delivered the late event"
    assert received[1] == late


def test_refuses_a_topic_with_several_partitions(topic):
    admin = AdminClient({"bootstrap.servers": BROKERS})
    for f in admin.create_topics([NewTopic(topic, num_partitions=3, replication_factor=1)]).values():
        f.result()
    with pytest.raises(RuntimeError, match="exactly 1"):
        KafkaLog(topic, BROKERS)


class Echo:
    """Answers every bar with a decision, like a minimal bot."""

    name = "echo"

    def __init__(self):
        self.recorded = {}

    def handle(self, event):
        if event.type != ev.BAR:
            return []
        return [ev.decision("echo", event.date, {event.key: 0.5}, "active")]


def test_catch_up_appends_missing_outputs_once(log):
    for e in sample(3):
        log.append(e)
    catch_up(Echo(), log)
    assert [e.type for _, e in log.read()] == [ev.BAR] * 3 + [ev.DECISION] * 3

    # A restart (new instance) finds every output already in the log: nothing new.
    catch_up(Echo(), log)
    assert log.end_offset() == 6

    # New input while "down": only its answer is added.
    log.append(ev.bar("S9", "2026-02-01", 1.0, 2.0))
    catch_up(Echo(), log)
    decisions = [e for _, e in log.read() if e.type == ev.DECISION]
    assert len(decisions) == 4 and len({d.id for d in decisions}) == 4
