from __future__ import annotations

import os
import re
import time
from typing import Any, Dict, Optional

import aiosmtplib

from app.channels.base import BaseChannel, register_channel, TransientChannelError, PermanentChannelError
from app.models import NotificationRequest


MAX_ATTACHMENT_BYTES = 10 * 1024 * 1024  # 10MB


def _bool_env(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")


@register_channel("email")
class EmailChannel(BaseChannel):
    """
    Email channel.
    - Uses aiosmtplib when SMTP_* env vars provided; otherwise mocks delivery.
    - Supports HTML and plain text (rendered body is used as HTML; text fallback auto-generated).
    - Validates max total attachments size up to 10MB (metadata-based, content not stored here).
    - SPF/DKIM headers placeholders.
    """

    async def send(self, req: NotificationRequest, rendered: Dict[str, Optional[str]]) -> Dict[str, Any]:
        start = time.perf_counter()

        subject = (rendered.get("subject") or "").strip()
        body = (rendered.get("body") or "").strip()

        if not subject:
            # Email can be sent without subject technically; enforce simple rule for demo
            subject = "(no subject)"

        # Validate recipient looks like an email
        if "@" not in req.recipient:
            raise PermanentChannelError("Invalid email recipient")

        # Validate attachments metadata if present
        attachments_meta = {}
        if req.metadata and isinstance(req.metadata, dict):
            attachments_meta = req.metadata.get("attachments") or {}
        total_bytes = 0
        if isinstance(attachments_meta, dict):
            for name, meta in attachments_meta.items():
                size = int(meta.get("size", 0)) if isinstance(meta, dict) else 0
                total_bytes += size
        if total_bytes > MAX_ATTACHMENT_BYTES:
            raise PermanentChannelError("Attachments exceed 10MB total size limit")

        # SPF/DKIM placeholders: add headers if configured (not a real signing)
        headers = {}
        if _bool_env("ADD_SPF_HEADER", True):
            headers["Received-SPF"] = "pass (placeholder)"
        if _bool_env("ADD_DKIM_HEADER", True):
            headers["DKIM-Signature"] = "v=1; a=rsa-sha256; d=example.com; s=default; (placeholder)"

        # If SMTP env configured, send real email; else mock
        smtp_host = os.getenv("SMTP_HOST")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USERNAME")
        smtp_pass = os.getenv("SMTP_PASSWORD")
        smtp_from = os.getenv("SMTP_FROM", smtp_user or "no-reply@example.com")
        use_tls = _bool_env("SMTP_USE_TLS", True)
        use_starttls = _bool_env("SMTP_STARTTLS", True)

        if smtp_host and smtp_user and smtp_pass:
            # Real send
            try:
                from email.message import EmailMessage

                msg = EmailMessage()
                msg["From"] = smtp_from
                msg["To"] = req.recipient
                msg["Subject"] = subject
                for k, v in headers.items():
                    msg[k] = v

                # Provide both HTML and text parts
                # Plain text fallback: strip tags simple heuristic
                plain_text = re.sub("<[^<]+?>", "", body)
                msg.set_content(plain_text or "(empty)")
                msg.add_alternative(body or "<p>(empty)</p>", subtype="html")

                # Note: Real attachments loading omitted; we only validate sizes via metadata

                # Connect and send
                client = aiosmtplib.SMTP(hostname=smtp_host, port=smtp_port, start_tls=use_starttls)
                await client.connect(timeout=10)
                if not use_starttls and use_tls:
                    await client.starttls()
                await client.login(smtp_user, smtp_pass)
                resp = await client.send_message(msg)
                await client.quit()
                latency_ms = (time.perf_counter() - start) * 1000.0
                return {"provider": "smtp", "response": str(resp), "latency_ms": latency_ms}
            except aiosmtplib.errors.SMTPException as e:
                # Treat SMTP errors as transient unless 5xx-classifies differently
                raise TransientChannelError(f"SMTP error: {e}") from e
            except Exception as e:
                # Network errors etc. transient
                raise TransientChannelError(f"SMTP send failed: {e}") from e
        else:
            # Mock send success
            latency_ms = (time.perf_counter() - start) * 1000.0
            return {"provider": "mock", "message": "queued", "latency_ms": latency_ms}
