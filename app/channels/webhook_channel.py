from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

import httpx

from app.channels.base import BaseChannel, register_channel, TransientChannelError, PermanentChannelError
from app.models import NotificationRequest


DEFAULT_TIMEOUT = 10.0  # seconds


@register_channel("webhook")
class WebhookChannel(BaseChannel):
    """
    Webhook delivery via HTTP POST with retries handled by the queue/retry layer.
    - Uses httpx AsyncClient
    - Timeout after 10 seconds
    - SSL certificate verification enabled by default
    - Custom headers supported via req.metadata["headers"]
    Payload includes rendered content and basic metadata.
    """

    async def send(self, req: NotificationRequest, rendered: Dict[str, Optional[str]]) -> Dict[str, Any]:
        if not req.recipient.lower().startswith(("http://", "https://")):
            raise PermanentChannelError("Webhook recipient must be a valid URL")

        headers: Dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": "notification-service/0.1",
        }

        # Allow custom headers via metadata
        if req.metadata and isinstance(req.metadata, dict):
            custom = req.metadata.get("headers")
            if isinstance(custom, dict):
                for k, v in custom.items():
                    headers[str(k)] = str(v)

        payload = {
            "channel": "webhook",
            "subject": rendered.get("subject"),
            "body": rendered.get("body"),
            "metadata": req.metadata or {},
        }

        start = time.perf_counter()
        try:
            async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
                resp = await client.post(req.recipient, json=payload, headers=headers)
                latency_ms = (time.perf_counter() - start) * 1000.0

                # 2xx -> success
                if 200 <= resp.status_code < 300:
                    return {
                        "provider": "http",
                        "status_code": resp.status_code,
                        "latency_ms": latency_ms,
                    }

                # 4xx -> permanent failure (won't succeed with retry)
                if 400 <= resp.status_code < 500:
                    raise PermanentChannelError(f"Webhook responded with {resp.status_code}: {resp.text[:200]}")

                # 5xx -> transient
                raise TransientChannelError(f"Webhook server error {resp.status_code}: {resp.text[:200]}")
        except httpx.TimeoutException as e:
            raise TransientChannelError(f"Webhook timeout after {DEFAULT_TIMEOUT}s") from e
        except httpx.HTTPError as e:
            # Network errors considered transient
            raise TransientChannelError(f"Webhook HTTP error: {e}") from e
