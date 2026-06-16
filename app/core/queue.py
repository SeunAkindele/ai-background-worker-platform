from collections import deque
from uuid import UUID


class InMemoryJobQueue:
    """
    FIFO queue storing job IDs only.
    PostgreSQL holds full job data — queue is just scheduling order.
    """

    def __init__(self) -> None:
        self._queue: deque[UUID] = deque()

    def enqueue(self, job_id: UUID) -> None:
        """O(1) — add to right end."""
        self._queue.append(job_id)

    def dequeue(self) -> UUID | None:
        """O(1) — remove from left end. Returns None if empty."""
        if not self._queue:
            return None
        return self._queue.popleft()

    def clear(self) -> None:
        """Remove all queued job IDs. Useful for tests."""
        self._queue.clear()

    def size(self) -> int:
        """O(1)."""
        return len(self._queue)

    def peek(self) -> UUID | None:
        """Optional: look at front without removing."""
        return self._queue[0] if self._queue else None


# Single shared instance for the app process (Stage 1 only)
job_queue = InMemoryJobQueue()
