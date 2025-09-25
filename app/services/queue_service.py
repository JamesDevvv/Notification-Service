from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models import (
    NotificationRequest,
    NotificationStatus,
    DeliveryAttempt as DeliveryAttemptSchema,
    new_tracking_id,
)
from app.database import (
    NotificationORM,
    DeliveryAttemptORM,
    TemplateORM,
    SessionLocal,
)
from app.services.template_service import TemplateService
from app.channels.base import get_channel, TransientChannelError, PermanentChannelError
from app.utils.retry_handler import get_retry_plan, CircuitBreaker
from app.utils.rate_limiter import RateLimiter

# -----------------------------------------------------------------------------
# Queue with background workers, retry logic, circuit breaker, and rate limiter
# -----------------------------------------------------------------------------

# In-memory ready queue: tuples of (priority_value, seq, tracking_id)
_ready_queue: Optional[asyncio.PriorityQueue] = None  # type: ignore
_seq_counter = 0
_workers: List[asyncio.Task] = []
_workers_started = False

# Per-recipient circuit breakers
_circuit_breakers: Dict[str, CircuitBreaker] = {}

# Optional rate limiter
_rate_limiter: Optional[RateLimiter] = None


def _priority_value(priority: str) -> int:
    # lower number => higher priority in PriorityQueue
    order = {"critical": 0, "high": 1, "normal": 2, "low": 3}
    return order.get(priority, 2)


def _env_bool(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.lower() in ("1", "true", "yes", "on")


def _ensure_ready_queue() -> None:
    global _ready_queue
    if _ready_queue is None:
        _ready_queue = asyncio.PriorityQueue()


async def start_queue_workers() -> None:
    """
    Start background worker tasks for processing notifications.
    """
    global _workers_started, _workers, _rate_limiter

    if _workers_started:
        return

    # Ensure channels are registered by importing modules
    try:
        from app.channels import email_channel, sms_channel, webhook_channel, push_channel  # noqa: F401
    except Exception as e:
        print(f"[queue] Channel registration import error: {e}")

    _ensure_ready_queue()

    # Optional in-memory per-recipient rate limiter
    if _env_bool("RATE_LIMIT_ENABLED", False):
        cap = float(os.getenv("RATE_LIMIT_CAPACITY", "10"))
        refill = float(os.getenv("RATE_LIMIT_REFILL", "1"))
        _rate_limiter = RateLimiter(capacity=cap, refill_rate=refill)

    workers = int(os.getenv("QUEUE_WORKERS", "4"))
    for i in range(workers):
        t = asyncio.create_task(_worker_loop(i))
        _workers.append(t)

    _workers_started = True
    print(f"[queue] Started {workers} worker(s)")


async def stop_queue_workers() -> None:
    """
    Stop worker tasks gracefully.
    """
    global _workers_started, _workers
    if not _workers_started:
        return
    for t in _workers:
        t.cancel()
    for t in _workers:
        try:
            await t
        except asyncio.CancelledError:
            pass
    _workers.clear()
    _workers_started = False
    print("[queue] Stopped workers")


def enqueue_notification(db: Session, req: NotificationRequest) -> str:
    """
    Persist a notification in 'queued' state and return tracking_id.
    Also enqueues it for processing.
    """
    tracking_id = new_tracking_id()

    # Persist full request context inside content JSON
    # Maintain backward-compatibility for subject/body only.
    content_json: Dict[str, Any] = {
        "content": req.content or {},
        "variables": req.variables or {},
        "metadata": req.metadata or {},
        "template_id": req.template_id,
    }

    notif = NotificationORM(
        tracking_id=tracking_id,
        channel=req.channel,
        recipient=req.recipient,
        content=content_json,
        status="queued",
        priority=req.priority,
        attempts=0,
        created_at=datetime.utcnow(),
        scheduled_for=None,
        delivered_at=None,
        last_attempt_at=None,
        failure_reason=None,
    )
    db.add(notif)
    db.commit()

    # Enqueue for processing
    _enqueue_ready(tracking_id, req.priority)
    return tracking_id


def _enqueue_ready(tracking_id: str, priority: str) -> None:
    """
    Put tracking_id into the in-memory priority queue.
    """
    global _seq_counter
    _ensure_ready_queue()
    _seq_counter += 1
    try:
        _ready_queue.put_nowait((_priority_value(priority), _seq_counter, tracking_id))  # type: ignore
    except Exception as e:
        print(f"[queue] Failed to enqueue: {e}")


async def _worker_loop(worker_id: int) -> None:
    """
    Worker loop: pull items from queue and process them with retries.
    """
    assert _ready_queue is not None
    while True:
        try:
            # Wait for next item
            priority, seq, tracking_id = await _ready_queue.get()  # type: ignore
            await _process_tracking_id(tracking_id)
        except asyncio.CancelledError:
            # graceful shutdown
            break
        except Exception as e:
            # Keep worker alive on unexpected errors
            print(f"[worker {worker_id}] error: {e}")


def _reconstruct_request_from_notif(notif: NotificationORM) -> NotificationRequest:
    """
    Build NotificationRequest from stored NotificationORM content JSON.
    """
    content = notif.content or {}
    # Back-compat
    if "content" in content or "variables" in content or "metadata" in content or "template_id" in content:
        body_content = content.get("content") or {}
        variables = content.get("variables") or {}
        metadata = content.get("metadata") or {}
        template_id = content.get("template_id")
    else:
        # old shape: direct subject/body
        body_content = content
        variables = {}
        metadata = {}
        template_id = None

    return NotificationRequest(
        channel=notif.channel,
        recipient=notif.recipient,
        template_id=template_id,
        content=body_content,
        variables=variables,
        priority=notif.priority,  # type: ignore
        metadata=metadata,
    )


def _get_or_create_cb(recipient: str) -> CircuitBreaker:
    cb = _circuit_breakers.get(recipient)
    if cb is None:
        # Defaults; can be tuned via env later
        cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=float(os.getenv("CB_COOLDOWN", "60")))
        _circuit_breakers[recipient] = cb
    return cb


