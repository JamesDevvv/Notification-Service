from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Dict


@dataclass
class TokenBucket:
    capacity: float
    refill_rate: float  # tokens per second
    tokens: float
    last_refill: float

    def try_consume(self, amount: float = 1.0) -> bool:
        now = time.time()
        # Refill based on elapsed time
        elapsed = now - self.last_refill
        if elapsed > 0:
            self.tokens = min(self.capacity, self.tokens + elapsed * self.refill_rate)
            self.last_refill = now

        if self.tokens >= amount:
            self.tokens -= amount
            return True
        return False


class RateLimiter:
    """
    Simple in-memory per-key token-bucket rate limiter.
    Not distributed; suitable for single-process use or as a fallback
    when Redis-based limiter is not available.
    """

    def __init__(self, capacity: float = 10.0, refill_rate: float = 1.0) -> None:
        """
        capacity: max tokens per bucket
        refill_rate: tokens per second
        """
        self.capacity = capacity
        self.refill_rate = refill_rate
        self._buckets: Dict[str, TokenBucket] = {}
        self._lock = threading.Lock()

    def allow(self, key: str, amount: float = 1.0) -> bool:
        with self._lock:
            bucket = self._buckets.get(key)
            if bucket is None:
                bucket = TokenBucket(
                    capacity=self.capacity,
                    refill_rate=self.refill_rate,
                    tokens=self.capacity,  # start full
                    last_refill=time.time(),
                )
                self._buckets[key] = bucket
            return bucket.try_consume(amount)
