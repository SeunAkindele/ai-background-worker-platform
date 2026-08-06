"""Redis sliding-window rate limiter."""
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
        """Return True if the client is under the rate limit."""
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
        """Record a request and return the current window count."""
        current_window = int(time.time()) // self._window_seconds
        key = f"rate:{user_id}:{current_window}"

        pipe = redis_client.pipeline()
        pipe.incr(key)
        pipe.expire(key, self._window_seconds * 2)
        results = pipe.execute()

        return results[0]

    def check_and_record(self, user_id: str) -> tuple[bool, int]:
        """
        Check the limit and record the request if allowed.

        Returns (allowed, current_count). Rejected requests are not recorded.
        """
        if not self.is_allowed(user_id):
            current_window = int(time.time()) // self._window_seconds
            key = f"rate:{user_id}:{current_window}"
            count = redis_client.get(key)
            return False, int(count) if count else 0

        count = self.record_request(user_id)
        return True, count


rate_limiter = RateLimiter()
