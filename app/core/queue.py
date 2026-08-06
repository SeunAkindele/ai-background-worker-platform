import heapq
import threading
from datetime import datetime
from uuid import UUID

from app.models.job import PRIORITY_RANK, JobPriority


class PriorityJobQueue:
    """
    Thread-safe priority queue for job IDs.

    Ordering: priority rank, then created_at (FIFO within the same priority).
    """

    def __init__(self) -> None:
        self._heap: list[tuple[int, float, UUID]] = []
        self._lock = threading.Lock()

    def enqueue(
        self,
        job_id: UUID,
        *,
        priority: JobPriority,
        created_at: datetime,
    ) -> None:
        with self._lock:
            heapq.heappush(self._heap, (PRIORITY_RANK[priority], created_at, job_id))

    def dequeue(self) -> UUID | None:
        with self._lock:
            if not self._heap:
                return None
            return heapq.heappop(self._heap)[2]

    def peek(self) -> UUID | None:
        with self._lock:
            if not self._heap:
                return None
            return self._heap[0][2]

    def size(self) -> int:
        with self._lock:
            return len(self._heap)

    def clear(self) -> None:
        with self._lock:
            self._heap.clear()


job_queue = PriorityJobQueue()
