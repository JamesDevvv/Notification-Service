import os
import tempfile
import time

import pytest  # type: ignore
from fastapi.testclient import TestClient # type: ignore

from app.main import app
from app.database import init_db


def setup_module(module):
    # Use isolated DB dir for integration tests
    tmpdir = tempfile.mkdtemp(prefix="notif-int-tests-")
    os.environ["DB_DIR"] = tmpdir
    os.environ["QUEUE_WORKERS"] = "2"
    os.environ["RATE_LIMIT_ENABLED"] = "false"
    init_db()


@pytest.mark.timeout(30)
def test_end_to_end_template_push(monkeypatch):
    # Speed up push and make deterministic
    import app.channels.push_channel as push_mod
    monkeypatch.setattr(push_mod, "RECEIPT_RATE", 1.0)
    monkeypatch.setattr(push_mod, "DELAY_RANGE", (0.01, 0.01))

    with TestClient(app) as client:
        # Create a template
        tpl_resp = client.post(
            "/templates",
            json={
                "name": "welcome-push",
                "channel": "push",
                "body": "Hello {{ name }}, welcome to our service!",
                "variables": ["name"],
                "active": True,
            },
        )
        assert tpl_resp.status_code == 200, tpl_resp.text
        tpl = tpl_resp.json()
        assert tpl["template_id"]
        assert tpl["name"] == "welcome-push"

        # Send notification using template_id by name convenience
        send_resp = client.post(
            "/notifications/send",
            json={
                "channel": "push",
                "recipient": "VALIDTOKEN_int_1234567890abcdef",
                "template_id": "welcome-push",  # allow referencing by name
                "variables": {"name": "Alice"},
                "priority": "high",
            },
        )
        assert send_resp.status_code == 200, send_resp.text
        tracking_id = send_resp.json()["tracking_id"]

        # Poll status until delivered
        delivered = False
        for _ in range(200):  # up to ~20s
            status_resp = client.get(f"/notifications/{tracking_id}/status")
            assert status_resp.status_code == 200
            data = status_resp.json()
            if data["status"] == "delivered":
                delivered = True
                break
            time.sleep(0.05)
        assert delivered, "Template-based push notification not delivered in time"

        # Analytics summary should be callable
        analytics_resp = client.get("/analytics/summary")
        assert analytics_resp.status_code == 200
        summary = analytics_resp.json()
        assert "by_channel_delivery_rates" in summary


@pytest.mark.timeout(30)
def test_batch_best_effort_and_atomic(monkeypatch):
    # Make sms deterministic and fast
    import app.channels.sms_channel as sms_mod
    monkeypatch.setattr(sms_mod, "FAILURE_RATE", 0.0)
    monkeypatch.setattr(sms_mod, "DELAY_RANGE", (0.01, 0.01))

    with TestClient(app) as client:
        # best_effort batch
        be_resp = client.post(
            "/notifications/batch",
            json={
                "delivery_mode": "best_effort",
                "notifications": [
                    {
                        "channel": "sms",
                        "recipient": "+15551234567",
                        "content": {"body": "Batch hello 1"},
                        "priority": "normal",
                    },
                    {
                        "channel": "sms",
                        "recipient": "+15551234568",
                        "content": {"body": "Batch hello 2"},
                        "priority": "high",
                    },
                ],
            },
        )
        assert be_resp.status_code == 200, be_resp.text
        be = be_resp.json()
        assert "batch_id" in be and len(be["items"]) == 2

        # atomic batch (simple validation path)
        at_resp = client.post(
            "/notifications/batch",
            json={
                "delivery_mode": "atomic",
                "notifications": [
                    {
                        "channel": "sms",
                        "recipient": "+15551234569",
                        "content": {"body": "Atomic hello"},
                        "priority": "normal",
                    }
                ],
            },
        )
        assert at_resp.status_code == 200, at_resp.text
        at = at_resp.json()
        assert "batch_id" in at and len(at["items"]) == 1
