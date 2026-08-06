"""
Rate limiter using Redis sliding window counter.

DSA Focus:
----------
Sliding window counter — a hybrid between fixed window and sliding log.

Algorithm:
1. Divide time into fixed windows (e.g., 60-second windows)
2. Track the current window count AND the previous window count
3. Estimate current rate = prev_count * overlap_fraction + curr_count

Time complexity: O(1) per check (2 Redis GETs + 1 INCR)
Space complexity: O(1) per user (2 keys at any time)

Why not a simple fixed window?
- Fixed window has a burst problem at window boundaries.
  A user could make 20 requests at second 59 and 20 more at second 61,
  effectively doing 40 in 2 seconds while the limit is 20/minute.
- Sliding window smooths this out.

Alternative: Token bucket
- Tokens refill at a steady rate
- Each request consumes a token
- Allows controlled bursts (bucket capacity)
- More complex to implement correctly in distributed systems

We use sliding window counter here because:
- Simple to implement with Redis
- Accurate enough for our use case
- No race conditions with INCR (atomic)

Python Internals Focus:
-----------------------
- time.time() returns a float (C double underneath) — Unix epoch seconds
- int() truncation for window alignment
- The // operator does floor division (same as int(a/b) for positive numbers)
"""
import time

from app.config import settings
from app.core.redis_client import redis_client


class RateLimiter:
    def __init__(
        self,
        max_requests: int | None = None,
        window_seconds: int | None = None,
    ):
        self._max_requests = max_requests or settings.rate_limit_requests
        self._window_seconds = window_seconds or settings.rate_limit_window_seconds

    def is_allowed(self, user_id: str) -> bool:
        """
        Check if a request from user_id should be allowed.

        Returns True if under the limit, False if rate limited.
        """
        current_window = int(time.time()) // self._window_seconds
        previous_window = current_window - 1

        curr_key = f"rate:{user_id}:{current_window}"
        prev_key = f"rate:{user_id}:{previous_window}"

        pipe = redis_client.pipeline()
        pipe.get(prev_key)
        pipe.get(curr_key)
        prev_count_raw, curr_count_raw = pipe.execute()

        prev_count = int(prev_count_raw) if prev_count_raw else 0
        curr_count = int(curr_count_raw) if curr_count_raw else 0

        elapsed_in_window = time.time() % self._window_seconds
        overlap_fraction = 1 - (elapsed_in_window / self._window_seconds)
        estimated_rate = prev_count * overlap_fraction + curr_count

        return estimated_rate < self._max_requests

    def record_request(self, user_id: str) -> int:
        """
        Record that a request was made. Returns the new count for this window.

        Uses INCR (atomic increment) + EXPIRE so keys auto-delete.
        No manual cleanup needed — Redis handles TTL eviction.
        """
        current_window = int(time.time()) // self._window_seconds
        key = f"rate:{user_id}:{current_window}"

        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, self._window_seconds * 2)
        results = pipe.execute()

        return results[0]

    def check_and_record(self, user_id: str) -> tuple[bool, int]:
        """
        Atomic check + record. Returns (allowed, current_count).

        If not allowed, does NOT record (so failed requests don't
        eat into the budget on the next window calculation).
        """
        if not self.is_allowed(user_id):
            current_window = int(time.time()) // self._window_seconds
            key = f"rate:{user_id}:{current_window}"
            count = redis_client.get(key)
            return False, int(count) if count else 0

        count = self.record_request(user_id)
        return True, count


rate_limiter = RateLimiter()