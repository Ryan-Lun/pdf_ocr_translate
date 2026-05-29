"""baseline schema

Revision ID: 0001_baseline_schema
Revises:
Create Date: 2026-05-29 00:00:00
"""
from __future__ import annotations

from alembic import op

from app.services import auth_store, job_store  # noqa: F401

# revision identifiers, used by Alembic.
revision = "0001_baseline_schema"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    job_store.Base.metadata.create_all(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    job_store.Base.metadata.drop_all(bind=bind, checkfirst=True)
