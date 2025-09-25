from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional, Union
from pydantic import BaseModel, Field, HttpUrl, validator
from uuid import uuid4


# =========================
# Pydantic API Schemas
# =========================

Priority = Literal["low", "normal", "high", "critical"]
Channel = Literal["email", "sms", "webhook", "push"]
Status = Literal["queued", "sending", "delivered", "failed", "bounced"]


class NotificationRequest(BaseModel):
    channel: Channel
    recipient: str  # email, phone, url, or device_id
    template_id: Optional[str] = None
    content: Optional[Dict[str, Union[str, Dict[str, Any]]]] = None  # subject, body, etc.
    variables: Optional[Dict[str, Any]] = Field(default_factory=dict)
    priority: Priority = "normal"
    metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

    @validator("recipient")
    def validate_recipient(cls, v, values):
        # Basic format hints (actual validation per channel is done in channel implementations)
        if not isinstance(v, str) or not v.strip():
            raise ValueError("recipient must be a non-empty string")
        return v.strip()


class DeliveryAttempt(BaseModel):
    attempt_number: int
    attempted_at: datetime
    status: str
    response_code: Optional[int] = None
    error_message: Optional[str] = None
    latency_ms: float


class NotificationStatus(BaseModel):
    tracking_id: str
    status: Status
    channel: str
    recipient: str
    attempts: int
    last_attempt_at: Optional[datetime] = None
    delivered_at: Optional[datetime] = None
    failure_reason: Optional[str] = None
    delivery_attempts: Optional[List[DeliveryAttempt]] = None


class Template(BaseModel):
    template_id: str
    name: str
    channel: str
    subject: Optional[str] = None  # For email
    body: str
    variables: List[str] = Field(default_factory=list)  # Required variables
    active: bool = True
    created_at: datetime
    updated_at: datetime


class TemplateCreateRequest(BaseModel):
    name: str
    channel: Channel
    subject: Optional[str] = None
    body: str
    variables: Optional[List[str]] = Field(default_factory=list)
    active: bool = True


class TemplateListResponse(BaseModel):
    items: List[Template]
    total: int
    page: int
    size: int


class BatchRequest(BaseModel):
    notifications: List[NotificationRequest]
    delivery_mode: Literal["atomic", "best_effort"] = "best_effort"
    batch_metadata: Optional[Dict[str, Any]] = Field(default_factory=dict)

    @validator("notifications")
    def validate_notifications_count(cls, v):
        if len(v) == 0:
            raise ValueError("notifications list cannot be empty")
        if len(v) > 100:
            raise ValueError("batch notifications cannot exceed 100")
        return v


class BatchResponseItem(BaseModel):
    tracking_id: str
    status: Status = "queued"
    error: Optional[str] = None


class BatchResponse(BaseModel):
    batch_id: str
    items: List[BatchResponseItem]


class ScheduledNotification(BaseModel):
    schedule_id: str
    notification: NotificationRequest
    send_at: datetime
    timezone: str = "UTC"
    recurrence: Optional[str] = None  # cron expression
    active: bool = True


class ScheduleCreateRequest(BaseModel):
    notification: NotificationRequest
    send_at: datetime
    timezone: str = "UTC"
    recurrence: Optional[str] = None  # cron expression
    active: bool = True


class AnalyticsSummary(BaseModel):
    by_channel_delivery_rates: Dict[str, float]  # channel -> delivered/total
    avg_delivery_time_ms: float
    failure_reasons: Dict[str, int]  # reason -> count
    time_window_start: Optional[datetime] = None
    time_window_end: Optional[datetime] = None


# =========================
# Helper factories
# =========================

def new_tracking_id() -> str:
    return str(uuid4())


def new_batch_id() -> str:
    return str(uuid4())


def new_template_id() -> str:
    return str(uuid4())


def new_schedule_id() -> str:
    return str(uuid4())
