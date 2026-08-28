from __future__ import annotations

import json
import logging
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import click
from flask import current_app, has_app_context, has_request_context, request
from flask_login import current_user
from sqlalchemy import func, or_, select

from . import alerts, job_store, state

_SYSTEM_ERROR_LEVEL_ORDER = {
    "DEBUG": 10,
    "INFO": 20,
    "WARNING": 30,
    "ERROR": 40,
    "CRITICAL": 50,
}


def current_actor() -> dict[str, str]:
    if not has_request_context() or not getattr(current_user, "is_authenticated", False):
        return {}
    work_id = " ".join(str(getattr(current_user, "work_id", "") or "").split()).strip()
    label = " ".join(str(getattr(current_user, "display_name", "") or "").split()).strip()
    return {"work_id": work_id, "label": label}


def record_audit(
    action: str,
    actor: dict[str, str] | None = None,
    detail: dict[str, Any] | None = None,
    job_id: str | None = None,
) -> bool:
    cleaned_action = " ".join(str(action or "").split()).strip()
    if not cleaned_action:
        return False

    actor_payload = actor if actor is not None else current_actor()
    work_id = _clean_text((actor_payload or {}).get("work_id") or (actor_payload or {}).get("username")) or None
    actor_label = _clean_text((actor_payload or {}).get("label"))
    detail_payload = dict(detail or {})
    if actor_label and "_actor_label" not in detail_payload:
        detail_payload["_actor_label"] = actor_label

    record = job_store.AuditLogRecord(
        created_at=job_store.utcnow(),
        action=cleaned_action,
        work_id=work_id,
        detail_json=_json_dumps(detail_payload),
        job_id=_clean_job_id(job_id),
        request_path=_request_path(),
        remote_addr=_remote_addr(),
    )
    try:
        with job_store.session_scope() as session:
            session.add(record)
        return True
    except Exception:
        _logger_exception("Database audit failed, falling back to JSONL")
        _append_fallback_jsonl(
            "fallback_audit.jsonl",
            {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "action": cleaned_action,
                "work_id": work_id,
                "detail": detail_payload,
                "job_id": _clean_job_id(job_id),
                "request_path": _request_path(),
                "remote_addr": _remote_addr(),
                "fallback": True,
            },
        )
        return False


def record_system_error(
    component: str,
    message: str,
    *,
    detail: dict[str, Any] | None = None,
    exc: Exception | None = None,
    job_id: str | None = None,
    level: str = "ERROR",
) -> bool:
    normalized_level = _normalize_system_error_level(level)
    if not should_persist_system_error(normalized_level):
        return False

    payload = dict(detail or {})
    error_type = ""
    if exc is not None:
        error_type = exc.__class__.__name__
        payload.setdefault("exception_message", str(exc))
        payload.setdefault(
            "traceback",
            "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).strip(),
        )

    cleaned_component = _clean_text(component) or "unknown"
    cleaned_message = (_clean_text(message) or "System error")[:500]
    cleaned_job_id = _clean_job_id(job_id)
    request_path = _request_path()
    remote_addr = _remote_addr()

    record = job_store.SystemErrorLogRecord(
        created_at=job_store.utcnow(),
        level=normalized_level,
        component=cleaned_component,
        message=cleaned_message,
        error_type=error_type or None,
        detail_json=_json_dumps(payload),
        job_id=cleaned_job_id,
        request_path=request_path,
        remote_addr=remote_addr,
    )
    persisted = False
    try:
        with job_store.session_scope() as session:
            session.add(record)
        persisted = True
    except Exception:
        _logger_exception("Failed to persist system error log")
        _append_fallback_jsonl(
            "system-error-fallback.jsonl",
            {
                "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "level": normalized_level,
                "component": cleaned_component,
                "message": cleaned_message,
                "error_type": error_type,
                "detail": payload,
                "job_id": cleaned_job_id,
                "request_path": request_path,
                "remote_addr": remote_addr,
                "fallback": True,
            },
        )

    _send_system_error_alert(
        component=cleaned_component,
        message=cleaned_message,
        error_type=error_type,
        job_id=cleaned_job_id,
        detail=payload,
    )
    return persisted


