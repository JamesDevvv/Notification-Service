from __future__ import annotations

import asyncio
import random
import re
import time
from typing import Any, Dict, Optional

from app.channels.base import BaseChannel, register_channel, TransientChannelError, PermanentChannelError
from app.models import NotificationRequest


# Very simple device token validation (mock)
TOKEN_REGEX = re.compile(r"^[A-Za-z0-9_\-:.]{16,256}$")

DELAY_RANGE = (0.1, 1.0)  # seconds
RECEIPT_RATE = 0.95  # 95% chance we get a positive receipt


@register_channel("push")
class PushChannel(BaseChannel):
    """
    Mock push notifications (FCM/APNS-like).
    - Validates device token
    - Simulates network delay
    - Returns mock delivery receipt data
    """

    async def send(self, req: NotificationRequest, rendered: Dict[str, Optional[str]]) -> Dict[str, Any]:
        start = time.perf_counter()

        token = req.recipient.strip()
        if not TOKEN_REGEX.match(token):
            raise PermanentChannelError("Invalid device token")

        body = (rendered.get("body") or "").strip()
        if not body:
            raise PermanentChannelError("Push body is required")

        # Simulate network delay
        await asyncio.sleep(random.uniform(*DELAY_RANGE))

        # Occasionally simulate transient failure
        if random.random() > RECEIPT_RATE:
            raise TransientChannelError("Push provider temporary failure")

        latency_ms = (time.perf_counter() - start) * 1000.0
        return {
            "provider": "mock-push",
            "receipt_id": f"r_{int(time.time()*1000)}_{random.randint(1000,9999)}",
            "latency_ms": latency_ms,
        }
