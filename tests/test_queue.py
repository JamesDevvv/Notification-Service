import os
import tempfile
import time

import pytest  # type: ignore 
from fastapi.testclient import TestClient  # type: ignore

from app.main import app
from app.database import init_db, SessionLocal
from app.database import NotificationORM


def setup_module(module):
    # Isolate DB for this test module
    tmpdir = tempfile.mkdtemp(prefix="notif-queue-tests-")
    os.environ["DB_DIR"] = tmpdir
    os.environ["QUEUE_WORKERS"] = "2"
    os.environ["RATE_LIMIT_ENABLED"] = "false"
    init_db()


@pytest.mark.timeout(20)
def test_queue_end_to_end_sms(monkeypatch):
    # Speed up SMS and make deterministic
    import app.channels.sms_channel as sms_mod
    monkeypatch.setattr(sms_mod, "FAILURE_RATE", 0.0)
    monkeypatch.setattr(sms_mod, "DELAY_RANGE", (0.01, 0.01))

    with TestClient(app) as client:
        # Send a notification
        resp = client.post(
            "/notifications/send",
            json={
                "channel": "sms",
                "recipient": "+15551234567",
                "content": {"body": "hello via sms"},
                "priority": "high",
            },
        )
        assert resp.status_code == 200
        tracking_id = resp.json()["tracking_id"]

        # Poll for delivery
        delivered = False
        for _ in range(100):  # up to ~10s
            status_resp = client.get(f"/notifications/{tracking_id}/status")
            assert status_resp.status_code == 200
            data = status_resp.json()
            if data["status"] == "delivered":
                delivered = True
                break
            time.sleep(0.1)
        assert delivered, f"Notification {tracking_id} was not delivered in time"


@pytest.mark.timeout(20)
def test_priority_queue_order(monkeypatch):
    # Make push fast and deterministic
    import app.channels.push_channel as push_mod
    monkeypatch.setattr(push_mod, "RECEIPT_RATE", 1.0)
    monkeypatch.setattr(push_mod, "DELAY_RANGE", (0.01, 0.01))

    with TestClient(app) as client:
        # enqueue low and high priority
        low = client.post(
            "/notifications/send",
            json={
                "channel": "push",
                "recipient": "VALIDTOKEN_low_1234567890abcdef",
                "content": {"body": "low priority"},
                "priority": "low",
            },
        ).json()["tracking_id"]

        high = client.post(
            "/notifications/send",
            json={
                "channel": "push",
                "recipient": "VALIDTOKEN_high_1234567890abcdef",
                "content": {"body": "high priority"},
                "priority": "high",
            },
        ).json()["tracking_id"]

        # Wait a bit and ensure high likely delivers earlier than low
        done = set()
        for _ in range(200):  # up to ~20s
            got = False
            for tid in [high, low]:
                status = client.get(f"/notifications/{tid}/status").json()
                if status["status"] == "delivered":
                    done.add(tid)
                    got = True
            if len(done) == 2:
                break
            time.sleep(0.05)

        assert high in done and low in done
