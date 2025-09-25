from __future__ import annotations

from datetime import datetime, date
from typing import Any, Dict, List, Optional, Tuple

from jinja2 import Environment, StrictUndefined, select_autoescape
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError

from app.database import TemplateORM
from app.models import Template as TemplateSchema, TemplateCreateRequest

# -------------------------------
# Jinja2 Environment and Filters
# -------------------------------

def _currency_filter(value: Any, symbol: str = "$", places: int = 2) -> str:
    try:
        amount = float(value)
    except Exception:
        return f"{symbol}{value}"
    return f"{symbol}{amount:,.{places}f}"

def _format_date_filter(value: Any, fmt: str = "%Y-%m-%d") -> str:
    try:
        if isinstance(value, (datetime, date)):
            return value.strftime(fmt)
        # Try parse from string
        return str(value)
    except Exception:
        return str(value)

_jinja_env = Environment(
    autoescape=select_autoescape(enabled_extensions=("html", "xml")),
    undefined=StrictUndefined,  # raise error on missing variables
)
_jinja_env.filters["currency"] = _currency_filter
_jinja_env.filters["format_date"] = _format_date_filter


# -------------------------------
# Helpers
# -------------------------------

def _to_schema(obj: TemplateORM) -> TemplateSchema:
    content = obj.content or {}
    subject = content.get("subject")
    body = content.get("body", "")
    return TemplateSchema(
        template_id=obj.template_id,
        name=obj.name,
        channel=obj.channel,
        subject=subject,
        body=body,
        variables=list(obj.variables or []),
        active=bool(obj.active),
        created_at=obj.created_at,
        updated_at=obj.updated_at,
    )


def _render_text(text: Optional[str], variables: Dict[str, Any]) -> Optional[str]:
    if text is None:
        return None
    tmpl = _jinja_env.from_string(text)
    return tmpl.render(**variables)


def _validate_required_variables(required: List[str], provided: Dict[str, Any]) -> None:
    missing = [v for v in required if v not in provided]
    if missing:
        raise ValueError(f"Missing required template variables: {', '.join(missing)}")


# -------------------------------
# Service
# -------------------------------

class TemplateService:
    @staticmethod
    def create_template(db: Session, req: TemplateCreateRequest) -> TemplateSchema:
        now = datetime.utcnow()
        obj = TemplateORM(
            template_id=str(__import__("uuid").uuid4()),
            name=req.name,
            channel=req.channel,
            content={"subject": req.subject, "body": req.body},
            variables=req.variables or [],
            active=req.active,
            created_at=now,
            updated_at=now,
        )
        db.add(obj)
        try:
            db.commit()
        except IntegrityError as e:
            db.rollback()
            raise ValueError("Template with this name already exists") from e
        db.refresh(obj)
        return _to_schema(obj)

    @staticmethod
    def get_template_by_id(db: Session, template_id: str) -> Optional[TemplateSchema]:
        obj = db.query(TemplateORM).filter(TemplateORM.template_id == template_id).one_or_none()
        if not obj:
            return None
        return _to_schema(obj)

    @staticmethod
    def get_template_orm(db: Session, template_id: str) -> Optional[TemplateORM]:
        return db.query(TemplateORM).filter(TemplateORM.template_id == template_id).one_or_none()

    @staticmethod
    def list_templates(
        db: Session,
        page: int = 1,
        size: int = 20,
        channel: Optional[str] = None,
        active: Optional[bool] = None,
    ) -> Tuple[List[TemplateSchema], int]:
        q = db.query(TemplateORM)
        if channel:
            q = q.filter(TemplateORM.channel == channel)
        if active is not None:
            q = q.filter(TemplateORM.active == active)
        total = q.count()
        items = (
            q.order_by(TemplateORM.created_at.desc())
            .offset((page - 1) * size)
            .limit(size)
            .all()
        )
        return [ _to_schema(t) for t in items ], total

    @staticmethod
    def set_active(db: Session, template_id: str, active: bool) -> bool:
        obj = db.query(TemplateORM).filter(TemplateORM.template_id == template_id).one_or_none()
        if not obj:
            return False
        obj.active = active
        obj.updated_at = datetime.utcnow()
        db.commit()
        return True

    @staticmethod
    def render(
        template_obj: TemplateORM,
        variables: Dict[str, Any],
    ) -> Dict[str, Optional[str]]:
        required = list(template_obj.variables or [])
        _validate_required_variables(required, variables)
        content = template_obj.content or {}
        subject_text = content.get("subject")
        body_text = content.get("body", "")
        rendered_subject = _render_text(subject_text, variables) if subject_text else None
        rendered_body = _render_text(body_text, variables) if body_text else ""
        return {"subject": rendered_subject, "body": rendered_body}
