from __future__ import annotations

import contextlib
import json
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, Integer, String, Text, create_engine, select, text
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

logger = logging.getLogger(__name__)


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


_engine = None
_session_factory: sessionmaker[Session] | None = None
REQUIRED_TABLES = ("jobs", "job_artifacts", "job_events")


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def init_app(app) -> None:
    global _engine, _session_factory
    database_url = app.config["DATABASE_URL"]
    if not database_url:
        raise RuntimeError("DATABASE_URL is required and must point to SQL Server.")
    if not database_url.lower().startswith("mssql"):
        raise RuntimeError("Only SQL Server DATABASE_URL values are supported.")
    _engine = create_engine(database_url, future=True, pool_pre_ping=True)
    _session_factory = sessionmaker(bind=_engine, future=True, expire_on_commit=False)
    _assert_required_tables()


def _assert_required_tables() -> None:
    if _engine is None:
        raise RuntimeError("Database engine not initialized.")
    query = text(
        """
        SELECT TABLE_NAME
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = 'dbo'
          AND TABLE_NAME IN ('jobs', 'job_artifacts', 'job_events');
        """
    )
    with _engine.connect() as conn:
        rows = conn.execute(query).fetchall()
    existing = {str(row[0]).lower() for row in rows}
    missing = [name for name in REQUIRED_TABLES if name.lower() not in existing]
    if missing:
        names = ", ".join(missing)
        raise RuntimeError(
            f"Missing required SQL Server tables: {names}. Run scripts/init_sqlserver_schema.sql first."
        )


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


def request_cancel(job_id: str) -> bool:
    with session_scope() as session:
        record = session.get(JobRecord, job_id)
        if record is None:
            return False
        if record.status in {"completed", "failed", "cancelled"}:
            return False
        record.cancel_requested = True
        record.status = "cancel_requested"
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


def claim_next_job(worker_id: str) -> JobRecord | None:
    with session_scope() as session:
        bind = session.get_bind()
        if bind is None or bind.dialect.name != "mssql":
            raise RuntimeError("claim_next_job requires a SQL Server engine.")
        result = session.execute(
            text(
                """
                ;WITH next_job AS (
                    SELECT TOP (1) job_id
                    FROM jobs WITH (UPDLOCK, READPAST, ROWLOCK)
                    WHERE status = :queued_status
                      AND cancel_requested = 0
                    ORDER BY created_at ASC
                )
                UPDATE jobs
                SET status = :running_status,
                    worker_id = :worker_id,
                    started_at = COALESCE(started_at, SYSUTCDATETIME()),
                    updated_at = SYSUTCDATETIME()
                OUTPUT inserted.job_id
                FROM jobs
                INNER JOIN next_job ON jobs.job_id = next_job.job_id;
                """
            ),
            {
                "queued_status": "queued",
                "running_status": "running",
                "worker_id": worker_id,
            },
        )
        row = result.first()
        if row is None:
            return None
        return session.get(JobRecord, row[0])


def deserialize_payload(record: JobRecord | None) -> dict[str, Any]:
    if record is None:
        return {}
    return _deserialize_payload(record.payload_json)
