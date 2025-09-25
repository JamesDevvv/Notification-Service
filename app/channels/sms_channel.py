from __future__ import annotations

import asyncio
import random
import re
import time
from typing import Any, Dict, Optional

from app.channels.base import BaseChannel, register_channel, TransientChannelError, PermanentChannelError
from app.models import NotificationRequest


# Basic E.164-like phone validation (very lenient)
PHONE_REGEX = re.compile(r"^\+?[1-9]\d{7,14}$")

# Character limits
# - hard limit: 1000 characters
# - segment size: 160 characters (informational; we don't price segments)
HARD_CHAR_LIMIT = 1000
SEGMENT_SIZE = 160

FAILURE_RATE = 0.05  # 5%
DELAY_RANGE = (1.0, 5.0)  # seconds


@register_channel("sms")
class SMSChannel(BaseChannel):
    """
    Mock Twilio-like SMS channel:
    - Validates recipient format and body length
    - Simulates delivery delay between 1–5 seconds
    - Simulates carrier failures at 5% rate
    """

    async def send(self, req: NotificationRequest, rendered: Dict[str, Optional[str]]) -> Dict[str, Any]:
        start = time.perf_counter()

        body = (rendered.get("body") or "").strip()
        if not body:
            raise PermanentChannelError("SMS body is required")

        # Validate phone number
        recipient = req.recipient.strip()
        if not PHONE_REGEX.match(recipient):
            raise PermanentChannelError("Invalid phone number format")

        # Validate length
        if len(body) > HARD_CHAR_LIMIT:
            raise PermanentChannelError(f"SMS body exceeds {HARD_CHAR_LIMIT} characters")

        # Simulate per-segment sending time with random delay
        await asyncio.sleep(random.uniform(*DELAY_RANGE))

        # Simulate carrier failures at 5%
        if random.random() < FAILURE_RATE:
            raise TransientChannelError("Carrier temporary failure")

        # Success
        segments = max(1, (len(body) + SEGMENT_SIZE - 1) // SEGMENT_SIZE)
        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "provider": "mock-twilio",
            "segments": segments,
            "latency_ms": latency_ms,
        }
