"""add translation memory entries

Revision ID: 0004_translation_memory_entries
Revises: 0003_editor_presence
Create Date: 2026-09-01 00:00:00
"""
from __future__ import annotations

from alembic import op
from sqlalchemy import inspect

from app.services import job_store, state

# revision identifiers, used by Alembic.
revision = "0004_translation_memory_entries"
down_revision = "0003_editor_presence"
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
    table = job_store.TranslationMemoryEntryRecord.__table__
    inspector = inspect(bind)
    schema = job_store.inspection_schema(bind)
    existing_tables = {name.lower() for name in inspector.get_table_names(schema=schema)}
    if table.name.lower() not in existing_tables:
        table.create(bind=bind, checkfirst=True)
        return
    existing_indexes = {index["name"].lower() for index in inspector.get_indexes(table.name, schema=schema)}
    for index in table.indexes:
        if index.name and index.name.lower() not in existing_indexes:
            index.create(bind=bind, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    _configure_schema(bind)
    job_store.TranslationMemoryEntryRecord.__table__.drop(bind=bind, checkfirst=True)
