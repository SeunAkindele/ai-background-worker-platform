import json
from datetime import datetime
from uuid import UUID

from app.core.redis_client import redis_client
from app.models.job import PRIORITY_RANK, JobPriority

# Queue key constants — single source of truth
PENDING_KEY = "jobs:pending"
PROCESSING_KEY = "jobs:processing"
RETRY_KEY = "jobs:retry"
FAILED_KEY = "jobs:failed"

# Encode priority + FIFO into one float score for ZSET
_SCORE_MULTIPLIER = 10**13


def _score(priority: JobPriority, created_at: datetime) -> float:
    rank = PRIORITY_RANK[priority]
    ts = created_at.timestamp()
    return rank * _SCORE_MULTIPLIER + ts


class RedisJobQueue:
    """
    Producer–consumer queue backed by Redis.

    pending:   ZSET  — priority + FIFO via score
    processing: LIST — jobs currently being worked
    retry/failed: LIST — dead-letter / retry stubs for Stage 3
    """

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
        """
        Atomically pop lowest-score job from pending and push to processing.

        timeout=0 → non-blocking (good for tests + worker poll loop).
        For blocking, you can use BZPOPMIN in the worker instead.
        """
        popped = self._redis.zpopmin(PENDING_KEY, count=1)
        if not popped:
            return None

        member, _score_val = popped[0]
        job_id = UUID(member)

        # Track in-flight work (LIST = simple audit trail)
        payload = json.dumps({"job_id": member})
        self._redis.lpush(PROCESSING_KEY, payload)

        return job_id

    def acknowledge(self, job_id: UUID) -> None:
        """Remove job from processing after successful completion."""
        member = str(job_id)
        payload = json.dumps({"job_id": member})
        self._redis.lrem(PROCESSING_KEY, count=0, value=payload)

    def move_to_failed(self, job_id: UUID) -> None:
        member = str(job_id)
        payload = json.dumps({"job_id": member, "reason": "handler_error"})
        self._redis.lrem(PROCESSING_KEY, count=0, value=json.dumps({"job_id": member}))
        self._redis.lpush(FAILED_KEY, payload)

    def move_to_retry(self, job_id: UUID) -> None:
        # Stage 3 stub — full retry scheduling comes in Stage 5
        member = str(job_id)
        payload = json.dumps({"job_id": member, "retry_count": 1})
        self._redis.lrem(PROCESSING_KEY, count=0, value=json.dumps({"job_id": member}))
        self._redis.lpush(RETRY_KEY, payload)

    def requeue_from_retry(self, job_id: UUID, *, priority: JobPriority, created_at: datetime) -> None:
        """Optional: pull from retry back into pending (manual or cron later)."""
        member = str(job_id)
        self._redis.zadd(PENDING_KEY, {member: _score(priority, created_at)})

    def size(self) -> int:
        return self._redis.zcard(PENDING_KEY)

    def processing_size(self) -> int:
        return self._redis.llen(PROCESSING_KEY)

    def clear(self) -> None:
        """Tests only — wipe all queue keys."""
        self._redis.delete(PENDING_KEY, PROCESSING_KEY, RETRY_KEY, FAILED_KEY)


job_queue = RedisJobQueue()