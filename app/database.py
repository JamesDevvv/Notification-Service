from __future__ import annotations

import os
import json
from datetime import datetime
from typing import Any, Dict, Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    create_engine,
    event,
)
from sqlalchemy.dialects.sqlite import JSON as SQLITE_JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import relationship, sessionmaker, Session

# =========================
# Database configuration
# =========================

DEFAULT_DB_DIR = os.getenv("DB_DIR", "./data")
os.makedirs(DEFAULT_DB_DIR, exist_ok=True)

DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{os.path.join(DEFAULT_DB_DIR, 'notifications.db')}")

# For SQLite + SQLAlchemy, check_same_thread=False is needed for multi-threaded FastAPI
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
    pool_pre_ping=True,
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


# =========================
# ORM Models
# =========================

class NotificationORM(Base):
    __tablename__ = "notifications"

    tracking_id = Column(String(36), primary_key=True, index=True)
    channel = Column(String(32), nullable=False)
    recipient = Column(String(256), nullable=False, index=True)
    # Store structured content: subject, body, headers, etc.
    content = Column(SQLITE_JSON, nullable=True)
    status = Column(String(32), nullable=False, index=True, default="queued")
    priority = Column(String(16), nullable=False, default="normal")
    attempts = Column(Integer, nullable=False, default=0)

    created_at = Column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    scheduled_for = Column(DateTime, nullable=True)
    delivered_at = Column(DateTime, nullable=True)
    last_attempt_at = Column(DateTime, nullable=True)
    failure_reason = Column(Text, nullable=True)

    attempts_rel = relationship("DeliveryAttemptORM", back_populates="notification", cascade="all, delete-orphan")

    __table_args__ = (
        Index("ix_notifications_recipient", "recipient"),
        Index("ix_notifications_status", "status"),
        Index("ix_notifications_created_at", "created_at"),
    )


class DeliveryAttemptORM(Base):
    __tablename__ = "delivery_attempts"

    id = Column(String(36), primary_key=True)
    tracking_id = Column(String(36), ForeignKey("notifications.tracking_id", ondelete="CASCADE"), nullable=False, index=True)

    attempt_number = Column(Integer, nullable=False)
    status = Column(String(32), nullable=False)
    error_message = Column(Text, nullable=True)
    response_code = Column(Integer, nullable=True)
    attempted_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    latency_ms = Column(Float, nullable=False, default=0.0)

    notification = relationship("NotificationORM", back_populates="attempts_rel")


class TemplateORM(Base):
    __tablename__ = "templates"

    template_id = Column(String(36), primary_key=True)
    name = Column(String(128), nullable=False, unique=True, index=True)
    channel = Column(String(32), nullable=False)

    # content JSON will typically include {subject, body}
    content = Column(SQLITE_JSON, nullable=False, default=dict)
    variables = Column(SQLITE_JSON, nullable=False, default=list)

    active = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow)

    __table_args__ = (
        Index("ix_templates_name", "name"),
    )


class ScheduledNotificationORM(Base):
    __tablename__ = "scheduled_notifications"

    schedule_id = Column(String(36), primary_key=True)
    # Store NotificationRequest-like structure
    notification_data = Column(SQLITE_JSON, nullable=False, default=dict)
    send_at = Column(DateTime, nullable=False, index=True)
    timezone = Column(String(64), nullable=False, default="UTC")
    recurrence = Column(String(128), nullable=True)
    last_run = Column(DateTime, nullable=True)
    active = Column(Boolean, nullable=False, default=True)

    __table_args__ = (
        Index("ix_scheduled_notifications_send_at", "send_at"),
    )


# =========================
# Utility functions
# =========================

def init_db() -> None:
    """
    Initialize database (create tables).
    """
    Base.metadata.create_all(bind=engine, checkfirst=True)


def get_db() -> Session: # type: ignore
    """
    FastAPI dependency to get DB session; use with:
        db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
