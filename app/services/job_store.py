from __future__ import annotations

import contextlib
import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine, func, inspect, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from . import state

logger = logging.getLogger(__name__)
_LOCAL_WORKER_ID_RE = re.compile(r"^worker-(\d+)$")
_DATABASE_SCHEMA = state.DATABASE_SCHEMA


def _metadata_schema(schema_name: str | None = None) -> str | None:
    schema = state.normalize_database_schema(schema_name or _DATABASE_SCHEMA)
    return None if schema.lower() == "dbo" else schema


def configure_database_schema(schema_name: str | None = None) -> str:
    global _DATABASE_SCHEMA
    _DATABASE_SCHEMA = state.normalize_database_schema(schema_name or state.DATABASE_SCHEMA)
    table_schema = _metadata_schema(_DATABASE_SCHEMA)
    for table in Base.metadata.tables.values():
        table.schema = table_schema
    return _DATABASE_SCHEMA


def current_database_schema() -> str:
    return _DATABASE_SCHEMA


def inspection_schema(engine) -> str | None:
    if getattr(engine.dialect, "name", "") == "mssql":
        return _DATABASE_SCHEMA
    return _metadata_schema(_DATABASE_SCHEMA)


def _quote_identifier(identifier: str) -> str:
    return "[" + identifier.replace("]", "]]") + "]"


def qualified_table_name(table_name: str, engine=None) -> str:
    schema = _DATABASE_SCHEMA if engine is None or getattr(engine.dialect, "name", "") == "mssql" else _metadata_schema(_DATABASE_SCHEMA)
    if schema:
        return f"{_quote_identifier(schema)}.{_quote_identifier(table_name)}"
    return _quote_identifier(table_name)


def ensure_database_schema(bind) -> None:
    if getattr(bind.dialect, "name", "") != "mssql":
        return
    schema = _DATABASE_SCHEMA
    if schema.lower() == "dbo":
        return
    schema_literal = schema.replace("'", "''")
    schema_identifier = _quote_identifier(schema)
    statement = text(f"IF SCHEMA_ID(N'{schema_literal}') IS NULL EXEC(N'CREATE SCHEMA {schema_identifier}');")
    if hasattr(bind, "execute"):
        bind.execute(statement)
        return
    with bind.begin() as conn:
        conn.execute(statement)


class Base(DeclarativeBase):
    pass


class JobRecord(Base):
    __tablename__ = "jobs"

    job_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    job_type: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    status: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    progress: Mapped[float] = mapped_column(Float, nullable=False, default=0.0)
    job_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_work_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    target_lang: Mapped[str | None] = mapped_column(String(20), nullable=True)
    document_mode: Mapped[str | None] = mapped_column(String(20), nullable=True)
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    retry_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    worker_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobArtifactRecord(Base):
    __tablename__ = "job_artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    artifact_type: Mapped[str] = mapped_column(String(50), nullable=False)
    file_path: Mapped[str] = mapped_column(String(1000), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class JobEventRecord(Base):
    __tablename__ = "job_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    stage: Mapped[str | None] = mapped_column(String(50), nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class EditorPresenceRecord(Base):
    __tablename__ = "editor_presence"

    job_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    work_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    remote_addr: Mapped[str | None] = mapped_column(String(100), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, index=True)


class AuditLogRecord(Base):
    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    action: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    work_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    request_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    remote_addr: Mapped[str | None] = mapped_column(String(100), nullable=True)


class SystemErrorLogRecord(Base):
    __tablename__ = "system_error_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    level: Mapped[str] = mapped_column(String(20), nullable=False, default="ERROR", index=True)
    component: Mapped[str] = mapped_column(String(200), nullable=False, index=True)
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    error_type: Mapped[str | None] = mapped_column(String(200), nullable=True)
    detail_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    request_path: Mapped[str | None] = mapped_column(String(500), nullable=True)
    remote_addr: Mapped[str | None] = mapped_column(String(100), nullable=True)


class DocumentTemplateRecord(Base):
    __tablename__ = "document_templates"

    template_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    owner_work_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    source_job_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="saved")
    payload_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