async def _process_tracking_id(tracking_id: str) -> None:
    """
    Process a single notification by tracking_id with retry policy and CB.
    """
    db = SessionLocal()
    try:
        notif = db.query(NotificationORM).filter(NotificationORM.tracking_id == tracking_id).one_or_none()
        if not notif:
            return

        req = _reconstruct_request_from_notif(notif)
        plan = get_retry_plan(req.priority)

        # Circuit breaker per recipient
        cb = _get_or_create_cb(req.recipient)
        if not cb.allow_request():
            # Fast-fail, mark as failed attempt (bounced)
            record_delivery_attempt(
                db,
                tracking_id=tracking_id,
                attempt_number=(notif.attempts or 0) + 1,
                status="failed",
                latency_ms=0.0,
                error_message="circuit_open",
            )
            return

        # Optional rate limiting per recipient
        if _rate_limiter is not None:
            if not _rate_limiter.allow(f"recipient:{req.recipient}"):
                # Requeue with slight delay to prevent tight loop
                await asyncio.sleep(0.5)
                _enqueue_ready(tracking_id, req.priority)
                return

        # Attempt send
        attempt_number = (notif.attempts or 0) + 1
        # Update status to sending
        notif.status = "sending"
        db.commit()

        start = time.perf_counter()
        try:
            rendered = await _render_content(db, req)
            channel = get_channel(req.channel)
            metadata = await channel.send(req, rendered)
            latency_ms = (time.perf_counter() - start) * 1000.0

            # Success
            cb.on_success()
            record_delivery_attempt(
                db,
                tracking_id=tracking_id,
                attempt_number=attempt_number,
                status="delivered",
                latency_ms=latency_ms,
                error_message=None,
            )
            return
        except PermanentChannelError as e:
            cb.on_failure()
            latency_ms = (time.perf_counter() - start) * 1000.0
            record_delivery_attempt(
                db,
                tracking_id=tracking_id,
                attempt_number=attempt_number,
                status="failed",
                latency_ms=latency_ms,
                error_message=str(e),
            )
            return
        except TransientChannelError as e:
            cb.on_failure()
            latency_ms = (time.perf_counter() - start) * 1000.0
            record_delivery_attempt(
                db,
                tracking_id=tracking_id,
                attempt_number=attempt_number,
                status="failed",
                latency_ms=latency_ms,
                error_message=str(e),
            )
            # schedule retry if allowed
            if attempt_number < plan.max_attempts:
                delay = plan.next_delay(attempt_number + 1) or 0.0
                # schedule re-enqueue after delay
                asyncio.create_task(_delayed_requeue(tracking_id, req.priority, delay))
            else:
                # give up
                pass
            return
        except Exception as e:
            # Unknown errors considered transient for safety
            cb.on_failure()
            latency_ms = (time.perf_counter() - start) * 1000.0
            record_delivery_attempt(
                db,
                tracking_id=tracking_id,
                attempt_number=attempt_number,
                status="failed",
                latency_ms=latency_ms,
                error_message=f"unexpected: {e}",
            )
            # attempt retry if allowed
            if attempt_number < plan.max_attempts:
                delay = plan.next_delay(attempt_number + 1) or 0.0
                asyncio.create_task(_delayed_requeue(tracking_id, req.priority, delay))
            return
    finally:
        db.close()


