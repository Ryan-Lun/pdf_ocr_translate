"""baseline schema

Revision ID: 0001_baseline_schema
Revises:
Create Date: 2026-05-29 00:00:00
"""
from __future__ import annotations

from alembic import op

from app.services import auth_store, job_store, state  # noqa: F401

# revision identifiers, used by Alembic.
revision = "0001_baseline_schema"
down_revision = None
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
    job_store.Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    _configure_schema(bind)
    job_store.Base.metadata.drop_all(bind=bind, checkfirst=True)