_engine = None
_session_factory: sessionmaker[Session] | None = None
REQUIRED_TABLES = (
    "jobs",
    "job_artifacts",
    "job_events",
    "editor_presence",
    "audit_logs",
    "system_error_logs",
    "document_templates",
)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _int_env(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s.", name, raw, default)
        return default


def init_app(app) -> None:
    global _engine, _session_factory
    database_url = app.config["DATABASE_URL"]
    configure_database_schema(app.config.get("DATABASE_SCHEMA") or state.DATABASE_SCHEMA)
    if not database_url:
        raise RuntimeError("DATABASE_URL is required and must point to SQL Server.")
    if not database_url.lower().startswith("mssql"):
        raise RuntimeError("Only SQL Server DATABASE_URL values are supported.")
    _engine = create_engine(
        database_url,
        future=True,
        pool_pre_ping=True,
        pool_size=max(1, _int_env("DB_POOL_SIZE", 3)),
        max_overflow=max(0, _int_env("DB_MAX_OVERFLOW", 2)),
        pool_timeout=max(1, _int_env("DB_POOL_TIMEOUT_SECONDS", 10)),
        pool_recycle=max(60, _int_env("DB_POOL_RECYCLE_SECONDS", 1800)),
        connect_args={"timeout": max(1, _int_env("DB_CONNECT_TIMEOUT_SECONDS", 10))},
    )
    _session_factory = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    if bool(app.config.get("AUTO_SCHEMA_MANAGEMENT", True)):
        ensure_database_schema(_engine)
        Base.metadata.create_all(bind=_engine, checkfirst=True)
        _ensure_compatible_columns()
        _assert_required_tables()
    else:
        _assert_required_tables()


def _ensure_compatible_columns() -> None:
    if _engine is None:
        raise RuntimeError("Database engine not initialized.")
    inspector = inspect(_engine)
    schema = inspection_schema(_engine)
    table_names = {name.lower() for name in inspector.get_table_names(schema=schema)}
    with _engine.begin() as conn:
        if "jobs" in table_names:
            job_columns = {col["name"].lower() for col in inspector.get_columns("jobs", schema=schema)}
            if "owner_work_id" not in job_columns:
                conn.execute(text(f"ALTER TABLE {qualified_table_name('jobs', _engine)} ADD owner_work_id NVARCHAR(100) NULL;"))
        if "document_templates" in table_names:
            template_columns = {col["name"].lower() for col in inspector.get_columns("document_templates", schema=schema)}
            if "owner_work_id" not in template_columns:
                conn.execute(text(f"ALTER TABLE {qualified_table_name('document_templates', _engine)} ADD owner_work_id NVARCHAR(100) NULL;"))


def _assert_required_tables() -> None:
    if _engine is None:
        raise RuntimeError("Database engine not initialized.")
    query = text(
        """
        SELECT TABLE_NAME, COLUMN_NAME
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = :schema_name
          AND TABLE_NAME IN (
            'jobs',
            'job_artifacts',
            'job_events',
            'editor_presence',
            'audit_logs',
            'system_error_logs',
            'document_templates'
          );
        """
    )
    with _engine.connect() as conn:
        rows = conn.execute(query, {"schema_name": current_database_schema()}).fetchall()
    existing = {str(row[0]).lower() for row in rows}
    missing = [name for name in REQUIRED_TABLES if name.lower() not in existing]
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(
            f"Missing required SQL Server tables in schema {current_database_schema()}: {names}. Run scripts/init_sqlserver_schema.sql first."
        )
    template_columns = {
        str(row[1]).lower()
        for row in rows
        if str(row[0]).lower() == "document_templates"
    }
    if "payload_json" not in template_columns:
        raise RuntimeError(
            f"Missing required SQL Server column: {current_database_schema()}.document_templates.payload_json. "
            "Update the database schema before starting the app."
        )


def assert_required_schema() -> None:
    _assert_required_tables()


def session_scope() -> contextlib.AbstractContextManager[Session]:
    if _session_factory is None:
        raise RuntimeError("Database session factory not initialized.")

    @contextlib.contextmanager
    def _scope():
        session = _session_factory()
        try:
            yield session
            session.commit()
        except Exception:
            session.rollback()
            raise
        finally:
            session.close()

    return _scope()


def _serialize_payload(payload: dict[str, Any] | None) -> str | None:
    if payload is None:
        return None
    return json.dumps(payload, ensure_ascii=False)


def _deserialize_payload(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def create_job(
    *,
    job_id: str,
    job_type: str,
    stage: str,
    status: str = "queued",
    progress: float = 0.0,
    job_name: str | None = None,
    owner_work_id: str | None = None,
    target_lang: str | None = None,
    document_mode: str | None = None,
    payload: dict[str, Any] | None = None,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
) -> None:
    now = utcnow()
    with session_scope() as session:
        session.add(
            JobRecord(
                job_id=job_id,
                job_type=job_type,
                status=status,
                stage=stage,
                progress=progress,
                job_name=job_name,
                owner_work_id=owner_work_id,
                target_lang=target_lang,
                document_mode=document_mode,
                payload_json=_serialize_payload(payload),
                error_message=None,
                cancel_requested=False,
                retry_count=0,
                worker_id=None,
                started_at=started_at,
                completed_at=completed_at,
                created_at=now,
                updated_at=now,
            )
        )


def get_job(job_id: str) -> JobRecord | None:
    with session_scope() as session:
        return session.get(JobRecord, job_id)


def list_jobs(job_type: str | None = None) -> list[JobRecord]:
    with session_scope() as session:
        stmt = select(JobRecord)
        if job_type:
            stmt = stmt.where(JobRecord.job_type == job_type)
        stmt = stmt.order_by(JobRecord.updated_at.desc())
        return list(session.scalars(stmt).all())


def list_artifacts(job_ids: list[str] | tuple[str, ...] | set[str]) -> dict[str, dict[str, JobArtifactRecord]]:
    normalized_ids = [str(job_id) for job_id in job_ids if job_id]
    if not normalized_ids:
        return {}
    with session_scope() as session:
        stmt = (
            select(JobArtifactRecord)
            .where(JobArtifactRecord.job_id.in_(normalized_ids))
            .order_by(JobArtifactRecord.created_at.asc(), JobArtifactRecord.id.asc())
        )
        artifacts: dict[str, dict[str, JobArtifactRecord]] = {}
        for artifact in session.scalars(stmt).all():
            artifacts.setdefault(artifact.job_id, {})[artifact.artifact_type] = artifact
        return artifacts


def upsert_editor_presence(
    *,
    job_id: str,
    work_id: str,
    display_name: str | None = None,
    remote_addr: str | None = None,
    user_agent: str | None = None,
) -> None:
    cleaned_work_id = " ".join(str(work_id or "").split()).strip()
    if not job_id or not cleaned_work_id:
        return
    now = utcnow()
    with session_scope() as session:
        record = session.get(EditorPresenceRecord, (job_id, cleaned_work_id))
        if record is None:
            session.add(
                EditorPresenceRecord(
                    job_id=job_id,
                    work_id=cleaned_work_id,
                    display_name=str(display_name or "").strip() or None,
                    remote_addr=str(remote_addr or "").strip() or None,
                    user_agent=str(user_agent or "").strip()[:500] or None,
                    created_at=now,
                    last_seen_at=now,
                )
            )
            return
        record.display_name = str(display_name or "").strip() or record.display_name
        record.remote_addr = str(remote_addr or "").strip() or None
        record.user_agent = str(user_agent or "").strip()[:500] or None
        record.last_seen_at = now


def list_active_editor_presence(
    job_ids: list[str] | tuple[str, ...] | set[str],
    *,
    max_age_seconds: int = 60,
) -> dict[str, list[dict[str, Any]]]:
    normalized_ids = [str(job_id) for job_id in job_ids if job_id]
    if not normalized_ids:
        return {}
    cutoff = utcnow() - timedelta(seconds=max(1, int(max_age_seconds)))
    with session_scope() as session:
        stale = session.scalars(
            select(EditorPresenceRecord).where(EditorPresenceRecord.last_seen_at < cutoff)
        ).all()
        for record in stale:
            session.delete(record)
        stmt = (
            select(EditorPresenceRecord)
            .where(EditorPresenceRecord.job_id.in_(normalized_ids))
            .where(EditorPresenceRecord.last_seen_at >= cutoff)
            .order_by(EditorPresenceRecord.last_seen_at.desc())
        )
        result: dict[str, list[dict[str, Any]]] = {}
        now_ts = utcnow()
        for record in session.scalars(stmt).all():
            last_seen_at = _ensure_aware_utc(record.last_seen_at)
            result.setdefault(record.job_id, []).append(
                {
                    "work_id": record.work_id,
                    "display_name": record.display_name or record.work_id,
                    "last_seen_at": last_seen_at.timestamp(),
                    "seconds_ago": max(0, int((now_ts - last_seen_at).total_seconds())),
                }
            )
        return result


def update_job(job_id: str, **updates: Any) -> None:
    with session_scope() as session:
        record = session.get(JobRecord, job_id)
        if record is None:
            return
        for key, value in updates.items():
            if not hasattr(record, key):
                continue
            setattr(record, key, value)
        record.updated_at = utcnow()


def delete_job(job_id: str) -> bool:
    with session_scope() as session:
        record = session.get(JobRecord, job_id)
        if record is None:
            return False
        for artifact in session.scalars(
            select(JobArtifactRecord).where(JobArtifactRecord.job_id == job_id)
        ).all():
            session.delete(artifact)
        for event in session.scalars(
            select(JobEventRecord).where(JobEventRecord.job_id == job_id)
        ).all():
            session.delete(event)
        for presence in session.scalars(
            select(EditorPresenceRecord).where(EditorPresenceRecord.job_id == job_id)
        ).all():
            session.delete(presence)
        session.delete(record)
        return True


def request_cancel(job_id: str) -> bool:
    with session_scope() as session:
        record = session.get(JobRecord, job_id)
        if record is None:
            return False
        if record.status in {"completed", "failed", "cancelled"}:
            return False
        if record.status == "queued":
            record.cancel_requested = True
            record.status = "cancelled"
            record.completed_at = utcnow()
            record.updated_at = utcnow()
            return True
        record.cancel_requested = True
        record.status = "cancel_requested"
        record.updated_at = utcnow()
        return True


def requeue_job(
    job_id: str,
    *,
    stage: str = "queued",
    payload: dict[str, Any] | None = None,
    progress: float = 0.0,
) -> bool:
    with session_scope() as session:
        record = session.get(JobRecord, job_id)
        if record is None:
            return False
        if record.status in {"queued", "running"}:
            return False
        record.payload_json = _serialize_payload(payload) if payload is not None else record.payload_json
        record.status = "queued"
        record.stage = stage
        record.progress = progress
        record.error_message = None
        record.cancel_requested = False
        record.worker_id = None
        record.started_at = None
        record.completed_at = None
        record.retry_count = int(record.retry_count or 0) + 1
        record.updated_at = utcnow()
        return True


def append_event(job_id: str, event_type: str, stage: str | None = None, message: str | None = None) -> None:
    with session_scope() as session:
        session.add(
            JobEventRecord(
                job_id=job_id,
                event_type=event_type,
                stage=stage,
                message=message,
                created_at=utcnow(),
            )
        )


def list_recent_events(
    job_ids: list[str],
    *,
    event_type: str | None = None,
    limit_per_job: int = 3,
) -> dict[str, list[JobEventRecord]]:
    cleaned_ids = [str(job_id or "").strip() for job_id in job_ids if str(job_id or "").strip()]
    if not cleaned_ids or limit_per_job <= 0:
        return {}
    stmt = select(JobEventRecord).where(JobEventRecord.job_id.in_(cleaned_ids))
    if event_type:
        stmt = stmt.where(JobEventRecord.event_type == str(event_type).strip())
    stmt = stmt.order_by(JobEventRecord.created_at.desc(), JobEventRecord.id.desc())
    grouped: dict[str, list[JobEventRecord]] = {job_id: [] for job_id in cleaned_ids}
    with session_scope() as session:
        for event in session.scalars(stmt).all():
            bucket = grouped.setdefault(str(event.job_id), [])
            if len(bucket) < limit_per_job:
                bucket.append(event)
    return {job_id: list(reversed(events)) for job_id, events in grouped.items() if events}


def register_artifact(job_id: str, artifact_type: str, file_path: str) -> None:
    with session_scope() as session:
        session.add(
            JobArtifactRecord(
                job_id=job_id,
                artifact_type=artifact_type,
                file_path=file_path,
                created_at=utcnow(),
            )
        )


def replace_artifacts(job_id: str, artifacts: dict[str, str]) -> None:
    with session_scope() as session:
        for artifact in session.scalars(
            select(JobArtifactRecord).where(JobArtifactRecord.job_id == job_id)
        ).all():
            session.delete(artifact)
        now = utcnow()
        for artifact_type, file_path in artifacts.items():
            cleaned_type = str(artifact_type or "").strip()
            cleaned_path = str(file_path or "").strip().replace("\\", "/").lstrip("/")
            if not cleaned_type or not cleaned_path:
                continue
            session.add(
                JobArtifactRecord(
                    job_id=job_id,
                    artifact_type=cleaned_type,
                    file_path=cleaned_path,
                    created_at=now,
                )
            )


def claim_next_job(
    worker_id: str,
    concurrency_limits: dict[str, int] | None = None,
) -> JobRecord | None:
    concurrency_limits = concurrency_limits or {}
    ocr_limit = max(0, int(concurrency_limits.get("ocr_overlay", 1)))
    pdf_translate_limit = max(0, int(concurrency_limits.get("pdf_translate", 1)))
    doc_limit = max(0, int(concurrency_limits.get("doc_workspace", 1)))
    word_limit = max(0, int(concurrency_limits.get("word_translate", 1)))
    with session_scope() as session:
        bind = session.get_bind()
        if bind is None or bind.dialect.name != "mssql":
            raise RuntimeError("claim_next_job requires a SQL Server engine.")
        jobs_table = qualified_table_name("jobs", bind)
        result = session.execute(
            text(
                f"""
                ;WITH next_job AS (
                    SELECT TOP (1) job_id
                    FROM {jobs_table} WITH (UPDLOCK, READPAST, ROWLOCK)
                    WHERE status = :queued_status
                      AND cancel_requested = 0
                      AND (
                        (job_type IN ('ocr_overlay', 'template_source') AND ISNULL(stage, '') <> 'translate' AND :ocr_limit > 0 AND (
                            SELECT COUNT(*)
                            FROM {jobs_table} AS active
                            WHERE active.job_type IN ('ocr_overlay', 'template_source')
                              AND active.status IN ('running', 'cancel_requested')
                              AND active.worker_id IS NOT NULL
                              AND ISNULL(active.stage, '') <> 'translate'
                        ) < :ocr_limit)
                        OR
                        (job_type IN ('ocr_overlay', 'template_source') AND ISNULL(stage, '') = 'translate' AND :pdf_translate_limit > 0 AND (
                            SELECT COUNT(*)
                            FROM {jobs_table} AS active
                            WHERE active.job_type IN ('ocr_overlay', 'template_source')
                              AND active.status IN ('running', 'cancel_requested')
                              AND active.worker_id IS NOT NULL
                              AND ISNULL(active.stage, '') = 'translate'
                        ) < :pdf_translate_limit)
                        OR
                        (job_type = 'doc_workspace' AND :doc_limit > 0 AND (
                            SELECT COUNT(*)
                            FROM {jobs_table} AS active
                            WHERE active.job_type = 'doc_workspace'
                              AND active.status IN ('running', 'cancel_requested')
                              AND active.worker_id IS NOT NULL
                        ) < :doc_limit)
                        OR
                        (job_type = 'word_translate' AND :word_limit > 0 AND (
                            SELECT COUNT(*)
                            FROM {jobs_table} AS active
                            WHERE active.job_type = 'word_translate'
                              AND active.status IN ('running', 'cancel_requested')
                              AND active.worker_id IS NOT NULL
                        ) < :word_limit)
                      )
                    ORDER BY created_at ASC
                )
                UPDATE target
                SET status = :running_status,
                    worker_id = :worker_id,
                    started_at = COALESCE(started_at, SYSUTCDATETIME()),
                    updated_at = SYSUTCDATETIME()
                OUTPUT inserted.job_id
                FROM {jobs_table} AS target
                INNER JOIN next_job ON target.job_id = next_job.job_id;
                """
            ),
            {
                "queued_status": "queued",
                "running_status": "running",
                "worker_id": worker_id,
                "ocr_limit": ocr_limit,
                "pdf_translate_limit": pdf_translate_limit,
                "doc_limit": doc_limit,
                "word_limit": word_limit,
            },
        )
        row = result.first()
        if row is None:
            return None
        return session.get(JobRecord, row[0])


def _is_local_worker_id_stale(worker_id: str | None) -> bool:
    if not worker_id:
        return True
    match = _LOCAL_WORKER_ID_RE.fullmatch(str(worker_id).strip())
    if not match:
        return False
    pid = int(match.group(1))
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return True
    except PermissionError:
        return False
    return False


def recover_orphaned_active_jobs() -> list[str]:
    """Requeue active jobs that have no live worker ownership.

    Legitimate active jobs are claimed through ``claim_next_job``, which assigns
    ``worker_id`` atomically. If an active row has ``worker_id IS NULL`` or
    points to a dead local worker process, it is orphaned and should not block
    queue concurrency forever.
    """

    with session_scope() as session:
        candidates = list(
            session.scalars(
                select(JobRecord).where(JobRecord.status.in_(("running", "cancel_requested")))
            ).all()
        )
        recovered: list[str] = []
        for record in candidates:
            if not _is_local_worker_id_stale(record.worker_id):
                continue
            if record.status == "cancel_requested" or record.cancel_requested:
                record.status = "cancelled"
                record.stage = "cancelled"
                record.completed_at = utcnow()
            else:
                record.status = "queued"
                record.stage = "translate" if str(record.stage or "").strip().lower() == "translate" else "queued"
                record.started_at = None
                record.completed_at = None
                record.retry_count = int(record.retry_count or 0) + 1
            record.worker_id = None
            record.updated_at = utcnow()
            recovered.append(record.job_id)
        return recovered


def deserialize_payload(record: JobRecord | None) -> dict[str, Any]:
    if record is None:
        return {}
    return _deserialize_payload(record.payload_json)


def count_document_templates() -> int:
    with session_scope() as session:
        return int(session.scalar(select(func.count()).select_from(DocumentTemplateRecord)) or 0)
