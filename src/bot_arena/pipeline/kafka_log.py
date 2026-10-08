"""The event log on Redpanda (Kafka API): one topic with exactly one partition.

Kafka only keeps messages in order within a partition, and the arena depends on that order,
so the topic must have a single partition. Offsets are the Kafka offsets of that partition;
a fresh topic starts at 0, the same as MemoryLog.
"""

import os
import uuid
from collections.abc import Iterator

from confluent_kafka import Consumer, KafkaError, KafkaException, Producer, TopicPartition
from confluent_kafka.admin import AdminClient, NewTopic
from dotenv import load_dotenv

from bot_arena.pipeline.events import Event

DEFAULT_TOPIC = "arena.paper"
TIMEOUT = 10.0  # seconds, for admin calls and appends


def brokers() -> str:
    load_dotenv()
    return os.getenv("KAFKA_BROKERS", "localhost:9092")


def default_topic() -> str:
    load_dotenv()
    return os.getenv("ARENA_TOPIC", DEFAULT_TOPIC)


class KafkaLog:
    def __init__(self, topic: str | None = None, bootstrap: str | None = None):
        self.topic = topic or default_topic()
        self.bootstrap = bootstrap or brokers()
        ensure_topic(self.topic, self.bootstrap)
        self._producer = Producer(
            {"bootstrap.servers": self.bootstrap, "enable.idempotence": True, "acks": "all", "linger.ms": 0}
        )
        # One consumer just for watermark lookups.
        self._meta = _consumer(self.bootstrap)

    def append(self, event: Event) -> None:
        """Blocks until the broker has stored the event, so a following read() will see it."""
        errors: list[KafkaError] = []

        def on_delivery(err, _msg):
            if err is not None:
                errors.append(err)

        self._producer.produce(
            self.topic, key=event.key.encode(), value=event.to_json(), partition=0, on_delivery=on_delivery
        )
        remaining = self._producer.flush(TIMEOUT)
        if remaining:
            raise KafkaException(f"timed out appending {event.id} to {self.topic}")
        if errors:
            raise KafkaException(errors[0])

    def end_offset(self) -> int:
        _low, high = self._meta.get_watermark_offsets(TopicPartition(self.topic, 0), timeout=TIMEOUT)
        return high

    def read(
        self, start: int = 0, stop: int | None = None, follow: bool = False
    ) -> Iterator[tuple[int, Event]]:
        if not follow:
            stop = self.end_offset() if stop is None else stop
            if start >= stop:
                return
        consumer = _consumer(self.bootstrap)
        try:
            consumer.assign([TopicPartition(self.topic, 0, start)])
            while True:
                msg = consumer.poll(1.0)
                if msg is None:
                    continue
                if msg.error():
                    if msg.error().code() == KafkaError._PARTITION_EOF:
                        continue
                    raise KafkaException(msg.error())
                offset = msg.offset()
                if not follow and offset >= stop:
                    return
                yield offset, Event.from_json(msg.value())
                if not follow and offset + 1 >= stop:
                    return
        finally:
            consumer.close()

    def close(self) -> None:
        self._producer.flush(TIMEOUT)
        self._meta.close()


def ensure_topic(topic: str, bootstrap: str | None = None) -> None:
    """Create the topic with one partition (kept forever) if missing; refuse one with more partitions."""
    admin = AdminClient({"bootstrap.servers": bootstrap or brokers()})
    existing = admin.list_topics(timeout=TIMEOUT).topics
    if topic in existing:
        partitions = len(existing[topic].partitions)
        if partitions != 1:
            raise RuntimeError(
                f"topic {topic!r} has {partitions} partitions; the arena log needs exactly 1 to stay ordered"
            )
        return
    new = NewTopic(
        topic,
        num_partitions=1,
        replication_factor=1,
        config={"retention.ms": "-1", "cleanup.policy": "delete"},
    )
    for future in admin.create_topics([new], operation_timeout=TIMEOUT).values():
        try:
            future.result()
        except KafkaException as exc:
            if exc.args[0].code() != KafkaError.TOPIC_ALREADY_EXISTS:  # lost a creation race: fine
                raise


def delete_topic(topic: str, bootstrap: str | None = None) -> None:
    """Delete a topic (for throwaway replays and tests). Missing topics are ignored."""
    admin = AdminClient({"bootstrap.servers": bootstrap or brokers()})
    for future in admin.delete_topics([topic], operation_timeout=TIMEOUT).values():
        try:
            future.result()
        except KafkaException as exc:
            if exc.args[0].code() != KafkaError.UNKNOWN_TOPIC_OR_PART:
                raise


def _consumer(bootstrap: str) -> Consumer:
    # Offsets are managed by hand (assign + start offset), so the group never matters.
    return Consumer(
        {
            "bootstrap.servers": bootstrap,
            "group.id": f"arena-reader-{uuid.uuid4().hex}",
            "enable.auto.commit": False,
            "enable.partition.eof": False,
            "auto.offset.reset": "earliest",
        }
    )
