from __future__ import annotations

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.database import get_db
from app.models import Template, TemplateCreateRequest, TemplateListResponse
from app.services.template_service import TemplateService

router = APIRouter()


@router.post("", response_model=Template)
def create_template(
    payload: TemplateCreateRequest,
    db: Session = Depends(get_db),
):
    """
    Create reusable message template.
    Supports variables and conditionals (Jinja2).
    """
    try:
        created = TemplateService.create_template(db, payload)
        return created
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("", response_model=TemplateListResponse)
def list_templates(
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    channel: Optional[str] = Query(None),
    active: Optional[bool] = Query(None),
    db: Session = Depends(get_db),
):
    """
    List templates with pagination. Filter by channel and active status.
    """
    items, total = TemplateService.list_templates(db, page=page, size=size, channel=channel, active=active)
    return TemplateListResponse(items=items, total=total, page=page, size=size)