def list_audit_logs(
    *,
    page: int = 1,
    per_page: int = 50,
    q: str = "",
    action: str = "",
    job_id: str = "",
    start_date: str = "",
    end_date: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with job_store.session_scope() as session:
        stmt = select(job_store.AuditLogRecord)
        count_stmt = select(func.count()).select_from(job_store.AuditLogRecord)
        filters = []
        if q:
            search = f"%{q}%"
            filters.append(
                or_(
                    job_store.AuditLogRecord.action.ilike(search),
                    job_store.AuditLogRecord.work_id.ilike(search),
                    job_store.AuditLogRecord.detail_json.ilike(search),
                    job_store.AuditLogRecord.job_id.startswith(q, autoescape=True),
                )
            )
        if action:
            filters.append(job_store.AuditLogRecord.action.ilike(f"%{action}%"))
        if job_id:
            filters.append(job_store.AuditLogRecord.job_id.startswith(job_id, autoescape=True))
        filters.extend(_date_filters(job_store.AuditLogRecord.created_at, start_date, end_date))
        for item in filters:
            stmt = stmt.where(item)
            count_stmt = count_stmt.where(item)
        total_count = int(session.scalar(count_stmt) or 0)
        pagination = _pagination(total_count, page, per_page)
        rows = session.scalars(
            stmt.order_by(job_store.AuditLogRecord.created_at.desc())
            .offset((pagination["page"] - 1) * pagination["per_page"])
            .limit(pagination["per_page"])
        ).all()
        return [_audit_entry(row) for row in rows], pagination


def list_system_error_logs(
    *,
    page: int = 1,
    per_page: int = 50,
    q: str = "",
    component: str = "",
    level: str = "",
    job_id: str = "",
    start_date: str = "",
    end_date: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    with job_store.session_scope() as session:
        stmt = select(job_store.SystemErrorLogRecord)
        count_stmt = select(func.count()).select_from(job_store.SystemErrorLogRecord)
        filters = []
        if q:
            search = f"%{q}%"
            filters.append(
                or_(
                    job_store.SystemErrorLogRecord.component.ilike(search),
                    job_store.SystemErrorLogRecord.message.ilike(search),
                    job_store.SystemErrorLogRecord.error_type.ilike(search),
                    job_store.SystemErrorLogRecord.detail_json.ilike(search),
                    job_store.SystemErrorLogRecord.request_path.ilike(search),
                    job_store.SystemErrorLogRecord.job_id.startswith(q, autoescape=True),
                )
            )
        if component:
            filters.append(job_store.SystemErrorLogRecord.component.ilike(f"%{component}%"))
        if level:
            filters.append(job_store.SystemErrorLogRecord.level == _normalize_system_error_level(level))
        if job_id:
            filters.append(job_store.SystemErrorLogRecord.job_id.startswith(job_id, autoescape=True))
        filters.extend(_date_filters(job_store.SystemErrorLogRecord.created_at, start_date, end_date))
        for item in filters:
            stmt = stmt.where(item)
            count_stmt = count_stmt.where(item)
        total_count = int(session.scalar(count_stmt) or 0)
        pagination = _pagination(total_count, page, per_page)
        rows = session.scalars(
            stmt.order_by(job_store.SystemErrorLogRecord.created_at.desc())
            .offset((pagination["page"] - 1) * pagination["per_page"])
            .limit(pagination["per_page"])
        ).all()
        return [_system_error_entry(row) for row in rows], pagination


def cleanup_audit_logs(*, retention_days: int, dry_run: bool = False) -> dict[str, Any]:
    return _cleanup_records(job_store.AuditLogRecord, retention_days=retention_days, dry_run=dry_run)


def cleanup_system_error_logs(*, retention_days: int, dry_run: bool = False) -> dict[str, Any]:
    return _cleanup_records(job_store.SystemErrorLogRecord, retention_days=retention_days, dry_run=dry_run)


def register_audit_cli(app) -> None:
    @app.cli.command("audit-cleanup")
    @click.option("--days", default=None, type=int, help="Retention period in days. Defaults to AUDIT_LOG_RETENTION_DAYS.")
    @click.option("--dry-run", is_flag=True, help="Show how many rows would be deleted without deleting them.")
    def audit_cleanup_command(days: int | None, dry_run: bool) -> None:
        retention_days = int(days or current_app.config.get("AUDIT_LOG_RETENTION_DAYS") or 180)
        result = cleanup_audit_logs(retention_days=retention_days, dry_run=dry_run)
        _echo_cleanup("audit_cleanup", result)

    @app.cli.command("system-error-cleanup")
    @click.option("--days", default=None, type=int, help="Retention period in days. Defaults to SYSTEM_ERROR_LOG_RETENTION_DAYS.")
    @click.option("--dry-run", is_flag=True, help="Show how many rows would be deleted without deleting them.")
    def system_error_cleanup_command(days: int | None, dry_run: bool) -> None:
        retention_days = int(days or current_app.config.get("SYSTEM_ERROR_LOG_RETENTION_DAYS") or 180)
        result = cleanup_system_error_logs(retention_days=retention_days, dry_run=dry_run)
        _echo_cleanup("system_error_cleanup", result)


def should_persist_system_error(level: str) -> bool:
    return _system_error_level_value(level) >= _system_error_level_value(_system_error_db_min_level())


def _send_system_error_alert(
    *,
    component: str,
    message: str,
    error_type: str,
    job_id: str | None,
    detail: dict[str, Any],
) -> None:
    config = current_app.config if has_app_context() else alerts.state_alert_config()
    try:
        alerts.send_teams_alert(
            config,
            source=component,
            message=message,
            exception_type=error_type,
            job_id=job_id,
            detail=detail,
        )
    except Exception:
        _logger_exception("Failed to send Teams Alert for system error")


def _cleanup_records(model, *, retention_days: int, dry_run: bool) -> dict[str, Any]:
    days = int(retention_days)
    if days <= 0:
        raise ValueError("retention_days must be greater than 0")
    cutoff = job_store.utcnow() - timedelta(days=days)
    with job_store.session_scope() as session:
        rows = session.scalars(select(model).where(model.created_at < cutoff)).all()
        matched_count = len(rows)
        if not dry_run:
            for row in rows:
                session.delete(row)
    return {
        "retention_days": days,
        "cutoff": cutoff,
        "matched_count": matched_count,
        "deleted_count": 0 if dry_run else matched_count,
        "dry_run": dry_run,
    }


def _echo_cleanup(name: str, result: dict[str, Any]) -> None:
    click.echo(
        f"{name} "
        f"retention_days={result['retention_days']} "
        f"cutoff={result['cutoff'].strftime('%Y-%m-%d %H:%M:%S')} "
        f"matched={result['matched_count']} "
        f"deleted={result['deleted_count']} "
        f"dry_run={'1' if result['dry_run'] else '0'}"
    )


def _audit_entry(row: job_store.AuditLogRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": row.created_at,
        "action": row.action,
        "work_id": row.work_id or "-",
        "detail": _json_loads(row.detail_json),
        "job_id": row.job_id or "",
        "request_path": row.request_path or "",
        "remote_addr": row.remote_addr or "",
    }


def _system_error_entry(row: job_store.SystemErrorLogRecord) -> dict[str, Any]:
    return {
        "id": row.id,
        "created_at": row.created_at,
        "level": row.level,
        "component": row.component,
        "message": row.message,
        "error_type": row.error_type or "",
        "detail": _json_loads(row.detail_json),
        "job_id": row.job_id or "",
        "request_path": row.request_path or "",
        "remote_addr": row.remote_addr or "",
    }


def _pagination(total_count: int, page: int, per_page: int) -> dict[str, Any]:
    per_page = max(1, min(int(per_page or 50), 200))
    total_pages = (total_count + per_page - 1) // per_page
    normalized_page = max(1, min(int(page or 1), total_pages)) if total_pages else 1
    return {
        "total_count": total_count,
        "page": normalized_page,
        "per_page": per_page,
        "total_pages": total_pages,
        "has_prev": normalized_page > 1,
        "has_next": normalized_page < total_pages,
    }


def _date_filters(column, start_date: str, end_date: str) -> list[Any]:
    filters = []
    start = _parse_date(start_date, end_of_day=False)
    end = _parse_date(end_date, end_of_day=True)
    if start is not None:
        filters.append(column >= start)
    if end is not None:
        filters.append(column <= end)
    return filters


def _parse_date(value: str, *, end_of_day: bool) -> datetime | None:
    cleaned = str(value or "").strip()
    if not cleaned:
        return None
    suffix = " 23:59:59" if end_of_day else " 00:00:00"
    try:
        return datetime.strptime(cleaned + suffix, "%Y-%m-%d %H:%M:%S")
    except ValueError:
        return None


def _normalize_system_error_level(level: str) -> str:
    normalized = str(level or "ERROR").strip().upper() or "ERROR"
    return "WARNING" if normalized == "WARN" else normalized


def _system_error_level_value(level: str) -> int:
    return _SYSTEM_ERROR_LEVEL_ORDER.get(_normalize_system_error_level(level), _SYSTEM_ERROR_LEVEL_ORDER["ERROR"])


def _system_error_db_min_level() -> str:
    if has_app_context():
        return _normalize_system_error_level(current_app.config.get("SYSTEM_ERROR_DB_MIN_LEVEL") or "ERROR")
    return _normalize_system_error_level(state.SYSTEM_ERROR_DB_MIN_LEVEL)


def _clean_text(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def _clean_job_id(value: str | None) -> str | None:
    cleaned = _clean_text(value)
    return cleaned or None


def _request_path() -> str | None:
    if not has_request_context():
        return None
    query = request.query_string.decode("utf-8", errors="ignore")
    return f"{request.path}?{query}" if query else request.path


def _remote_addr() -> str | None:
    if not has_request_context():
        return None
    return str(request.headers.get("X-Forwarded-For") or request.remote_addr or "").split(",", 1)[0].strip() or None


def _json_dumps(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, default=str)


def _json_loads(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except Exception:
        return {"raw": raw}
    return data if isinstance(data, dict) else {"value": data}


def _append_fallback_jsonl(filename: str, payload: dict[str, Any]) -> None:
    try:
        log_dir = _fallback_log_dir()
        log_dir.mkdir(parents=True, exist_ok=True)
        with (log_dir / filename).open("a", encoding="utf-8") as file_obj:
            file_obj.write(json.dumps(payload, ensure_ascii=False, default=str))
            file_obj.write("\n")
    except Exception:
        _logger_exception("Failed to write fallback audit/system log")


def _fallback_log_dir() -> Path:
    if has_app_context():
        configured = current_app.config.get("APP_LOG_DIR")
        if configured:
            return Path(str(configured)).expanduser()
    return state.APP_LOG_DIR


def _logger_exception(message: str) -> None:
    if has_app_context():
        current_app.logger.exception(message)
        return
    logging.getLogger(__name__).exception(message)
