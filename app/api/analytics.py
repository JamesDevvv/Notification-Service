from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import AnalyticsSummary
from app.services.analytics_service import AnalyticsService

router = APIRouter()


@router.get("/summary", response_model=AnalyticsSummary)
def analytics_summary(
    db: Session = Depends(get_db),
    window_start: Optional[datetime] = Query(None),
    window_end: Optional[datetime] = Query(None),
):
    """
    Delivery rates by channel, average delivery time, and failure reasons breakdown.
    Optional time window parameters (UTC datetimes).
    """
    return AnalyticsService.summary(db, window_start=window_start, window_end=window_end)
