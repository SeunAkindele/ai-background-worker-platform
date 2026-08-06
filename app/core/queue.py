import json
from datetime import datetime
from uuid import UUID

from app.core.redis_client import redis_client
from app.models.job import PRIORITY_RANK, JobPriority

PENDING_KEY = "jobs:pending"
PROCESSING_KEY = "jobs:processing"
RETRY_KEY = "jobs:retry"
FAILED_KEY = "jobs:failed"

_SCORE_MULTIPLIER = 10**13


def _score(priority: JobPriority, created_at: datetime) -> float:
    rank = PRIORITY_RANK[priority]
    ts = created_at.timestamp()
    return rank * _SCORE_MULTIPLIER + ts


class RedisJobQueue:
    """Redis-backed priority queue with processing, retry, and failed lists."""

    def __init__(self, client=redis_client) -> None:
        self._redis = client

    def enqueue(
        self,
        job_id: UUID,
        *,
        priority: JobPriority,
        created_at: datetime,
    ) -> None:
        member = str(job_id)
        self._redis.zadd(PENDING_KEY, {member: _score(priority, created_at)})

    def dequeue(self, timeout: int = 0) -> UUID | None:
        """Pop the next pending job and move it to processing."""
        popped = self._redis.zpopmin(PENDING_KEY, count=1)
        if not popped:
            return None

        member, _score_val = popped[0]
        job_id = UUID(member)

        payload = json.dumps({"job_id": member})
        self._redis.lpush(PROCESSING_KEY, payload)

        return job_id

    def acknowledge(self, job_id: UUID) -> None:
        """Remove a job from processing after successful completion."""
        member = str(job_id)
        payload = json.dumps({"job_id": member})
        self._redis.lrem(PROCESSING_KEY, count=0, value=payload)

    def move_to_failed(self, job_id: UUID) -> None:
        member = str(job_id)
        payload = json.dumps({"job_id": member, "reason": "handler_error"})
        self._redis.lrem(PROCESSING_KEY, count=0, value=json.dumps({"job_id": member}))
        self._redis.lpush(FAILED_KEY, payload)

    def move_to_retry(self, job_id: UUID) -> None:
        member = str(job_id)
        payload = json.dumps({"job_id": member, "retry_count": 1})
        self._redis.lrem(PROCESSING_KEY, count=0, value=json.dumps({"job_id": member}))
        self._redis.lpush(RETRY_KEY, payload)

    def requeue_from_retry(
        self,
        job_id: UUID,
        *,
        priority: JobPriority,
        created_at: datetime,
    ) -> None:
        """Move a job from retry back into pending."""
        member = str(job_id)
        self._redis.zadd(PENDING_KEY, {member: _score(priority, created_at)})

    def size(self) -> int:
        return self._redis.zcard(PENDING_KEY)

    def processing_size(self) -> int:
        return self._redis.llen(PROCESSING_KEY)

    def retry_size(self) -> int:
        return self._redis.llen(RETRY_KEY)

    def failed_size(self) -> int:
        return self._redis.llen(FAILED_KEY)

    def stats(self) -> dict[str, int]:
        return {
            "pending": self.size(),
            "processing": self.processing_size(),
            "retry": self.retry_size(),
            "failed": self.failed_size(),
        }

    def clear(self) -> None:
        self._redis.delete(PENDING_KEY, PROCESSING_KEY, RETRY_KEY, FAILED_KEY)

    def peek(self) -> UUID | None:
        items = self._redis.zrange(PENDING_KEY, 0, 0)
        return UUID(items[0]) if items else None


job_queue = RedisJobQueue()
