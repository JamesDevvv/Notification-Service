from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Optional, Dict, Any

from croniter import croniter
try:
    from zoneinfo import ZoneInfo  # Python 3.9+
except Exception:  # pragma: no cover
    ZoneInfo = None  # type: ignore

from app.database import SessionLocal, ScheduledNotificationORM
from app.models import NotificationRequest
from app.services.queue_service import enqueue_notification

# Scheduler background task handle
_scheduler_task: Optional[asyncio.Task] = None
_stop_event: Optional[asyncio.Event] = None


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _to_utc(dt: datetime, tz_name: str) -> datetime:
    """
    Convert a datetime interpreted in tz_name to UTC.
    - If dt is naive: treat it as time in tz_name
    - If dt is aware: convert to UTC regardless of tz_name
    """
    if dt.tzinfo is None:
        if ZoneInfo is None:
            # Fallback: assume naive datetimes are already UTC
            return dt.replace(tzinfo=timezone.utc)
        tz = ZoneInfo(tz_name)
        local_dt = dt.replace(tzinfo=tz)
        return local_dt.astimezone(timezone.utc)
    else:
        return dt.astimezone(timezone.utc)


def _next_cron_time(current_local: datetime, cron_expr: str, tz_name: str) -> datetime:
    """
    Compute next occurrence for cron_expr in tz_name, return UTC-aware datetime.
    """
    if ZoneInfo is not None:
        tz = ZoneInfo(tz_name)
        base_local = current_local.astimezone(tz) if current_local.tzinfo else current_local.replace(tzinfo=tz)
    else:
        # Fallback assume UTC
        tz = timezone.utc
        base_local = current_local.astimezone(tz) if current_local.tzinfo else current_local.replace(tzinfo=tz)

    itr = croniter(cron_expr, base_local)
    next_local = itr.get_next(datetime)
    # Convert to UTC
    return next_local.astimezone(timezone.utc)


async def _process_due_schedules() -> None:
    """
    Scan the DB for due scheduled notifications and enqueue them.
    """
    db = SessionLocal()
    try:
        # Load active schedules. We filter a bit in SQL, but finalize due check in Python with timezone handling.
        schedules = (
            db.query(ScheduledNotificationORM)
            .filter(ScheduledNotificationORM.active == True)  # noqa: E712
            .all()
        )

        now_utc = _now_utc()
        for sched in schedules:
            try:
                tz_name = sched.timezone or "UTC"
                send_at_utc = _to_utc(sched.send_at, tz_name)
                # Avoid double processing by checking last_run
                if send_at_utc <= now_utc and (sched.last_run is None or sched.last_run < send_at_utc):
                    # Build NotificationRequest from stored json
                    payload: Dict[str, Any] = sched.notification_data or {}
                    req = NotificationRequest.parse_obj(payload)  # type: ignore
                    enqueue_notification(db, req)
                    # Update last_run and compute next if recurring
                    sched.last_run = now_utc
                    if sched.recurrence:
                        # compute next send time in local tz then store as UTC (aware)
                        next_utc = _next_cron_time(send_at_utc, sched.recurrence, tz_name)
                        # Store as naive UTC in DB for consistency (SQLAlchemy DateTime without TZ)
                        sched.send_at = next_utc.replace(tzinfo=None)
                    else:
                        # one-off schedule completed; deactivate
                        sched.active = False
                    db.commit()
            except Exception as e:
                # Log and continue; do not crash the scheduler loop
                # In a production setup, use proper logging here
                print(f"[scheduler] Failed processing schedule {sched.schedule_id}: {e}")
    finally:
        db.close()


async def _scheduler_loop():
    """
    Scheduler loop:
      - poll DB for due scheduled_notifications
      - enqueue notifications
      - handle recurrence (cron)
      - timezone aware
    """
    assert _stop_event is not None
    try:
        while not _stop_event.is_set():
            await _process_due_schedules()
            await asyncio.sleep(1.0)
    except asyncio.CancelledError:
        # graceful shutdown
        pass


async def start_scheduler():
    """
    Start scheduler loop.
    """
    global _scheduler_task, _stop_event
    if _scheduler_task is not None and not _scheduler_task.done():
        return
    _stop_event = asyncio.Event()
    _scheduler_task = asyncio.create_task(_scheduler_loop())


async def stop_scheduler():
    """
    Stop scheduler loop.
    """
    global _scheduler_task, _stop_event
    if _scheduler_task:
        assert _stop_event is not None
        _stop_event.set()
        _scheduler_task.cancel()
        try:
            await _scheduler_task
        except asyncio.CancelledError:
            pass
        _scheduler_task = None
        _stop_event = None
