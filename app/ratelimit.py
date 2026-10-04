import threading
import time
from collections import defaultdict, deque

from .config import settings
from .errors import ApiError


class SlidingWindowLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = limit
        self.window = window_seconds
        self._hits: dict[int, deque] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: int) -> None:
        now = time.monotonic()
        with self._lock:
            q = self._hits[key]
            while q and now - q[0] >= self.window:
                q.popleft()
            if len(q) >= self.limit:
                retry = int(self.window - (now - q[0])) + 1
                raise ApiError(429, "RATE_LIMITED",
                               f"Too many booking attempts. Retry in {retry}s.",
                               headers={"Retry-After": str(retry)})
            q.append(now)

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


booking_limiter = SlidingWindowLimiter(settings.booking_rate_limit,
                                       settings.booking_rate_window_seconds)