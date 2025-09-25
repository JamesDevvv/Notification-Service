from __future__ import annotations

import random
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional


# Retry strategy by priority
RETRY_CONFIGS: Dict[str, Dict[str, List[int] or int]] = {
    "critical": {"max_attempts": 5, "delays": [1, 5, 15, 60, 300]},
    "high": {"max_attempts": 3, "delays": [5, 30, 120]},
    "normal": {"max_attempts": 2, "delays": [10, 60]},
    "low": {"max_attempts": 1, "delays": []},
}


def backoff_with_jitter(base_delay: float, attempt: int, jitter_ratio: float = 0.2) -> float:
    """
    Exponential backoff with jitter based on attempt number.
    If explicit delays are provided by config, prefer those; otherwise compute: base * 2^(attempt-1)
    """
    delay = base_delay * (2 ** (attempt - 1))
    jitter = delay * jitter_ratio
    return max(0.0, delay + random.uniform(-jitter, jitter))


@dataclass
class CircuitBreaker:
    """
    Simple per-recipient circuit breaker.
    - closed: calls pass through
    - open: calls fail fast until cooldown elapses
    - half_open: probe: allow a single call; success -> closed; failure -> open again
    """
    failure_threshold: int = 3
    cooldown_seconds: float = 60.0

    state: str = "closed"  # closed | open | half_open
    failure_count: int = 0
    opened_at: Optional[float] = None
    half_open_probe_in_flight: bool = False

    def on_success(self) -> None:
        self.state = "closed"
        self.failure_count = 0
        self.opened_at = None
        self.half_open_probe_in_flight = False

    def on_failure(self) -> None:
        if self.state == "half_open":
            # Immediately open again
            self.state = "open"
            self.opened_at = time.time()
            self.half_open_probe_in_flight = False
            self.failure_count = max(self.failure_count, self.failure_threshold)
            return

        self.failure_count += 1
        if self.failure_count >= self.failure_threshold:
            self.state = "open"
            self.opened_at = time.time()

    def allow_request(self) -> bool:
        now = time.time()
        if self.state == "closed":
            return True

        if self.state == "open":
            # check cooldown
            if self.opened_at is None:
                self.opened_at = now
                return False
            if (now - self.opened_at) >= self.cooldown_seconds:
                # move to half-open
                self.state = "half_open"
                self.half_open_probe_in_flight = False
                return self.allow_request()
            return False

        if self.state == "half_open":
            # allow a single probe
            if not self.half_open_probe_in_flight:
                self.half_open_probe_in_flight = True
                return True
            return False

        return False


@dataclass
class RetryPlan:
    max_attempts: int
    delays: List[float] = field(default_factory=list)  # in seconds

    def next_delay(self, attempt_number: int) -> Optional[float]:
        """
        Returns the delay before the given attempt_number (1-based).
        If configured delays are shorter, fall back to exponential backoff with jitter.
        """
        if attempt_number <= 1:
            return 0.0
        idx = attempt_number - 2  # delay before attempt 2 is index 0
        if idx < len(self.delays):
            return float(self.delays[idx])
        # fallback: exponential with jitter based on last configured or 1s base
        base = float(self.delays[-1]) if self.delays else 1.0
        return backoff_with_jitter(base_delay=base, attempt=attempt_number - len(self.delays))


def get_retry_plan(priority: str) -> RetryPlan:
    cfg = RETRY_CONFIGS.get(priority, RETRY_CONFIGS["normal"])
    return RetryPlan(max_attempts=int(cfg["max_attempts"]), delays=[float(x) for x in cfg["delays"]])  # type: ignore


class TransientError(Exception):
    """Exception type to signal transient, retryable errors."""
    pass


class PermanentError(Exception):
    """Exception type to signal permanent, non-retryable errors."""
    pass
