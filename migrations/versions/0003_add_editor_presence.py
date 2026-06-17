"""add editor presence

Revision ID: 0003_editor_presence
Revises: 0002_audit_system_logs
Create Date: 2026-06-16 00:00:00
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

from app.services import job_store, state

# revision identifiers, used by Alembic.
revision = "0003_editor_presence"
down_revision = "0002_audit_system_logs"
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
    table = job_store.EditorPresenceRecord.__table__
    inspector = inspect(bind)
    schema = job_store.inspection_schema(bind)
    existing_tables = {name.lower() for name in inspector.get_table_names(schema=schema)}
    if table.name.lower() not in existing_tables:
        table.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    _configure_schema(bind)
    job_store.EditorPresenceRecord.__table__.drop(bind=bind, checkfirst=True)
