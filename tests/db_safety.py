from __future__ import annotations

import os

from sqlalchemy import create_engine

from app.config import TestingConfig
from app.services import job_store, state

DEFAULT_TEST_SCHEMA = "translation_test"
FORBIDDEN_TEST_SCHEMAS = {"dbo", "translation"}


def configure_test_database(monkeypatch):
    database_url = state.normalize_database_url(os.getenv("TEST_DATABASE_URL", state.DATABASE_URL).strip())
    schema = state.normalize_database_schema(os.getenv("TEST_DATABASE_SCHEMA", DEFAULT_TEST_SCHEMA))
    if schema.lower() in FORBIDDEN_TEST_SCHEMAS or not schema.lower().endswith("_test"):
        raise RuntimeError(
            "Refusing to run destructive DB tests outside a dedicated test schema. "
            "Set TEST_DATABASE_SCHEMA to a name ending in '_test'."
        )
    monkeypatch.setattr(state, "DATABASE_URL", database_url)
    monkeypatch.setattr(state, "DATABASE_SCHEMA", schema)
    monkeypatch.setattr(TestingConfig, "DATABASE_URL", database_url)
    monkeypatch.setattr(TestingConfig, "DATABASE_SCHEMA", schema)
    job_store.configure_database_schema(schema)
    engine = create_engine(database_url, future=True, pool_pre_ping=True)
    job_store.ensure_database_schema(engine)
    return engine
