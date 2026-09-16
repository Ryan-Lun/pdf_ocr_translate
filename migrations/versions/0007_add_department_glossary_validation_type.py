"""add department glossary validation type

Revision ID: 0007_glossary_validation_type
Revises: 0006_glossary_audit_events
Create Date: 2026-09-16 00:00:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy import inspect

from app.services import job_store, state

# revision identifiers, used by Alembic.
revision = "0007_glossary_validation_type"
down_revision = "0006_glossary_audit_events"
branch_labels = None
depends_on = None


def _configure_schema(bind) -> None:
    if bind.dialect.name == "mssql":
        job_store.configure_database_schema(state.DATABASE_SCHEMA)
        job_store.ensure_database_schema(bind)
    else:
        job_store.configure_database_schema("dbo")


def upgrade() -> None:
    bind = op.get_bind()
    _configure_schema(bind)
    inspector = inspect(bind)
    schema = job_store.inspection_schema(bind)
    tables = {name.lower() for name in inspector.get_table_names(schema=schema)}
    if "department_glossary_entries" not in tables:
        job_store.DepartmentGlossaryEntryRecord.__table__.create(bind=bind, checkfirst=True)
        return
    columns = {
        column["name"].lower()
        for column in inspector.get_columns("department_glossary_entries", schema=schema)
    }
    if "validation_type" in columns:
        return
    op.add_column(
        "department_glossary_entries",
        sa.Column(
            "validation_type",
            sa.String(length=30),
            nullable=False,
            server_default="strict_required",
        ),
        schema=schema,
    )


def downgrade() -> None:
    bind = op.get_bind()
    _configure_schema(bind)
    inspector = inspect(bind)
    schema = job_store.inspection_schema(bind)
    tables = {name.lower() for name in inspector.get_table_names(schema=schema)}
    if "department_glossary_entries" not in tables:
        return
    columns = {
        column["name"].lower()
        for column in inspector.get_columns("department_glossary_entries", schema=schema)
    }
    if "validation_type" not in columns:
        return
    op.drop_column("department_glossary_entries", "validation_type", schema=schema)
