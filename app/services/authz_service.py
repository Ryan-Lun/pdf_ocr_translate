from __future__ import annotations

from typing import Any, Optional
from urllib.parse import urlparse

from flask import current_app, has_app_context

from . import jobs, job_store


def sanitize_next_url(raw_next: Optional[str]) -> Optional[str]:
    if not raw_next:
        return None
    candidate = str(raw_next).strip()
    if candidate.endswith("?"):
        candidate = candidate[:-1]
    if not candidate.startswith("/") or candidate.startswith("//"):
        return None
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return None
    return candidate


def normalize_work_id(value: object) -> str:
    return " ".join(str(value or "").split()).strip()


def current_work_id(user: Any) -> str:
    return normalize_work_id(getattr(user, "work_id", ""))


def user_is_admin(user: Any) -> bool:
    return bool(getattr(user, "is_admin", False))


def owner_access_enabled() -> bool:
    if has_app_context():
        return bool(current_app.config.get("OWNER_ACCESS_ENABLED", True))
    return True


def can_access_owner(user: Any, owner_work_id: object) -> bool:
    if not owner_access_enabled():
        return True
    if user_is_admin(user):
        return True
    owner = normalize_work_id(owner_work_id)
    if not owner:
        return False
    return current_work_id(user) == owner


def resolve_job_owner_work_id(job_id: str) -> str:
    if not jobs.safe_job_id(job_id):
        return ""
    record = job_store.get_job(job_id)
    if record is not None:
        owner = normalize_work_id(getattr(record, "owner_work_id", ""))
        if owner:
            return owner
    meta = jobs.load_job_meta(jobs.job_dir(job_id)) or {}
    return normalize_work_id(meta.get("owner_work_id"))


def can_access_job(user: Any, job_id: str) -> bool:
    return can_access_owner(user, resolve_job_owner_work_id(job_id))


def resolve_template_owner_work_id(template: dict[str, Any] | None) -> str:
    if not isinstance(template, dict):
        return ""
    owner = normalize_work_id(template.get("owner_work_id"))
    if owner:
        return owner
    source_job_id = normalize_work_id(template.get("source_job_id"))
    if jobs.safe_job_id(source_job_id):
        return resolve_job_owner_work_id(source_job_id)
    return ""


def can_access_template(user: Any, template: dict[str, Any] | None) -> bool:
    return True
