import os
import tempfile
import pytest # type: ignore

from app.models import NotificationRequest
from app.channels.base import PermanentChannelError
from app.channels.email_channel import EmailChannel
from app.channels.sms_channel import SMSChannel
from app.channels.webhook_channel import WebhookChannel
from app.channels.push_channel import PushChannel


@pytest.mark.asyncio
async def test_email_mock_send_success():
    # Ensure SMTP not configured -> mock path
    os.environ.pop("SMTP_HOST", None)
    os.environ.pop("SMTP_USERNAME", None)
    os.environ.pop("SMTP_PASSWORD", None)

    ch = EmailChannel()
    req = NotificationRequest(
        channel="email",
        recipient="user@example.com",
        content={"subject": "Hi", "body": "<p>Hello</p>"},
        priority="normal",
    )
    rendered = {"subject": "Hi", "body": "<p>Hello</p>"}
    res = await ch.send(req, rendered)
    assert res["provider"] in ("mock", "smtp")
    assert "latency_ms" in res


@pytest.mark.asyncio
async def test_email_invalid_recipient():
    ch = EmailChannel()
    req = NotificationRequest(
        channel="email",
        recipient="invalid-email",
        content={"subject": "Test", "body": "Body"},
        priority="normal",
    )
    with pytest.raises(PermanentChannelError):
        await ch.send(req, {"subject": "Test", "body": "Body"})


@pytest.mark.asyncio
async def test_sms_send_success(monkeypatch):
    # Make SMS deterministic and fast
    import app.channels.sms_channel as sms_mod
    monkeypatch.setattr(sms_mod, "FAILURE_RATE", 0.0)
    monkeypatch.setattr(sms_mod, "DELAY_RANGE", (0.01, 0.01))

    ch = SMSChannel()
    req = NotificationRequest(
        channel="sms",
        recipient="+15551234567",
        content={"body": "Hello via SMS"},
        priority="normal",
    )
    res = await ch.send(req, {"body": "Hello via SMS"})
    assert res["provider"] == "mock-twilio"
    assert "latency_ms" in res


@pytest.mark.asyncio
async def test_webhook_invalid_url():
    ch = WebhookChannel()
    req = NotificationRequest(
        channel="webhook",
        recipient="ftp://example.com/webhook",
        content={"body": "Ping"},
        priority="normal",
    )
    with pytest.raises(PermanentChannelError):
        await ch.send(req, {"body": "Ping"})


@pytest.mark.asyncio
async def test_push_send_success(monkeypatch):
    # Make push deterministic and fast
    import app.channels.push_channel as push_mod
    monkeypatch.setattr(push_mod, "RECEIPT_RATE", 1.0)
    monkeypatch.setattr(push_mod, "DELAY_RANGE", (0.01, 0.01))

    ch = PushChannel()
    req = NotificationRequest(
        channel="push",
        recipient="VALIDTOKEN_1234567890abcdef",
        content={"body": "Hello Push"},
        priority="normal",
    )
    res = await ch.send(req, {"body": "Hello Push"})
    assert res["provider"] == "mock-push"
    assert "receipt_id" in res
