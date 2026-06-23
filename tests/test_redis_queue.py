from datetime import datetime, timezone
from uuid import uuid4

from app.core.queue import RedisJobQueue
from app.models.job import JobPriority


def test_high_priority_dequeues_before_normal(fake_redis):
    queue = RedisJobQueue(client=fake_redis)
    high_id = uuid4()
    normal_id = uuid4()
    now = datetime.now(timezone.utc)

    queue.enqueue(normal_id, priority=JobPriority.NORMAL, created_at=now)
    queue.enqueue(high_id, priority=JobPriority.HIGH, created_at=now)

    assert queue.dequeue() == high_id
    assert queue.dequeue() == normal_id


def test_same_priority_fifo_by_created_at(fake_redis):
    queue = RedisJobQueue(client=fake_redis)
    older_id = uuid4()
    newer_id = uuid4()

    queue.enqueue(
        newer_id,
        priority=JobPriority.NORMAL,
        created_at=datetime(2025, 1, 2, tzinfo=timezone.utc),
    )
    queue.enqueue(
        older_id,
        priority=JobPriority.NORMAL,
        created_at=datetime(2025, 1, 1, tzinfo=timezone.utc),
    )

    assert queue.dequeue() == older_id
    assert queue.dequeue() == newer_id


def test_queue_survives_new_client_instance(fake_redis):
    """Simulates API enqueue + separate worker dequeue (different objects, same Redis)."""
    q1 = RedisJobQueue(client=fake_redis)
    q2 = RedisJobQueue(client=fake_redis)
    job_id = uuid4()
    now = datetime.now(timezone.utc)

    q1.enqueue(job_id, priority=JobPriority.NORMAL, created_at=now)
    assert q1.size() == 1

    assert q2.dequeue() == job_id
    assert q2.size() == 0