async def _delayed_requeue(tracking_id: str, priority: str, delay: float) -> None:
    try:
        await asyncio.sleep(delay)
        _enqueue_ready(tracking_id, priority)
    except Exception as e:
        print(f"[queue] delayed requeue error: {e}")


async def _render_content(db: Session, req: NotificationRequest) -> Dict[str, Optional[str]]:
    """
    Render content from template or use provided content.
    """
    # If template_id is provided, fetch by id or by name for convenience
    if req.template_id:
        tpl = db.query(TemplateORM).filter(TemplateORM.template_id == req.template_id).one_or_none()
        if not tpl:
            # try by name
            tpl = db.query(TemplateORM).filter(TemplateORM.name == req.template_id, TemplateORM.active == True).one_or_none()  # noqa: E712
        if not tpl:
            raise PermanentChannelError("Template not found")

        return TemplateService.render(tpl, req.variables or {})

    # No template: use raw content
    subject = None
    body = ""
    if req.content and isinstance(req.content, dict):
        subject = req.content.get("subject")
        body = req.content.get("body") or ""
    return {"subject": subject, "body": body}


def record_delivery_attempt(
    db: Session,
    tracking_id: str,
    attempt_number: int,
    status: str,
    latency_ms: float,
    error_message: Optional[str] = None,
    response_code: Optional[int] = None,
) -> None:
    """
    Persist a delivery attempt record for a given notification and update status.
    """
    attempt = DeliveryAttemptORM(
        id=new_tracking_id(),
        tracking_id=tracking_id,
        attempt_number=attempt_number,
        status=status,
        error_message=error_message,
        response_code=response_code,
        attempted_at=datetime.utcnow(),
        latency_ms=latency_ms,
    )
    db.add(attempt)

    notif = db.query(NotificationORM).filter(NotificationORM.tracking_id == tracking_id).one_or_none()
    if notif:
        notif.attempts = max(notif.attempts or 0, attempt_number)
        notif.last_attempt_at = attempt.attempted_at
        if status == "delivered":
            notif.status = "delivered"
            notif.delivered_at = attempt.attempted_at
            notif.failure_reason = None
        elif status in ("failed", "bounced"):
            # Keep latest status; do not mark delivered_at
            notif.status = status
            notif.failure_reason = error_message

    db.commit()


def get_status(db: Session, tracking_id: str) -> Optional[NotificationStatus]:
    """
    Read a notification's current status with attempt history.
    """
    notif = (
        db.query(NotificationORM)
        .filter(NotificationORM.tracking_id == tracking_id)
        .one_or_none()
    )
    if not notif:
        return None

    attempts = (
        db.query(DeliveryAttemptORM)
        .filter(DeliveryAttemptORM.tracking_id == tracking_id)
        .order_by(DeliveryAttemptORM.attempt_number.asc())
        .all()
    )

    attempts_models: List[DeliveryAttemptSchema] = [
        DeliveryAttemptSchema(
            attempt_number=a.attempt_number,
            attempted_at=a.attempted_at,
            status=a.status,
            response_code=a.response_code,
            error_message=a.error_message,
            latency_ms=a.latency_ms,
        )
        for a in attempts
    ]

    return NotificationStatus(
        tracking_id=notif.tracking_id,
        status=notif.status,  # type: ignore
        channel=notif.channel,
        recipient=notif.recipient,
        attempts=notif.attempts or 0,
        last_attempt_at=notif.last_attempt_at,
        delivered_at=notif.delivered_at,
        failure_reason=notif.failure_reason,
        delivery_attempts=attempts_models,
    )
