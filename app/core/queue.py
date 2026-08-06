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
        """Append a job ID to the end of the queue."""
        self._queue.append(job_id)

    def dequeue(self) -> UUID | None:
        """Remove and return the next job ID, or None if empty."""
        if not self._queue:
            return None
        return self._queue.popleft()

    def clear(self) -> None:
        """Remove all queued job IDs."""
        self._queue.clear()

    def size(self) -> int:
        """Return the number of queued job IDs."""
        return len(self._queue)

    def peek(self) -> UUID | None:
        """Return the front job ID without removing it."""
        return self._queue[0] if self._queue else None


job_queue = InMemoryJobQueue()

