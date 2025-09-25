from __future__ import annotations

from datetime import datetime, timedelta
from typing import Dict, Optional, Tuple

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.database import NotificationORM, DeliveryAttemptORM
from app.models import AnalyticsSummary


class AnalyticsService:
    @staticmethod
    def summary(
        db: Session,
        window_start: Optional[datetime] = None,
        window_end: Optional[datetime] = None,
    ) -> AnalyticsSummary:
        """
        Compute delivery rates by channel, average delivery time, and failure reasons breakdown
        over an optional time window.
        """
        # Default to last 24h if no window provided
        if window_end is None:
            window_end = datetime.utcnow()
        if window_start is None:
            window_start = window_end - timedelta(days=1)

        base_query = db.query(NotificationORM).filter(
            NotificationORM.created_at >= window_start,
            NotificationORM.created_at <= window_end,
        )

        # Delivery rates by channel: delivered/total per channel
        totals_per_channel = dict(
            db.query(NotificationORM.channel, func.count(NotificationORM.tracking_id))
            .filter(
                NotificationORM.created_at >= window_start,
                NotificationORM.created_at <= window_end,
            )
            .group_by(NotificationORM.channel)
            .all()
        )
        delivered_per_channel = dict(
            db.query(NotificationORM.channel, func.count(NotificationORM.tracking_id))
            .filter(
                NotificationORM.created_at >= window_start,
                NotificationORM.created_at <= window_end,
                NotificationORM.status == "delivered",
            )
            .group_by(NotificationORM.channel)
            .all()
        )
        by_channel_delivery_rates: Dict[str, float] = {}
        for channel, total in totals_per_channel.items():
            delivered = delivered_per_channel.get(channel, 0)
            rate = float(delivered) / float(total) if total else 0.0
            by_channel_delivery_rates[channel] = rate

        # Average delivery time (ms): difference between delivered_at and created_at
        delivered_rows = (
            db.query(NotificationORM.created_at, NotificationORM.delivered_at)
            .filter(
                NotificationORM.created_at >= window_start,
                NotificationORM.created_at <= window_end,
                NotificationORM.delivered_at.isnot(None),
            )
            .all()
        )
        total_ms = 0.0
        delivered_count = 0
        for created_at, delivered_at in delivered_rows:
            if created_at and delivered_at:
                delta = delivered_at - created_at
                total_ms += delta.total_seconds() * 1000.0
                delivered_count += 1
        avg_delivery_time_ms = (total_ms / delivered_count) if delivered_count else 0.0

        # Failure reasons breakdown from notifications table (latest failure reason)
        failure_rows = (
            db.query(NotificationORM.failure_reason, func.count(NotificationORM.tracking_id))
            .filter(
                NotificationORM.created_at >= window_start,
                NotificationORM.created_at <= window_end,
                NotificationORM.status.in_(("failed", "bounced")),
                NotificationORM.failure_reason.isnot(None),
            )
            .group_by(NotificationORM.failure_reason)
            .all()
        )
        failure_reasons: Dict[str, int] = {}
        for reason, count in failure_rows:
            key = reason or "unknown"
            failure_reasons[key] = count

        return AnalyticsSummary(
            by_channel_delivery_rates=by_channel_delivery_rates,
            avg_delivery_time_ms=avg_delivery_time_ms,
            failure_reasons=failure_reasons,
            time_window_start=window_start,
            time_window_end=window_end,
        )
