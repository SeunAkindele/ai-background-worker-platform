from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.core.queue import PriorityJobQueue
from app.models.job import JobPriority


@pytest.fixture
def queue():
    return PriorityJobQueue()


def test_high_priority_dequeues_before_normal(queue):
    high_id = uuid4()
    normal_id = uuid4()
    now = datetime.now(timezone.utc)

    queue.enqueue(normal_id, priority=JobPriority.NORMAL, created_at=now)
    queue.enqueue(high_id, priority=JobPriority.HIGH, created_at=now)

    assert queue.dequeue() == high_id
    assert queue.dequeue() == normal_id


def test_same_priority_fifo_by_created_at(queue):
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