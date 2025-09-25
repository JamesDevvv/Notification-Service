from __future__ import annotations

from typing import List, Optional, Union
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db, ScheduledNotificationORM
from app.models import (
    NotificationRequest,
    NotificationStatus,
    BatchRequest,
    BatchResponse,
    BatchResponseItem,
    ScheduleCreateRequest,
    new_batch_id,
    new_schedule_id,
)
from app.services.queue_service import enqueue_notification, get_status

router = APIRouter()


# Support bulk recipients in /send by accepting an alternate payload shape
class NotificationRequestBulk(NotificationRequest):
    recipients: List[str]  # overrides single recipient for bulk path


@router.post("/send")
def send_notification(
    payload: Union[NotificationRequestBulk, NotificationRequest],
    db: Session = Depends(get_db),
):
    """
    Send immediate notification.
    - Supports single or bulk recipients.
    - Returns tracking_id for single, or list of tracking_ids for bulk.
    """
    # Distinguish bulk vs single by presence of 'recipients' attribute
    if hasattr(payload, "recipients"):
        bulk_payload = payload  # type: ignore
        tracking_ids: List[str] = []
        base_req: NotificationRequest = NotificationRequest(
            channel=bulk_payload.channel,
            recipient="",  # will be filled per-recipient
            template_id=bulk_payload.template_id,
            content=bulk_payload.content,
            variables=bulk_payload.variables,
            priority=bulk_payload.priority,
            metadata=bulk_payload.metadata,
        )
        for r in bulk_payload.recipients:
            base_req.recipient = r
            tid = enqueue_notification(db, base_req)
            tracking_ids.append(tid)
        return {"tracking_ids": tracking_ids, "count": len(tracking_ids)}
    else:
        tid = enqueue_notification(db, payload)  # type: ignore
        return {"tracking_id": tid}


@router.post("/schedule")
def schedule_notification(
    payload: ScheduleCreateRequest,
    db: Session = Depends(get_db),
):
    """
    Schedule future notification. Supports recurrence (cron) and timezone.
    Returns schedule_id.
    """
    schedule_id = new_schedule_id()
    sched = ScheduledNotificationORM(
        schedule_id=schedule_id,
        notification_data=payload.notification.dict(),
        send_at=payload.send_at,
        timezone=payload.timezone,
        recurrence=payload.recurrence,
        last_run=None,
        active=payload.active,
    )
    db.add(sched)
    db.commit()
    return {"schedule_id": schedule_id}


@router.get("/{tracking_id}/status", response_model=NotificationStatus)
def notification_status(
    tracking_id: str,
    db: Session = Depends(get_db),
):
    """
    Get delivery status and attempts, including failure reasons.
    """
    status = get_status(db, tracking_id)
    if not status:
        raise HTTPException(status_code=404, detail="Tracking ID not found")
    return status


@router.post("/batch", response_model=BatchResponse)
def batch_notifications(
    payload: BatchRequest,
    db: Session = Depends(get_db),
):
    """
    Send up to 100 notifications.
    - delivery_mode: 'atomic' or 'best_effort'
    - Returns batch_id and per-item tracking_ids
    """
    if len(payload.notifications) > 100:
        raise HTTPException(status_code=400, detail="Batch size cannot exceed 100")

    batch_id = new_batch_id()
    items: List[BatchResponseItem] = []

    if payload.delivery_mode == "atomic":
        # Validate all first
        try:
            for req in payload.notifications:
                # Basic validation via Pydantic already happened
                pass
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Atomic validation failed: {e}")

        # Enqueue all
        for req in payload.notifications:
            tid = enqueue_notification(db, req)
            items.append(BatchResponseItem(tracking_id=tid, status="queued"))
    else:
        # best_effort: try each, collect errors
        for req in payload.notifications:
            try:
                tid = enqueue_notification(db, req)
                items.append(BatchResponseItem(tracking_id=tid, status="queued"))
            except Exception as e:
                items.append(BatchResponseItem(tracking_id="", status="failed", error=str(e)))

    return BatchResponse(batch_id=batch_id, items=items)
