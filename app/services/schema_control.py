from __future__ import annotations

from collections.abc import Mapping

from sqlalchemy import inspect

from . import auth_store, job_store

SCHEMA_GROUPS: dict[str, tuple[str, ...]] = {
    "jobs": ("jobs", "job_artifacts", "job_events", "document_templates"),
    "auth": ("users", "roles", "user_roles"),
}

REQUIRED_COLUMNS: dict[str, tuple[str, ...]] = {
    "jobs": (
        "job_id",
        "job_type",
        "status",
        "stage",
        "progress",
        "job_name",
        "owner_work_id",
        "target_lang",
        "document_mode",
        "payload_json",
        "error_message",
        "cancel_requested",
        "retry_count",
        "worker_id",
        "started_at",
        "completed_at",
        "created_at",
        "updated_at",
    ),
    "job_artifacts": ("id", "job_id", "artifact_type", "file_path", "created_at"),
    "job_events": ("id", "job_id", "event_type", "stage", "message", "created_at"),
    "document_templates": (
        "template_id",
        "name",
        "display_name",
        "owner_work_id",
        "source_job_id",
        "status",
        "payload_json",
        "created_at",
        "updated_at",
    ),
    "users": ("id", "work_id", "display_name", "email", "is_active", "created_at", "last_login_at"),
    "roles": ("id", "name"),
    "user_roles": ("user_id", "role_id"),
}


def auto_schema_management_enabled(app) -> bool:
    return bool(app.config.get("AUTO_SCHEMA_MANAGEMENT", True))


def _engine():
    engine = getattr(job_store, "_engine", None)
    if engine is None:
        raise RuntimeError("Database engine not initialized.")
    return engine


def existing_tables() -> set[str]:
    inspector = inspect(_engine())
    return {name.lower() for name in inspector.get_table_names()}


def tables_exist(*table_names: str) -> bool:
    tables = existing_tables()
    return all(table.lower() in tables for table in table_names)


def required_schema_groups(app) -> dict[str, tuple[str, ...]]:
    groups = {"jobs": SCHEMA_GROUPS["jobs"]}
    if app.config.get("AUTH_ENABLED", False):
        groups["auth"] = SCHEMA_GROUPS["auth"]
    return groups


def missing_schema_groups(app, table_groups: Mapping[str, tuple[str, ...]] | None = None) -> dict[str, list[str]]:
    groups = dict(table_groups or required_schema_groups(app))
    tables = existing_tables()
    missing: dict[str, list[str]] = {}
    for group_name, required_tables in groups.items():
        absent = [table for table in required_tables if table.lower() not in tables]
        if absent:
            missing[group_name] = absent
    return missing


def missing_columns(table_groups: Mapping[str, tuple[str, ...]] | None = None) -> dict[str, list[str]]:
    groups = dict(table_groups or SCHEMA_GROUPS)
    inspector = inspect(_engine())
    tables = existing_tables()
    missing: dict[str, list[str]] = {}
    for required_tables in groups.values():
        for table in required_tables:
            if table.lower() not in tables:
                continue
            existing = {col["name"].lower() for col in inspector.get_columns(table)}
            absent = [column for column in REQUIRED_COLUMNS.get(table, ()) if column.lower() not in existing]
            if absent:
                missing[table] = absent
    return missing


def ensure_auto_schema(app) -> None:
    if not auto_schema_management_enabled(app):
        return
    engine = _engine()
    job_store.Base.metadata.create_all(bind=engine, checkfirst=True)
    auth_store.ensure_auth_schema()
