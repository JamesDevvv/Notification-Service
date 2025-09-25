import os
import tempfile
from datetime import datetime

import pytest  # type: ignore

from app.database import init_db, SessionLocal
from app.services.template_service import TemplateService
from app.models import TemplateCreateRequest


def setup_module(module):
    # Ensure a clean temporary DB dir for tests
    tmpdir = tempfile.mkdtemp(prefix="notif-tests-")
    os.environ["DB_DIR"] = tmpdir
    init_db()


def test_template_create_and_render():
    db = SessionLocal()
    try:
        req = TemplateCreateRequest(
            name="welcome-email",
            channel="email",
            subject="Welcome {{ name }}",
            body="Hello {{ name }}, your plan is {{ plan }}.",
            variables=["name", "plan"],
            active=True,
        )
        tpl = TemplateService.create_template(db, req)

        assert tpl.template_id
        assert tpl.name == "welcome-email"
        assert tpl.channel == "email"
        assert tpl.subject == "Welcome {{ name }}"
        assert "Hello" in tpl.body

        # Render with variables
        orm = TemplateService.get_template_orm(db, tpl.template_id)
        assert orm is not None
        rendered = TemplateService.render(orm, {"name": "John", "plan": "Premium"})
        assert rendered["subject"] == "Welcome John"
        assert "John" in rendered["body"]
        assert "Premium" in rendered["body"]
    finally:
        db.close()


def test_template_missing_variables_validation():
    db = SessionLocal()
    try:
        req = TemplateCreateRequest(
            name="invoice-email",
            channel="email",
            subject="Invoice {{ invoice_id }}",
            body="Amount due: {{ amount | currency }} by {{ due_date | format_date('%Y-%m-%d') }}",
            variables=["invoice_id", "amount", "due_date"],
            active=True,
        )
        tpl = TemplateService.create_template(db, req)
        orm = TemplateService.get_template_orm(db, tpl.template_id)
        assert orm is not None

        with pytest.raises(ValueError):
            TemplateService.render(orm, {"invoice_id": "INV-1"})  # missing amount and due_date

        # Provide complete vars
        rendered = TemplateService.render(orm, {
            "invoice_id": "INV-1",
            "amount": 1234.0,
            "due_date": datetime(2024, 1, 2),
        })
        assert "INV-1" in (rendered["subject"] or "")
        assert "$1,234.00" in (rendered["body"] or "")
        assert "2024-01-02" in (rendered["body"] or "")
    finally:
        db.close()
