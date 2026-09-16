from __future__ import annotations

import csv
import json
import logging
import re
import threading
import uuid
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from html import escape as _html_escape, unescape as _html_unescape
from io import BytesIO
from pathlib import Path
from typing import TypeAlias
import zipfile

from sqlalchemy import func, select, true
from flask import has_request_context
from flask_login import current_user
from xml.etree import ElementTree as ET

from lang_utils import normalize_lang_code

from . import job_store, state

logger = logging.getLogger(__name__)

try:
    import xlsxwriter
except Exception:  # pragma: no cover - optional dependency in runtime env
    xlsxwriter = None

_PROTECTED_TERM_PREFIX = "[[[GLOSSARY_TERM_"
_PROTECTED_TERM_PATTERN = re.compile(r"\[{3,}GLOSSARY_TERM_\d+::(.*?)\]{3,}")
_REQUIRED_TERM_PATTERN = re.compile(
    r"<term\s+id=[\"\'](\d{4})[\"\']>(.*?)</term>",
    re.DOTALL,
)
_ASCII_WORD_RE = re.compile(r"[A-Za-z0-9]")
_ASCII_TERM_TRAILING_RE = re.compile(r"[A-Za-z0-9\]\)%.]$")
_ASCII_TERM_LEADING_RE = re.compile(r"^[A-Za-z0-9\[\(]")
_SPREADSHEET_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
_GLOSSARY_CACHE_LOCK = threading.Lock()
_GLOBAL_GLOSSARY_CACHE: tuple[Path, float | None, list[dict[str, str]]] | None = None
_COMBINED_GLOSSARY_CACHE: tuple[
    tuple[tuple[str, float | None], ...],
    list[tuple[str, str]],
] | None = None
_SYSTEM_GLOSSARY_CACHE: tuple[
    tuple[tuple[str, float | None], ...],
    list[dict[str, str]],
] | None = None

STATUS_ACTIVE = "active"
STATUS_DISABLED = "disabled"
VALIDATION_TYPE_STRICT_REQUIRED = "strict_required"
VALIDATION_TYPE_LEXICAL_REQUIRED = "lexical_required"
VALIDATION_TYPE_REFERENCE_ONLY = "reference_only"
VALIDATION_TYPES = frozenset(
    {
        VALIDATION_TYPE_STRICT_REQUIRED,
        VALIDATION_TYPE_LEXICAL_REQUIRED,
        VALIDATION_TYPE_REFERENCE_ONLY,
    }
)
DEFAULT_DEPARTMENT_GLOSSARY_CODE = "regulatory-document-control"
DEFAULT_DEPARTMENT_GLOSSARY_NAME = "法規文管部"


@dataclass(frozen=True)
class DepartmentGlossaryLibrary:
    library_id: int
    code: str
    name: str
    department_code: str
    is_default: bool
    is_active: bool


@dataclass(frozen=True)
class SelectedDepartmentGlossary:
    library_id: int
    code: str
    name: str
    department_code: str
    is_active: bool
    entry_count: int

    def to_context(self) -> dict[str, object]:
        return {
            "source": "sql",
            "library_id": self.library_id,
            "library_code": self.code,
            "library_name": self.name,
            "department_code": self.department_code,
            "entry_count": self.entry_count,
        }


class DepartmentGlossarySelectionError(ValueError):
    def __init__(self, code: str, user_message: str):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message


class DepartmentGlossaryLibraryError(ValueError):
    def __init__(self, code: str, user_message: str):
        super().__init__(user_message)
        self.code = code
        self.user_message = user_message


@dataclass(frozen=True)
class DepartmentGlossaryEntry:
    entry_id: int
    library_id: int
    source_lang: str
    target_lang: str
    source_term: str
    target_term: str
    status: str
    validation_type: str = VALIDATION_TYPE_STRICT_REQUIRED
    priority: int = 0
    notes: str | None = None
    created_by_work_id: str | None = None
    updated_by_work_id: str | None = None


IMPORT_ACTION_CREATED = "created"
IMPORT_ACTION_UPDATED = "updated"
IMPORT_ACTION_UNCHANGED = "unchanged"
IMPORT_ACTION_WOULD_CREATE = "would_create"
IMPORT_ACTION_WOULD_UPDATE = "would_update"
IMPORT_ACTION_INVALID = "invalid"
IMPORT_ACTION_DUPLICATE = "duplicate"
IMPORT_REASON_NEW_ENTRY = "new_entry"
IMPORT_REASON_EXISTING_TERM_UPDATED = "existing_term_updated"
IMPORT_REASON_EXISTING_TERM_UNCHANGED = "existing_term_unchanged"
IMPORT_REASON_MISSING_SOURCE_TERM = "missing_source_term"
IMPORT_REASON_MISSING_TARGET_TERM = "missing_target_term"
IMPORT_REASON_ITEM_MUST_BE_OBJECT = "item_must_be_object"
IMPORT_REASON_JSON_MUST_BE_LIST = "json_must_be_list"
IMPORT_REASON_DUPLICATE_SOURCE_TERM = "duplicate_source_term"


VALIDATION_REVIEW_CSV_COLUMNS = (
    "entry_id",
    "library_id",
    "source_lang",
    "target_lang",
    "source_term",
    "target_term",
    "current_validation_type",
    "suggested_validation_type",
    "classification_reason",
    "confidence",
    "reviewed_validation_type",
    "review_note",
)


@dataclass(frozen=True)
class DepartmentGlossaryValidationReviewExportSummary:
    library_id: int
    library_code: str
    output_path: Path
    exported: int


APPLY_REVIEW_ACTION_UPDATED = "updated"
APPLY_REVIEW_ACTION_WOULD_UPDATE = "would_update"
APPLY_REVIEW_ACTION_SKIPPED = "skipped"
APPLY_REVIEW_ACTION_INVALID = "invalid"
APPLY_REVIEW_ACTION_UNCHANGED = "unchanged"
APPLY_REVIEW_REASON_REVIEWED_VALUE_BLANK = "reviewed_validation_type_blank"
APPLY_REVIEW_REASON_VALIDATION_TYPE_UPDATED = "validation_type_updated"
APPLY_REVIEW_REASON_VALIDATION_TYPE_UNCHANGED = "validation_type_unchanged"
APPLY_REVIEW_REASON_INVALID_VALIDATION_TYPE = "invalid_validation_type"
APPLY_REVIEW_REASON_ENTRY_ID_INVALID = "entry_id_invalid"
APPLY_REVIEW_REASON_LIBRARY_ID_INVALID = "library_id_invalid"
APPLY_REVIEW_REASON_ENTRY_NOT_FOUND = "entry_not_found"
APPLY_REVIEW_REASON_ENTRY_IDENTITY_MISMATCH = "entry_identity_mismatch"


@dataclass(frozen=True)
class DepartmentGlossaryValidationReviewApplyDetail:
    row_number: int
    action: str
    reason: str
    entry_id: int | None = None
    reviewed_validation_type: str = ""


@dataclass(frozen=True)
class DepartmentGlossaryValidationReviewApplySummary:
    dry_run: bool
    library_id: int
    scanned: int = 0
    would_update: int = 0
    updated: int = 0
    skipped: int = 0
    invalid: int = 0
    unchanged: int = 0
    details: tuple[DepartmentGlossaryValidationReviewApplyDetail, ...] = ()


@dataclass(frozen=True)
class DepartmentGlossaryImportDetail:
    row_number: int
    action: str
    reason: str
    source_term: str = ""
    target_term: str = ""
    entry_id: int | None = None


@dataclass(frozen=True)
class DepartmentGlossaryImportSummary:
    dry_run: bool
    library_id: int | None
    scanned: int = 0
    created: int = 0
    updated: int = 0
    unchanged: int = 0
    would_create: int = 0
    would_update: int = 0
    invalid: int = 0
    duplicates: int = 0
    details: tuple[DepartmentGlossaryImportDetail, ...] = ()


@dataclass(frozen=True)
class RequiredGlossaryTerm:
    id: str
    source: str
    target: str


@dataclass(frozen=True)
class GlossaryApplication:
    text: str
    required_terms: tuple[RequiredGlossaryTerm, ...]


RequiredTermContext: TypeAlias = (
    GlossaryApplication | Iterable[RequiredGlossaryTerm] | Mapping[str, str] | None
)


def _escape_required_term_target(value: str) -> str:
    return _html_escape(value, quote=True).replace("&#x27;", "&apos;")


def _unescape_required_term_target(value: str) -> str:
    return _html_unescape(value)


def _required_term_target_map(required_terms: RequiredTermContext) -> dict[str, str]:
    terms = _required_terms_tuple(required_terms)
    if terms is not None:
        return {term.id: term.target for term in terms}
    if isinstance(required_terms, Mapping):
        return {str(term_id): str(target) for term_id, target in required_terms.items()}
    return {}


def _required_terms_tuple(
    required_terms: RequiredTermContext,
) -> tuple[RequiredGlossaryTerm, ...] | None:
    if required_terms is None:
        return tuple()
    if isinstance(required_terms, GlossaryApplication):
        return tuple(required_terms.required_terms)
    if isinstance(required_terms, Mapping):
        return None
    return tuple(required_terms)


def summarize_required_glossary_hits(
    hits_by_location: Iterable[tuple[str, RequiredTermContext]],
) -> list[dict[str, object]]:
    summary: dict[tuple[str, str], dict[str, object]] = {}
    for raw_location, required_terms in hits_by_location:
        terms = _required_terms_tuple(required_terms)
        if not terms:
            continue
        location = str(raw_location or "").strip()
        for term in terms:
            key = (term.source, term.target)
            item = summary.get(key)
            if item is None:
                item = {
                    "source_term": term.source,
                    "approved_term": term.target,
                    "count": 0,
                    "locations": [],
                }
                summary[key] = item
            item["count"] = int(item["count"]) + 1
            locations = item["locations"]
            if isinstance(locations, list) and location and location not in locations:
                locations.append(location)
    return list(summary.values())


def write_required_glossary_hits_artifact(
    job_dir: Path,
    hits_by_location: Iterable[tuple[str, RequiredTermContext]],
    *,
    filename: str = "glossary_hits.json",
) -> Path:
    path = Path(job_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            summarize_required_glossary_hits(hits_by_location),
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return path


def _normalize_glossary_lang(value: str) -> str:
    normalized = normalize_lang_code(value)
    return normalized or str(value or "").strip().lower() or "auto"


def _clean_department_glossary_status(value: str) -> str:
    status = str(value or STATUS_ACTIVE).strip().lower()
    if status not in {STATUS_ACTIVE, STATUS_DISABLED}:
        raise ValueError(f"Unsupported Department Glossary status: {value}")
    return status


def _clean_department_glossary_validation_type(value: str | None) -> str:
    validation_type = str(value or VALIDATION_TYPE_STRICT_REQUIRED).strip().lower()
    if validation_type not in VALIDATION_TYPES:
        raise ValueError(f"Unsupported Department Glossary validation_type: {value}")
    return validation_type


def _library_from_record(record: job_store.DepartmentGlossaryLibraryRecord) -> DepartmentGlossaryLibrary:
    return DepartmentGlossaryLibrary(
        library_id=int(record.id),
        code=record.code,
        name=record.name,
        department_code=record.department_code,
        is_default=bool(record.is_default),
        is_active=bool(record.is_active),
    )


def _entry_from_record(record: job_store.DepartmentGlossaryEntryRecord) -> DepartmentGlossaryEntry:
    return DepartmentGlossaryEntry(
        entry_id=int(record.id),
        library_id=int(record.library_id),
        source_lang=record.source_lang,
        target_lang=record.target_lang,
        source_term=record.source_term,
        target_term=record.target_term,
        status=record.status,
        validation_type=_clean_department_glossary_validation_type(
            getattr(record, "validation_type", None)
        ),
        priority=int(record.priority or 0),
        notes=record.notes,
        created_by_work_id=record.created_by_work_id,
        updated_by_work_id=record.updated_by_work_id,
    )


def _current_request_work_id() -> str:
    if not has_request_context() or not getattr(current_user, "is_authenticated", False):
        return ""
    return " ".join(str(getattr(current_user, "work_id", "") or "").split()).strip()


def _resolve_glossary_audit_actor(explicit_work_id: object = None) -> str:
    request_work_id = _current_request_work_id()
    if request_work_id:
        return request_work_id
    explicit = " ".join(str(explicit_work_id or "").split()).strip()
    return explicit or "system"


def _library_audit_payload(record: job_store.DepartmentGlossaryLibraryRecord | DepartmentGlossaryLibrary | None) -> dict[str, object] | None:
    if record is None:
        return None
    if isinstance(record, DepartmentGlossaryLibrary):
        return {
            "id": record.library_id,
            "code": record.code,
            "name": record.name,
            "department_code": record.department_code,
            "is_default": record.is_default,
            "is_active": record.is_active,
        }
    return {
        "id": int(record.id),
        "code": record.code,
        "name": record.name,
        "department_code": record.department_code,
        "is_default": bool(record.is_default),
        "is_active": bool(record.is_active),
    }


def _entry_audit_payload(record: job_store.DepartmentGlossaryEntryRecord | DepartmentGlossaryEntry | None) -> dict[str, object] | None:
    if record is None:
        return None
    if isinstance(record, DepartmentGlossaryEntry):
        return {
            "id": record.entry_id,
            "library_id": record.library_id,
            "source_lang": record.source_lang,
            "target_lang": record.target_lang,
            "source_term": record.source_term,
            "target_term": record.target_term,
            "status": record.status,
            "validation_type": record.validation_type,
            "priority": record.priority,
            "notes": record.notes,
            "created_by_work_id": record.created_by_work_id,
            "updated_by_work_id": record.updated_by_work_id,
        }
    return {
        "id": int(record.id),
        "library_id": int(record.library_id),
        "source_lang": record.source_lang,
        "target_lang": record.target_lang,
        "source_term": record.source_term,
        "target_term": record.target_term,
        "status": record.status,
        "validation_type": _clean_department_glossary_validation_type(
            getattr(record, "validation_type", None)
        ),
        "priority": int(record.priority or 0),
        "notes": record.notes,
        "created_by_work_id": record.created_by_work_id,
        "updated_by_work_id": record.updated_by_work_id,
    }


def _json_or_none(payload: dict[str, object] | None) -> str | None:
    if payload is None:
        return None
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _record_glossary_audit_event(
    session,
    *,
    action: str,
    target_type: str,
    target_id: int,
    before: dict[str, object] | None,
    after: dict[str, object] | None,
    actor_work_id: object = None,
    created_at=None,
) -> None:
    session.add(
        job_store.GlossaryAuditEventRecord(
            created_at=created_at or job_store.utcnow(),
            actor_work_id=_resolve_glossary_audit_actor(actor_work_id),
            action=str(action),
            target_type=str(target_type),
            target_id=int(target_id),
            before_json=_json_or_none(before),
            after_json=_json_or_none(after),
        )
    )


def _glossary_audit_event_to_payload(row: job_store.GlossaryAuditEventRecord) -> dict[str, object]:
    return {
        "id": int(row.id),
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "actor_work_id": row.actor_work_id,
        "action": row.action,
        "target_type": row.target_type,
        "target_id": int(row.target_id),
        "before": json.loads(row.before_json) if row.before_json else None,
        "after": json.loads(row.after_json) if row.after_json else None,
    }


def list_glossary_audit_events(
    *,
    target_type: str | None = None,
    target_id: int | None = None,
    actor_work_id: str | None = None,
    action: str | None = None,
    limit: int = 100,
) -> list[dict[str, object]]:
    with job_store.session_scope() as session:
        stmt = select(job_store.GlossaryAuditEventRecord)
        if target_type:
            stmt = stmt.where(job_store.GlossaryAuditEventRecord.target_type == str(target_type))
        if target_id is not None:
            stmt = stmt.where(job_store.GlossaryAuditEventRecord.target_id == int(target_id))
        if actor_work_id:
            stmt = stmt.where(job_store.GlossaryAuditEventRecord.actor_work_id == str(actor_work_id))
        if action:
            stmt = stmt.where(job_store.GlossaryAuditEventRecord.action == str(action))
        rows = session.scalars(
            stmt.order_by(
                job_store.GlossaryAuditEventRecord.created_at.desc(),
                job_store.GlossaryAuditEventRecord.id.desc(),
            ).limit(max(1, min(int(limit or 100), 500)))
        ).all()
        return [_glossary_audit_event_to_payload(row) for row in rows]


def _clean_department_glossary_library_name(name: object) -> str:
    cleaned = " ".join(str(name or "").split()).strip()
    if not cleaned:
        raise DepartmentGlossaryLibraryError(
            "missing_department_glossary_library_name",
            "請輸入部門詞彙庫名稱",
        )
    return cleaned


def _clean_department_glossary_department_code(department_code: object) -> str:
    cleaned = " ".join(str(department_code or "").split()).strip()
    if not cleaned:
        raise DepartmentGlossaryLibraryError(
            "missing_department_glossary_department_code",
            "請輸入部門代碼",
        )
    return cleaned


def _slugify_department_glossary_code(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")
    return slug[:80].strip("-") or "department-glossary"


def _generate_department_glossary_code(
    *,
    name: str,
    department_code: str,
) -> str:
    base = _slugify_department_glossary_code(f"{department_code}-{name}")
    suffix = uuid.uuid4().hex[:8]
    suffix_text = f"-{suffix}"
    return f"{base[:100 - len(suffix_text)]}{suffix_text}"


def _get_department_glossary_library_record(session, library_id: int):
    record = session.get(job_store.DepartmentGlossaryLibraryRecord, int(library_id))
    if record is None:
        raise DepartmentGlossaryLibraryError(
            "department_glossary_library_not_found",
            "部門詞彙庫不存在",
        )
    return record


def _job_payload_references_department_glossary_library(record, library_id: int) -> bool:
    payload = job_store.deserialize_payload(record)
    value = payload.get("department_glossary_library_id")
    if value is None:
        return False
    try:
        return int(value) == int(library_id)
    except (TypeError, ValueError):
        return False


def active_job_references_department_glossary_library(library_id: int) -> list[dict[str, str | None]]:
    with job_store.session_scope() as session:
        records = session.scalars(
            select(job_store.JobRecord)
            .where(job_store.JobRecord.status.in_(("queued", "running", "cancel_requested")))
            .order_by(job_store.JobRecord.updated_at.desc())
        ).all()
        matches = [
            record
            for record in records
            if _job_payload_references_department_glossary_library(record, library_id)
        ]
        return [
            {
                "job_id": record.job_id,
                "job_type": record.job_type,
                "status": record.status,
                "stage": record.stage,
                "job_name": record.job_name,
            }
            for record in matches
        ]


def create_department_glossary_library(
    *,
    name: object,
    department_code: object,
    actor_work_id: str | None = None,
) -> DepartmentGlossaryLibrary:
    cleaned_name = _clean_department_glossary_library_name(name)
    cleaned_department_code = _clean_department_glossary_department_code(department_code)
    now = job_store.utcnow()
    with job_store.session_scope() as session:
        code = _generate_department_glossary_code(
            name=cleaned_name,
            department_code=cleaned_department_code,
        )
        record = job_store.DepartmentGlossaryLibraryRecord(
            code=code,
            name=cleaned_name,
            department_code=cleaned_department_code,
            is_default=False,
            is_active=True,
            created_at=now,
            updated_at=now,
        )
        session.add(record)
        session.flush()
        after = _library_audit_payload(record)
        _record_glossary_audit_event(
            session,
            action="create",
            target_type="library",
            target_id=int(record.id),
            before=None,
            after=after,
            actor_work_id=actor_work_id,
            created_at=now,
        )
        return _library_from_record(record)


def update_department_glossary_library(
    library_id: int,
    *,
    name: object,
    department_code: object,
    actor_work_id: str | None = None,
) -> DepartmentGlossaryLibrary:
    cleaned_name = _clean_department_glossary_library_name(name)
    cleaned_department_code = _clean_department_glossary_department_code(department_code)
    with job_store.session_scope() as session:
        record = _get_department_glossary_library_record(session, int(library_id))
        before = _library_audit_payload(record)
        now = job_store.utcnow()
        record.name = cleaned_name
        record.department_code = cleaned_department_code
        record.updated_at = now
        session.flush()
        after = _library_audit_payload(record)
        if before != after:
            _record_glossary_audit_event(
                session,
                action="update",
                target_type="library",
                target_id=int(record.id),
                before=before,
                after=after,
                actor_work_id=actor_work_id,
                created_at=now,
            )
        return _library_from_record(record)


def disable_department_glossary_library(
    library_id: int,
    *,
    actor_work_id: str | None = None,
) -> DepartmentGlossaryLibrary:
    blocking_jobs = active_job_references_department_glossary_library(int(library_id))
    if blocking_jobs:
        raise DepartmentGlossaryLibraryError(
            "department_glossary_library_has_active_jobs",
            "此部門詞彙庫仍有執行中或佇列中的任務，請等待任務完成後再停用。",
        )
    with job_store.session_scope() as session:
        record = _get_department_glossary_library_record(session, int(library_id))
        before = _library_audit_payload(record)
        now = job_store.utcnow()
        record.is_active = False
        record.updated_at = now
        session.flush()
        after = _library_audit_payload(record)
        if before != after:
            _record_glossary_audit_event(
                session,
                action="disable",
                target_type="library",
                target_id=int(record.id),
                before=before,
                after=after,
                actor_work_id=actor_work_id,
                created_at=now,
            )
        return _library_from_record(record)


def activate_department_glossary_library(
    library_id: int,
    *,
    actor_work_id: str | None = None,
) -> DepartmentGlossaryLibrary:
    with job_store.session_scope() as session:
        record = _get_department_glossary_library_record(session, int(library_id))
        before = _library_audit_payload(record)
        now = job_store.utcnow()
        record.is_active = True
        record.updated_at = now
        session.flush()
        after = _library_audit_payload(record)
        if before != after:
            _record_glossary_audit_event(
                session,
                action="activate",
                target_type="library",
                target_id=int(record.id),
                before=before,
                after=after,
                actor_work_id=actor_work_id,
                created_at=now,
            )
        return _library_from_record(record)


def get_or_create_department_glossary_library(
    *,
    code: str,
    name: str,
    department_code: str,
    is_default: bool = False,
    is_active: bool = True,
    actor_work_id: str | None = None,
) -> DepartmentGlossaryLibrary:
    cleaned_code = str(code or "").strip()
    cleaned_name = str(name or "").strip()
    cleaned_department_code = str(department_code or "").strip()
    if not cleaned_code or not cleaned_name or not cleaned_department_code:
        raise ValueError("Department Glossary library code, name, and department code are required.")
    now = job_store.utcnow()
    with job_store.session_scope() as session:
        record = session.scalar(
            select(job_store.DepartmentGlossaryLibraryRecord).where(
                job_store.DepartmentGlossaryLibraryRecord.code == cleaned_code
            )
        )
        if record is None:
            record = job_store.DepartmentGlossaryLibraryRecord(
                code=cleaned_code,
                name=cleaned_name,
                department_code=cleaned_department_code,
                is_default=bool(is_default),
                is_active=bool(is_active),
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            session.flush()
            _record_glossary_audit_event(
                session,
                action="create",
                target_type="library",
                target_id=int(record.id),
                before=None,
                after=_library_audit_payload(record),
                actor_work_id=actor_work_id,
                created_at=now,
            )
        else:
            before = _library_audit_payload(record)
            record.name = cleaned_name
            record.department_code = cleaned_department_code
            record.is_default = bool(is_default)
            record.is_active = bool(is_active)
            record.updated_at = now
            session.flush()
            after = _library_audit_payload(record)
            if before != after:
                _record_glossary_audit_event(
                    session,
                    action="update",
                    target_type="library",
                    target_id=int(record.id),
                    before=before,
                    after=after,
                    actor_work_id=actor_work_id,
                    created_at=now,
                )
        return _library_from_record(record)


def get_or_create_default_department_glossary(
    *,
    actor_work_id: str | None = None,
) -> DepartmentGlossaryLibrary:
    existing = _find_department_glossary_library_by_code(DEFAULT_DEPARTMENT_GLOSSARY_CODE)
    if existing is not None:
        if existing.is_default:
            return existing
        with job_store.session_scope() as session:
            record = _get_department_glossary_library_record(session, existing.library_id)
            before = _library_audit_payload(record)
            now = job_store.utcnow()
            record.is_default = True
            record.updated_at = now
            session.flush()
            after = _library_audit_payload(record)
            if before != after:
                _record_glossary_audit_event(
                    session,
                    action="update",
                    target_type="library",
                    target_id=int(record.id),
                    before=before,
                    after=after,
                    actor_work_id=actor_work_id,
                    created_at=now,
                )
            return _library_from_record(record)

    return get_or_create_department_glossary_library(
        code=DEFAULT_DEPARTMENT_GLOSSARY_CODE,
        name=DEFAULT_DEPARTMENT_GLOSSARY_NAME,
        department_code=DEFAULT_DEPARTMENT_GLOSSARY_NAME,
        is_default=True,
        is_active=True,
        actor_work_id=actor_work_id,
    )


def list_department_glossary_libraries(*, active_only: bool = False) -> list[DepartmentGlossaryLibrary]:
    with job_store.session_scope() as session:
        stmt = select(job_store.DepartmentGlossaryLibraryRecord)
        if active_only:
            stmt = stmt.where(job_store.DepartmentGlossaryLibraryRecord.is_active == true())
        stmt = stmt.order_by(
            job_store.DepartmentGlossaryLibraryRecord.is_default.desc(),
            job_store.DepartmentGlossaryLibraryRecord.name.asc(),
            job_store.DepartmentGlossaryLibraryRecord.id.asc(),
        )
        return [_library_from_record(record) for record in session.scalars(stmt).all()]


def _parse_selected_department_glossary_library_id(value: object) -> int | None:
    if value is None:
        return None
    if isinstance(value, str):
        value = value.strip()
        if not value:
            return None
    try:
        library_id = int(value)
    except (TypeError, ValueError):
        raise DepartmentGlossarySelectionError(
            "invalid_department_glossary",
            "選擇的部門詞彙庫格式不正確",
        ) from None
    if library_id <= 0:
        raise DepartmentGlossarySelectionError(
            "invalid_department_glossary",
            "選擇的部門詞彙庫格式不正確",
        )
    return library_id


def resolve_selected_department_glossary(
    library_id: object,
    *,
    source_lang: str = "zh",
    target_lang: str = "en",
    require_active: bool = True,
    allow_default_fallback: bool = False,
) -> SelectedDepartmentGlossary:
    parsed_library_id = _parse_selected_department_glossary_library_id(library_id)
    if parsed_library_id is None:
        if not allow_default_fallback:
            raise DepartmentGlossarySelectionError(
                "missing_department_glossary",
                "請選擇部門詞彙庫",
            )
        parsed_library_id = get_or_create_default_department_glossary().library_id

    normalized_source_lang = _normalize_glossary_lang(source_lang)
    normalized_target_lang = _normalize_glossary_lang(target_lang)
    with job_store.session_scope() as session:
        record = session.get(job_store.DepartmentGlossaryLibraryRecord, int(parsed_library_id))
        if record is None:
            raise DepartmentGlossarySelectionError(
                "department_glossary_not_found",
                "選擇的部門詞彙庫不存在",
            )
        library = _library_from_record(record)
        if require_active and not library.is_active:
            raise DepartmentGlossarySelectionError(
                "department_glossary_inactive",
                "選擇的部門詞彙庫已停用",
            )
        entry_count = session.scalar(
            select(func.count(job_store.DepartmentGlossaryEntryRecord.id))
            .where(job_store.DepartmentGlossaryEntryRecord.library_id == library.library_id)
            .where(job_store.DepartmentGlossaryEntryRecord.source_lang == normalized_source_lang)
            .where(job_store.DepartmentGlossaryEntryRecord.target_lang == normalized_target_lang)
            .where(job_store.DepartmentGlossaryEntryRecord.status == STATUS_ACTIVE)
        )
    return SelectedDepartmentGlossary(
        library_id=library.library_id,
        code=library.code,
        name=library.name,
        department_code=library.department_code,
        is_active=library.is_active,
        entry_count=int(entry_count or 0),
    )


def upsert_department_glossary_entry(
    *,
    library_id: int,
    source_lang: str,
    target_lang: str,
    source_term: str,
    target_term: str,
    status: str = STATUS_ACTIVE,
    validation_type: str | None = None,
    priority: int = 0,
    notes: str | None = None,
    created_by_work_id: str | None = None,
    updated_by_work_id: str | None = None,
) -> int:
    cleaned_source_term = str(source_term or "").strip()
    cleaned_target_term = str(target_term or "").strip()
    if not int(library_id or 0):
        raise ValueError("Department Glossary library_id is required.")
    if not cleaned_source_term or not cleaned_target_term:
        raise ValueError("Department Glossary source and target terms are required.")
    cleaned_status = _clean_department_glossary_status(status)
    cleaned_validation_type = (
        _clean_department_glossary_validation_type(validation_type)
        if validation_type is not None
        else None
    )
    normalized_source_lang = _normalize_glossary_lang(source_lang)
    normalized_target_lang = _normalize_glossary_lang(target_lang)
    now = job_store.utcnow()
    with job_store.session_scope() as session:
        library = session.get(job_store.DepartmentGlossaryLibraryRecord, int(library_id))
        if library is None:
            raise ValueError(f"Department Glossary library not found: {library_id}")
        record = session.scalar(
            select(job_store.DepartmentGlossaryEntryRecord)
            .where(job_store.DepartmentGlossaryEntryRecord.library_id == int(library_id))
            .where(job_store.DepartmentGlossaryEntryRecord.source_lang == normalized_source_lang)
            .where(job_store.DepartmentGlossaryEntryRecord.target_lang == normalized_target_lang)
            .where(job_store.DepartmentGlossaryEntryRecord.source_term == cleaned_source_term)
            .where(job_store.DepartmentGlossaryEntryRecord.status == cleaned_status)
            .order_by(job_store.DepartmentGlossaryEntryRecord.id.asc())
        )
        if record is None:
            record = job_store.DepartmentGlossaryEntryRecord(
                library_id=int(library_id),
                source_lang=normalized_source_lang,
                target_lang=normalized_target_lang,
                source_term=cleaned_source_term,
                target_term=cleaned_target_term,
                validation_type=cleaned_validation_type or VALIDATION_TYPE_STRICT_REQUIRED,
                status=cleaned_status,
                priority=int(priority or 0),
                notes=str(notes).strip() if notes is not None and str(notes).strip() else None,
                created_by_work_id=str(created_by_work_id or "").strip() or None,
                updated_by_work_id=str(updated_by_work_id or created_by_work_id or "").strip() or None,
                created_at=now,
                updated_at=now,
            )
            session.add(record)
            session.flush()
            _record_glossary_audit_event(
                session,
                action="create",
                target_type="entry",
                target_id=int(record.id),
                before=None,
                after=_entry_audit_payload(record),
                actor_work_id=created_by_work_id or updated_by_work_id,
                created_at=now,
            )
            return int(record.id)
        before = _entry_audit_payload(record)
        record.target_term = cleaned_target_term
        if cleaned_validation_type is not None:
            record.validation_type = cleaned_validation_type
        record.priority = int(priority or 0)
        record.notes = str(notes).strip() if notes is not None and str(notes).strip() else None
        record.updated_by_work_id = (
            str(updated_by_work_id or created_by_work_id or "").strip() or record.updated_by_work_id
        )
        record.updated_at = now
        session.flush()
        after = _entry_audit_payload(record)
        if before != after:
            _record_glossary_audit_event(
                session,
                action="update",
                target_type="entry",
                target_id=int(record.id),
                before=before,
                after=after,
                actor_work_id=updated_by_work_id or created_by_work_id,
                created_at=now,
            )
        return int(record.id)


def update_department_glossary_entry(
    entry_id: int,
    *,
    library_id: int,
    source_term: str,
    target_term: str,
    validation_type: str | None = None,
    updated_by_work_id: str | None = None,
) -> DepartmentGlossaryEntry:
    cleaned_source_term = str(source_term or "").strip()
    cleaned_target_term = str(target_term or "").strip()
    if not cleaned_source_term or not cleaned_target_term:
        raise ValueError("Department Glossary source and target terms are required.")
    cleaned_validation_type = (
        _clean_department_glossary_validation_type(validation_type)
        if validation_type is not None
        else None
    )
    with job_store.session_scope() as session:
        record = session.get(job_store.DepartmentGlossaryEntryRecord, int(entry_id))
        if record is None or int(record.library_id) != int(library_id):
            raise ValueError("Department Glossary entry not found.")
        duplicate = session.scalar(
            select(job_store.DepartmentGlossaryEntryRecord)
            .where(job_store.DepartmentGlossaryEntryRecord.library_id == int(library_id))
            .where(job_store.DepartmentGlossaryEntryRecord.source_lang == record.source_lang)
            .where(job_store.DepartmentGlossaryEntryRecord.target_lang == record.target_lang)
            .where(job_store.DepartmentGlossaryEntryRecord.source_term == cleaned_source_term)
            .where(job_store.DepartmentGlossaryEntryRecord.status == record.status)
            .where(job_store.DepartmentGlossaryEntryRecord.id != int(entry_id))
        )
        if duplicate is not None:
            raise ValueError("Department Glossary source term already exists in this library.")
        before = _entry_audit_payload(record)
        now = job_store.utcnow()
        record.source_term = cleaned_source_term
        record.target_term = cleaned_target_term
        if cleaned_validation_type is not None:
            record.validation_type = cleaned_validation_type
        record.updated_by_work_id = str(updated_by_work_id or "").strip() or record.updated_by_work_id
        record.updated_at = now
        session.flush()
        after = _entry_audit_payload(record)
        if before != after:
            _record_glossary_audit_event(
                session,
                action="update",
                target_type="entry",
                target_id=int(record.id),
                before=before,
                after=after,
                actor_work_id=updated_by_work_id,
                created_at=now,
            )
        return _entry_from_record(record)


def disable_department_glossary_entry(
    entry_id: int,
    *,
    updated_by_work_id: str | None = None,
) -> bool:
    with job_store.session_scope() as session:
        record = session.get(job_store.DepartmentGlossaryEntryRecord, int(entry_id))
        if record is None:
            return False
        before = _entry_audit_payload(record)
        now = job_store.utcnow()
        record.status = STATUS_DISABLED
        record.updated_by_work_id = str(updated_by_work_id or "").strip() or record.updated_by_work_id
        record.updated_at = now
        session.flush()
        after = _entry_audit_payload(record)
        if before != after:
            _record_glossary_audit_event(
                session,
                action="disable",
                target_type="entry",
                target_id=int(record.id),
                before=before,
                after=after,
                actor_work_id=updated_by_work_id,
                created_at=now,
            )
        return True


def list_department_glossary_entries(
    library_id: int,
    *,
    active_only: bool = False,
    source_lang: str | None = None,
    target_lang: str | None = None,
) -> list[DepartmentGlossaryEntry]:
    with job_store.session_scope() as session:
        stmt = select(job_store.DepartmentGlossaryEntryRecord).where(
            job_store.DepartmentGlossaryEntryRecord.library_id == int(library_id)
        )
        if source_lang is not None:
            stmt = stmt.where(
                job_store.DepartmentGlossaryEntryRecord.source_lang == _normalize_glossary_lang(source_lang)
            )
        if target_lang is not None:
            stmt = stmt.where(
                job_store.DepartmentGlossaryEntryRecord.target_lang == _normalize_glossary_lang(target_lang)
            )
        if active_only:
            stmt = stmt.where(job_store.DepartmentGlossaryEntryRecord.status == STATUS_ACTIVE)
        stmt = stmt.order_by(
            job_store.DepartmentGlossaryEntryRecord.priority.desc(),
            job_store.DepartmentGlossaryEntryRecord.id.asc(),
        )
        return [_entry_from_record(record) for record in session.scalars(stmt).all()]


def load_department_glossary_pairs(
    library_id: int | None = None,
    *,
    source_lang: str = "zh",
    target_lang: str = "en",
) -> list[tuple[str, str]]:
    if library_id is None:
        library_id = get_or_create_default_department_glossary().library_id
    entries = list_department_glossary_entries(
        int(library_id),
        active_only=True,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    pairs = [(entry.source_term, entry.target_term) for entry in entries]
    pairs.sort(key=lambda pair: (-len(pair[0]), pair[0]))
    return pairs


def _find_department_glossary_library_by_code(code: str) -> DepartmentGlossaryLibrary | None:
    cleaned_code = str(code or "").strip()
    if not cleaned_code:
        return None
    with job_store.session_scope() as session:
        record = session.scalar(
            select(job_store.DepartmentGlossaryLibraryRecord).where(
                job_store.DepartmentGlossaryLibraryRecord.code == cleaned_code
            )
        )
        return _library_from_record(record) if record is not None else None


def _import_summary_from_details(
    *,
    dry_run: bool,
    library_id: int | None,
    scanned: int,
    details: list[DepartmentGlossaryImportDetail],
) -> DepartmentGlossaryImportSummary:
    counts = {
        IMPORT_ACTION_CREATED: 0,
        IMPORT_ACTION_UPDATED: 0,
        IMPORT_ACTION_UNCHANGED: 0,
        IMPORT_ACTION_WOULD_CREATE: 0,
        IMPORT_ACTION_WOULD_UPDATE: 0,
        IMPORT_ACTION_INVALID: 0,
        IMPORT_ACTION_DUPLICATE: 0,
    }
    for detail in details:
        counts[detail.action] = counts.get(detail.action, 0) + 1
    return DepartmentGlossaryImportSummary(
        dry_run=dry_run,
        library_id=library_id,
        scanned=scanned,
        created=counts[IMPORT_ACTION_CREATED],
        updated=counts[IMPORT_ACTION_UPDATED],
        unchanged=counts[IMPORT_ACTION_UNCHANGED],
        would_create=counts[IMPORT_ACTION_WOULD_CREATE],
        would_update=counts[IMPORT_ACTION_WOULD_UPDATE],
        invalid=counts[IMPORT_ACTION_INVALID],
        duplicates=counts[IMPORT_ACTION_DUPLICATE],
        details=tuple(details),
    )


def _department_glossary_import_existing_entries(
    *,
    library_id: int | None,
    source_lang: str,
    target_lang: str,
) -> dict[str, DepartmentGlossaryEntry]:
    if library_id is None:
        return {}
    entries = list_department_glossary_entries(
        library_id,
        active_only=True,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    return {entry.source_term: entry for entry in entries}


def _department_glossary_import_item_detail(
    item: object,
    *,
    row_number: int,
    accepted_sources: set[str],
) -> DepartmentGlossaryImportDetail | None:
    if not isinstance(item, dict):
        return DepartmentGlossaryImportDetail(
            row_number=row_number,
            action=IMPORT_ACTION_INVALID,
            reason=IMPORT_REASON_ITEM_MUST_BE_OBJECT,
        )
    source_term = str(item.get("cn") or item.get("source_term") or "").strip()
    target_term = str(item.get("en") or item.get("target_term") or "").strip()
    if not source_term:
        return DepartmentGlossaryImportDetail(
            row_number=row_number,
            action=IMPORT_ACTION_INVALID,
            reason=IMPORT_REASON_MISSING_SOURCE_TERM,
            target_term=target_term,
        )
    if not target_term:
        return DepartmentGlossaryImportDetail(
            row_number=row_number,
            action=IMPORT_ACTION_INVALID,
            reason=IMPORT_REASON_MISSING_TARGET_TERM,
            source_term=source_term,
        )
    if source_term in accepted_sources:
        return DepartmentGlossaryImportDetail(
            row_number=row_number,
            action=IMPORT_ACTION_DUPLICATE,
            reason=IMPORT_REASON_DUPLICATE_SOURCE_TERM,
            source_term=source_term,
            target_term=target_term,
        )
    accepted_sources.add(source_term)
    return None


def _department_entry_to_compat_item(entry: DepartmentGlossaryEntry) -> dict[str, str]:
    return {"cn": entry.source_term, "en": entry.target_term}


def _department_entry_to_payload(entry: DepartmentGlossaryEntry) -> dict[str, str | int | None]:
    return {
        "id": entry.entry_id,
        "library_id": entry.library_id,
        "cn": entry.source_term,
        "en": entry.target_term,
        "source_lang": entry.source_lang,
        "target_lang": entry.target_lang,
        "status": entry.status,
        "validation_type": entry.validation_type,
        "priority": entry.priority,
        "notes": entry.notes,
    }


def _department_library_to_payload(library: DepartmentGlossaryLibrary) -> dict[str, str | int | bool]:
    return {
        "id": library.library_id,
        "code": library.code,
        "name": library.name,
        "department_code": library.department_code,
        "is_default": library.is_default,
        "is_active": library.is_active,
    }


def department_glossary_library_to_payload(library: DepartmentGlossaryLibrary) -> dict[str, str | int | bool]:
    return _department_library_to_payload(library)


def department_glossary_entry_to_payload(entry: DepartmentGlossaryEntry) -> dict[str, str | int | None]:
    return _department_entry_to_payload(entry)


def _resolve_department_glossary_export_library(
    *,
    library_id: int | None = None,
    library_code: str | None = None,
) -> SelectedDepartmentGlossary:
    cleaned_code = str(library_code or "").strip()
    has_library_id = library_id is not None
    has_library_code = bool(cleaned_code)
    if has_library_id == has_library_code:
        raise DepartmentGlossarySelectionError(
            "ambiguous_department_glossary",
            "Specify exactly one of library_id or library_code.",
        )
    if has_library_id:
        return resolve_selected_department_glossary(library_id, require_active=True)
    library = _find_department_glossary_library_by_code(cleaned_code)
    if library is None:
        raise DepartmentGlossarySelectionError(
            "department_glossary_not_found",
            f"Department Glossary library_code not found: {cleaned_code}",
        )
    return resolve_selected_department_glossary(library.library_id, require_active=True)


def export_department_glossary_validation_review_csv(
    output_path: Path | str,
    *,
    library_id: int | None = None,
    library_code: str | None = None,
) -> DepartmentGlossaryValidationReviewExportSummary:
    selected = _resolve_department_glossary_export_library(
        library_id=library_id,
        library_code=library_code,
    )
    entries = list_department_glossary_entries(
        selected.library_id,
        active_only=True,
    )
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=VALIDATION_REVIEW_CSV_COLUMNS)
        writer.writeheader()
        for entry in entries:
            writer.writerow(
                {
                    "entry_id": entry.entry_id,
                    "library_id": entry.library_id,
                    "source_lang": entry.source_lang,
                    "target_lang": entry.target_lang,
                    "source_term": entry.source_term,
                    "target_term": entry.target_term,
                    "current_validation_type": entry.validation_type,
                    "suggested_validation_type": "",
                    "classification_reason": "",
                    "confidence": "",
                    "reviewed_validation_type": "",
                    "review_note": "",
                }
            )
    return DepartmentGlossaryValidationReviewExportSummary(
        library_id=selected.library_id,
        library_code=selected.code,
        output_path=path,
        exported=len(entries),
    )


def _review_csv_int_value(row: dict[str, str], column: str) -> int | None:
    try:
        return int(str(row.get(column) or "").strip())
    except (TypeError, ValueError):
        return None


def _review_csv_identity_matches(
    row: dict[str, str],
    *,
    selected_library_id: int,
    entry: DepartmentGlossaryEntry,
) -> bool:
    return (
        _review_csv_int_value(row, "library_id") == selected_library_id
        and entry.library_id == selected_library_id
        and str(row.get("source_lang") or "").strip() == entry.source_lang
        and str(row.get("target_lang") or "").strip() == entry.target_lang
        and str(row.get("source_term") or "").strip() == entry.source_term
        and str(row.get("target_term") or "").strip() == entry.target_term
    )


def _validation_review_apply_summary_from_details(
    *,
    dry_run: bool,
    library_id: int,
    scanned: int,
    details: list[DepartmentGlossaryValidationReviewApplyDetail],
) -> DepartmentGlossaryValidationReviewApplySummary:
    counts = {
        APPLY_REVIEW_ACTION_WOULD_UPDATE: 0,
        APPLY_REVIEW_ACTION_UPDATED: 0,
        APPLY_REVIEW_ACTION_SKIPPED: 0,
        APPLY_REVIEW_ACTION_INVALID: 0,
        APPLY_REVIEW_ACTION_UNCHANGED: 0,
    }
    for detail in details:
        counts[detail.action] = counts.get(detail.action, 0) + 1
    return DepartmentGlossaryValidationReviewApplySummary(
        dry_run=dry_run,
        library_id=library_id,
        scanned=scanned,
        would_update=counts[APPLY_REVIEW_ACTION_WOULD_UPDATE],
        updated=counts[APPLY_REVIEW_ACTION_UPDATED],
        skipped=counts[APPLY_REVIEW_ACTION_SKIPPED],
        invalid=counts[APPLY_REVIEW_ACTION_INVALID],
        unchanged=counts[APPLY_REVIEW_ACTION_UNCHANGED],
        details=tuple(details),
    )


def apply_department_glossary_validation_review_csv(
    csv_path: Path | str,
    *,
    library_id: int | None,
    apply: bool = False,
    updated_by_work_id: str | None = None,
) -> DepartmentGlossaryValidationReviewApplySummary:
    selected = resolve_selected_department_glossary(library_id, require_active=True)
    path = Path(csv_path)
    entries_by_id = {
        entry.entry_id: entry
        for entry in list_department_glossary_entries(selected.library_id, active_only=True)
    }
    details: list[DepartmentGlossaryValidationReviewApplyDetail] = []
    with path.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing_columns = [
            column for column in VALIDATION_REVIEW_CSV_COLUMNS if column not in (reader.fieldnames or [])
        ]
        if missing_columns:
            raise ValueError(f"Validation review CSV missing columns: {', '.join(missing_columns)}")
        for row_number, row in enumerate(reader, start=2):
            reviewed_validation_type = str(row.get("reviewed_validation_type") or "").strip()
            if not reviewed_validation_type:
                details.append(
                    DepartmentGlossaryValidationReviewApplyDetail(
                        row_number=row_number,
                        action=APPLY_REVIEW_ACTION_SKIPPED,
                        reason=APPLY_REVIEW_REASON_REVIEWED_VALUE_BLANK,
                        entry_id=_review_csv_int_value(row, "entry_id"),
                    )
                )
                continue
            entry_id = _review_csv_int_value(row, "entry_id")
            if entry_id is None:
                details.append(
                    DepartmentGlossaryValidationReviewApplyDetail(
                        row_number=row_number,
                        action=APPLY_REVIEW_ACTION_INVALID,
                        reason=APPLY_REVIEW_REASON_ENTRY_ID_INVALID,
                        reviewed_validation_type=reviewed_validation_type,
                    )
                )
                continue
            row_library_id = _review_csv_int_value(row, "library_id")
            if row_library_id is None:
                details.append(
                    DepartmentGlossaryValidationReviewApplyDetail(
                        row_number=row_number,
                        action=APPLY_REVIEW_ACTION_INVALID,
                        reason=APPLY_REVIEW_REASON_LIBRARY_ID_INVALID,
                        entry_id=entry_id,
                        reviewed_validation_type=reviewed_validation_type,
                    )
                )
                continue
            try:
                cleaned_validation_type = _clean_department_glossary_validation_type(reviewed_validation_type)
            except ValueError:
                details.append(
                    DepartmentGlossaryValidationReviewApplyDetail(
                        row_number=row_number,
                        action=APPLY_REVIEW_ACTION_INVALID,
                        reason=APPLY_REVIEW_REASON_INVALID_VALIDATION_TYPE,
                        entry_id=entry_id,
                        reviewed_validation_type=reviewed_validation_type,
                    )
                )
                continue
            entry = entries_by_id.get(entry_id)
            if entry is None:
                details.append(
                    DepartmentGlossaryValidationReviewApplyDetail(
                        row_number=row_number,
                        action=APPLY_REVIEW_ACTION_INVALID,
                        reason=APPLY_REVIEW_REASON_ENTRY_NOT_FOUND,
                        entry_id=entry_id,
                        reviewed_validation_type=cleaned_validation_type,
                    )
                )
                continue
            if not _review_csv_identity_matches(
                row,
                selected_library_id=selected.library_id,
                entry=entry,
            ):
                details.append(
                    DepartmentGlossaryValidationReviewApplyDetail(
                        row_number=row_number,
                        action=APPLY_REVIEW_ACTION_INVALID,
                        reason=APPLY_REVIEW_REASON_ENTRY_IDENTITY_MISMATCH,
                        entry_id=entry_id,
                        reviewed_validation_type=cleaned_validation_type,
                    )
                )
                continue
            if entry.validation_type == cleaned_validation_type:
                details.append(
                    DepartmentGlossaryValidationReviewApplyDetail(
                        row_number=row_number,
                        action=APPLY_REVIEW_ACTION_UNCHANGED,
                        reason=APPLY_REVIEW_REASON_VALIDATION_TYPE_UNCHANGED,
                        entry_id=entry_id,
                        reviewed_validation_type=cleaned_validation_type,
                    )
                )
                continue
            if not apply:
                details.append(
                    DepartmentGlossaryValidationReviewApplyDetail(
                        row_number=row_number,
                        action=APPLY_REVIEW_ACTION_WOULD_UPDATE,
                        reason=APPLY_REVIEW_REASON_VALIDATION_TYPE_UPDATED,
                        entry_id=entry_id,
                        reviewed_validation_type=cleaned_validation_type,
                    )
                )
                continue
            update_department_glossary_entry(
                entry_id,
                library_id=selected.library_id,
                source_term=entry.source_term,
                target_term=entry.target_term,
                validation_type=cleaned_validation_type,
                updated_by_work_id=updated_by_work_id,
            )
            entries_by_id[entry_id] = DepartmentGlossaryEntry(
                entry_id=entry.entry_id,
                library_id=entry.library_id,
                source_lang=entry.source_lang,
                target_lang=entry.target_lang,
                source_term=entry.source_term,
                target_term=entry.target_term,
                status=entry.status,
                validation_type=cleaned_validation_type,
                priority=entry.priority,
                notes=entry.notes,
                created_by_work_id=entry.created_by_work_id,
                updated_by_work_id=updated_by_work_id or entry.updated_by_work_id,
            )
            details.append(
                DepartmentGlossaryValidationReviewApplyDetail(
                    row_number=row_number,
                    action=APPLY_REVIEW_ACTION_UPDATED,
                    reason=APPLY_REVIEW_REASON_VALIDATION_TYPE_UPDATED,
                    entry_id=entry_id,
                    reviewed_validation_type=cleaned_validation_type,
                )
            )
    return _validation_review_apply_summary_from_details(
        dry_run=not apply,
        library_id=selected.library_id,
        scanned=len(details),
        details=details,
    )


def load_department_glossary_items(
    library_id: int | None = None,
    *,
    active_only: bool = True,
) -> list[dict[str, str]]:
    if library_id is None:
        library_id = get_or_create_default_department_glossary().library_id
    else:
        library_id = resolve_selected_department_glossary(
            library_id,
            require_active=False,
        ).library_id
    entries = list_department_glossary_entries(int(library_id), active_only=active_only)
    items = [_department_entry_to_compat_item(entry) for entry in entries]
    items.sort(key=lambda item: item["cn"])
    return items


def load_default_department_glossary_items() -> list[dict[str, str]]:
    return load_department_glossary_items()


def sync_department_glossary_items(
    library_id: int,
    items: list[dict[str, str]],
    *,
    replace: bool = True,
    updated_by_work_id: str | None = None,
) -> list[dict[str, str]]:
    selected_library = resolve_selected_department_glossary(
        library_id,
        require_active=False,
    )
    cleaned_by_cn: dict[str, str] = {}
    for item in items:
        if not isinstance(item, dict):
            continue
        cn = str(item.get("cn") or "").strip()
        en = str(item.get("en") or "").strip()
        if cn and en:
            cleaned_by_cn[cn] = en
    for cn, en in cleaned_by_cn.items():
        upsert_department_glossary_entry(
            library_id=selected_library.library_id,
            source_lang="zh",
            target_lang="en",
            source_term=cn,
            target_term=en,
            updated_by_work_id=updated_by_work_id,
        )
    if replace:
        for entry in list_department_glossary_entries(selected_library.library_id, active_only=True):
            if entry.source_term not in cleaned_by_cn:
                disable_department_glossary_entry(
                    entry.entry_id,
                    updated_by_work_id=updated_by_work_id,
                )
    return load_department_glossary_items(selected_library.library_id)


def sync_default_department_glossary_items(
    items: list[dict[str, str]],
    *,
    replace: bool = True,
    updated_by_work_id: str | None = None,
) -> list[dict[str, str]]:
    library = get_or_create_default_department_glossary(actor_work_id=updated_by_work_id)
    return sync_department_glossary_items(
        library.library_id,
        items,
        replace=replace,
        updated_by_work_id=updated_by_work_id,
    )


def apply_department_glossary_import(
    library_id: int,
    items: list[dict[str, str]],
) -> list[dict[str, str]]:
    return sync_department_glossary_items(library_id, items, replace=False)


def apply_default_department_glossary_import(items: list[dict[str, str]]) -> list[dict[str, str]]:
    library = get_or_create_default_department_glossary()
    return apply_department_glossary_import(library.library_id, items)


def import_department_glossary_json(
    json_path: Path | str,
    *,
    apply: bool = False,
    source_lang: str = "zh",
    target_lang: str = "en",
    created_by_work_id: str | None = None,
    updated_by_work_id: str | None = None,
) -> DepartmentGlossaryImportSummary:
    path = Path(json_path)
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, list):
        return DepartmentGlossaryImportSummary(
            dry_run=not apply,
            library_id=None,
            scanned=0,
            invalid=1,
            details=(
                DepartmentGlossaryImportDetail(
                    row_number=1,
                    action=IMPORT_ACTION_INVALID,
                    reason=IMPORT_REASON_JSON_MUST_BE_LIST,
                ),
            ),
        )

    normalized_source_lang = _normalize_glossary_lang(source_lang)
    normalized_target_lang = _normalize_glossary_lang(target_lang)
    library = (
        get_or_create_default_department_glossary(
            actor_work_id=updated_by_work_id or created_by_work_id,
        )
        if apply
        else _find_department_glossary_library_by_code(DEFAULT_DEPARTMENT_GLOSSARY_CODE)
    )
    existing_by_source = _department_glossary_import_existing_entries(
        library_id=library.library_id if library is not None else None,
        source_lang=normalized_source_lang,
        target_lang=normalized_target_lang,
    )

    details: list[DepartmentGlossaryImportDetail] = []
    accepted_sources: set[str] = set()
    for index, item in enumerate(payload, start=2):
        item_detail = _department_glossary_import_item_detail(
            item,
            row_number=index,
            accepted_sources=accepted_sources,
        )
        if item_detail is not None:
            details.append(item_detail)
            continue
        assert isinstance(item, dict)
        source_term = str(item.get("cn") or item.get("source_term") or "").strip()
        target_term = str(item.get("en") or item.get("target_term") or "").strip()

        existing = existing_by_source.get(source_term)
        if existing is None:
            if not apply:
                details.append(
                    DepartmentGlossaryImportDetail(
                        row_number=index,
                        action=IMPORT_ACTION_WOULD_CREATE,
                        reason=IMPORT_REASON_NEW_ENTRY,
                        source_term=source_term,
                        target_term=target_term,
                    )
                )
                continue
            entry_id = upsert_department_glossary_entry(
                library_id=library.library_id,
                source_lang=normalized_source_lang,
                target_lang=normalized_target_lang,
                source_term=source_term,
                target_term=target_term,
                created_by_work_id=created_by_work_id,
                updated_by_work_id=updated_by_work_id,
            )
            details.append(
                DepartmentGlossaryImportDetail(
                    row_number=index,
                    action=IMPORT_ACTION_CREATED,
                    reason=IMPORT_REASON_NEW_ENTRY,
                    source_term=source_term,
                    target_term=target_term,
                    entry_id=entry_id,
                )
            )
            existing_by_source[source_term] = DepartmentGlossaryEntry(
                entry_id=entry_id,
                library_id=library.library_id,
                source_lang=normalized_source_lang,
                target_lang=normalized_target_lang,
                source_term=source_term,
                target_term=target_term,
                status=STATUS_ACTIVE,
                validation_type=VALIDATION_TYPE_STRICT_REQUIRED,
            )
            continue

        if existing.target_term == target_term:
            details.append(
                DepartmentGlossaryImportDetail(
                    row_number=index,
                    action=IMPORT_ACTION_UNCHANGED,
                    reason=IMPORT_REASON_EXISTING_TERM_UNCHANGED,
                    source_term=source_term,
                    target_term=target_term,
                    entry_id=existing.entry_id,
                )
            )
            continue
        if not apply:
            details.append(
                DepartmentGlossaryImportDetail(
                    row_number=index,
                    action=IMPORT_ACTION_WOULD_UPDATE,
                    reason=IMPORT_REASON_EXISTING_TERM_UPDATED,
                    source_term=source_term,
                    target_term=target_term,
                    entry_id=existing.entry_id,
                )
            )
            continue
        entry_id = upsert_department_glossary_entry(
            library_id=library.library_id,
            source_lang=normalized_source_lang,
            target_lang=normalized_target_lang,
            source_term=source_term,
            target_term=target_term,
            updated_by_work_id=updated_by_work_id or created_by_work_id,
        )
        details.append(
            DepartmentGlossaryImportDetail(
                row_number=index,
                action=IMPORT_ACTION_UPDATED,
                reason=IMPORT_REASON_EXISTING_TERM_UPDATED,
                source_term=source_term,
                target_term=target_term,
                entry_id=entry_id,
            )
        )
        existing_by_source[source_term] = DepartmentGlossaryEntry(
            entry_id=entry_id,
            library_id=library.library_id,
            source_lang=normalized_source_lang,
            target_lang=normalized_target_lang,
            source_term=source_term,
            target_term=target_term,
            status=STATUS_ACTIVE,
            validation_type=existing.validation_type,
        )

    return _import_summary_from_details(
        dry_run=not apply,
        library_id=library.library_id if library is not None else None,
        scanned=len(payload),
        details=details,
    )


def global_glossary_path() -> Path:
    return Path(state.GLOBAL_GLOSSARY_PATH)


def system_glossary_path() -> Path:
    return Path(state.SYSTEM_GLOSSARY_PATH)


def _resolve_glossary_path(raw_path: str) -> Path:
    path = Path(raw_path)
    if not path.is_absolute():
        path = state.BASE_DIR / path
    return path


def _path_mtime(path: Path) -> float | None:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return None


def invalidate_glossary_cache() -> None:
    global _GLOBAL_GLOSSARY_CACHE, _COMBINED_GLOSSARY_CACHE, _SYSTEM_GLOSSARY_CACHE
    with _GLOSSARY_CACHE_LOCK:
        _GLOBAL_GLOSSARY_CACHE = None
        _COMBINED_GLOSSARY_CACHE = None
        _SYSTEM_GLOSSARY_CACHE = None


def _clean_glossary_items(data: object) -> list[dict[str, str]]:
    if not isinstance(data, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cn = str(item.get("cn") or "").strip()
        en = str(item.get("en") or "").strip()
        if not cn or not en:
            continue
        cleaned.append({"cn": cn, "en": en})
    return cleaned


def load_global_glossary() -> list[dict[str, str]]:
    global _GLOBAL_GLOSSARY_CACHE
    path = global_glossary_path()
    current_mtime = _path_mtime(path)
    with _GLOSSARY_CACHE_LOCK:
        cached = _GLOBAL_GLOSSARY_CACHE
        if cached and cached[0] == path and cached[1] == current_mtime:
            return list(cached[2])

    if current_mtime is None:
        cleaned: list[dict[str, str]] = []
    else:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            cleaned = []
        else:
            cleaned = _clean_glossary_items(data)

    with _GLOSSARY_CACHE_LOCK:
        _GLOBAL_GLOSSARY_CACHE = (path, current_mtime, cleaned)
    return list(cleaned)


def write_global_glossary(items: list[dict[str, str]]) -> None:
    payload: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        cn = str(item.get("cn") or "").strip()
        en = str(item.get("en") or "").strip()
        if not cn or not en:
            continue
        key = (cn, en)
        if key in seen:
            continue
        payload.append({"cn": cn, "en": en})
        seen.add(key)
    path = global_glossary_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    invalidate_glossary_cache()


def write_system_glossary(items: list[dict[str, str]]) -> None:
    payload: list[dict[str, str]] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        cn = str(item.get("cn") or "").strip()
        en = str(item.get("en") or "").strip()
        if not cn or not en or cn in seen:
            continue
        payload.append({"cn": cn, "en": en})
        seen.add(cn)
    path = system_glossary_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    invalidate_glossary_cache()


def _system_glossary_paths() -> tuple[Path, ...]:
    if not state.SYSTEM_GLOSSARY_PATH:
        return tuple()
    return (_resolve_glossary_path(state.SYSTEM_GLOSSARY_PATH),)


def load_system_glossary() -> list[dict[str, str]]:
    global _SYSTEM_GLOSSARY_CACHE
    paths = _system_glossary_paths()
    cache_key = tuple((str(path), _path_mtime(path)) for path in paths)
    with _GLOSSARY_CACHE_LOCK:
        cached = _SYSTEM_GLOSSARY_CACHE
        if cached and cached[0] == cache_key:
            return [dict(item) for item in cached[1]]

    entries_by_cn: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in _clean_glossary_items(data):
            entries_by_cn[item["cn"]] = item["en"]

    cleaned = [
        {"cn": cn, "en": en}
        for cn, en in sorted(entries_by_cn.items(), key=lambda pair: pair[0])
    ]
    with _GLOSSARY_CACHE_LOCK:
        _SYSTEM_GLOSSARY_CACHE = (cache_key, cleaned)
    return [dict(item) for item in cleaned]


def _load_json_glossary_entries() -> list[tuple[str, str]]:
    global _COMBINED_GLOSSARY_CACHE
    paths = _system_glossary_paths()
    if state.GLOBAL_GLOSSARY_PATH:
        paths = paths + (_resolve_glossary_path(state.GLOBAL_GLOSSARY_PATH),)
    cache_key = tuple((str(path), _path_mtime(path)) for path in paths)
    with _GLOSSARY_CACHE_LOCK:
        cached = _COMBINED_GLOSSARY_CACHE
        if cached and cached[0] == cache_key:
            return list(cached[1])

    entries_by_cn: dict[str, str] = {}
    for path in paths:
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for item in _clean_glossary_items(data):
            entries_by_cn[item["cn"]] = item["en"]
    entries = list(entries_by_cn.items())
    entries.sort(key=lambda pair: len(pair[0]), reverse=True)
    with _GLOSSARY_CACHE_LOCK:
        _COMBINED_GLOSSARY_CACHE = (cache_key, entries)
    return list(entries)


def _translation_glossary_source() -> str:
    configured = str(getattr(state, "TRANSLATION_GLOSSARY_SOURCE", "sql") or "sql").strip().lower()
    if configured not in {"sql", "json"}:
        raise ValueError("TRANSLATION_GLOSSARY_SOURCE must be either 'sql' or 'json'.")
    return configured


def load_glossary_entries(
    library_id: int | None = None,
    *,
    source_lang: str = "zh",
    target_lang: str = "en",
) -> list[tuple[str, str]]:
    if _translation_glossary_source() == "json":
        return _load_json_glossary_entries()
    return load_department_glossary_pairs(
        library_id,
        source_lang=source_lang,
        target_lang=target_lang,
    )


def load_combined_glossary(
    library_id: int | None = None,
    *,
    source_lang: str = "zh",
    target_lang: str = "en",
) -> list[tuple[str, str]]:
    return load_glossary_entries(
        library_id,
        source_lang=source_lang,
        target_lang=target_lang,
    )


def current_department_glossary_context(
    library_id: int | None = None,
    *,
    source_lang: str = "zh",
    target_lang: str = "en",
    glossary_entries: list[tuple[str, str]] | None = None,
) -> dict[str, object]:
    source = _translation_glossary_source()
    entries = list(glossary_entries) if glossary_entries is not None else load_glossary_entries(
        library_id,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    entry_snapshot = [
        {"source_term": source_term, "target_term": target_term}
        for source_term, target_term in entries
    ]
    context: dict[str, object] = {
        "source": source,
        "library_id": None,
        "library_code": None,
        "library_name": None,
        "department_code": None,
        "entry_count": len(entries),
        "entries": entry_snapshot,
    }
    if source == "json":
        return context

    try:
        library = (
            get_or_create_default_department_glossary()
            if library_id is None
            else _get_department_glossary_library(int(library_id))
        )
    except RuntimeError as exc:
        logger.debug("Department Glossary context metadata unavailable: %s", exc)
        return context
    context.update(
        {
            "library_id": library.library_id,
            "library_code": library.code,
            "library_name": library.name,
            "department_code": library.department_code,
        }
    )
    return context


def department_glossary_lookup_source_lang(source_lang: str) -> str:
    return "zh" if normalize_lang_code(source_lang) == "auto" else source_lang


def selected_department_glossary_library_id_from_mappings(
    *mappings: Mapping[str, object] | None,
) -> object | None:
    for mapping in mappings:
        if not mapping:
            continue
        value = mapping.get("department_glossary_library_id")
        if value is not None and str(value).strip():
            return value
    return None


def load_execution_department_glossary(
    library_id: object,
    *,
    source_lang: str = "zh",
    target_lang: str = "en",
    allow_default_fallback: bool = True,
) -> tuple[list[tuple[str, str]], dict[str, object]]:
    lookup_source_lang = department_glossary_lookup_source_lang(source_lang)
    if library_id is None or not str(library_id).strip():
        entries = load_combined_glossary()
        context = current_department_glossary_context(
            glossary_entries=entries,
            source_lang=lookup_source_lang,
            target_lang=target_lang,
        )
        return entries, context
    try:
        selected = resolve_selected_department_glossary(
            library_id,
            source_lang=lookup_source_lang,
            target_lang=target_lang,
            require_active=True,
            allow_default_fallback=allow_default_fallback,
        )
    except DepartmentGlossarySelectionError as exc:
        raise RuntimeError(exc.user_message) from exc
    entries = load_combined_glossary(
        selected.library_id,
        source_lang=lookup_source_lang,
        target_lang=target_lang,
    )
    context = current_department_glossary_context(
        selected.library_id,
        glossary_entries=entries,
        source_lang=lookup_source_lang,
        target_lang=target_lang,
    )
    return entries, context


def department_glossary_context_artifact_enabled() -> bool:
    return bool(getattr(state, "GLOSSARY_CONTEXT_ARTIFACT_ENABLED", False))


def write_department_glossary_context_artifact(
    job_dir: Path,
    context: dict[str, object],
    *,
    filename: str = "glossary_context.json",
) -> Path | None:
    if not department_glossary_context_artifact_enabled():
        return None
    path = Path(job_dir) / filename
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(context, ensure_ascii=False, indent=2), encoding="utf-8")
    job_id = Path(job_dir).name
    if re.fullmatch(r"[a-fA-F0-9]{32}", job_id):
        try:
            job_store.register_artifact(job_id, "glossary_context", filename)
        except RuntimeError as exc:
            logger.debug("Unable to register glossary context artifact: %s", exc)
    return path


def _get_department_glossary_library(library_id: int) -> DepartmentGlossaryLibrary:
    with job_store.session_scope() as session:
        record = session.get(job_store.DepartmentGlossaryLibraryRecord, int(library_id))
        if record is None:
            raise ValueError(f"Department Glossary library not found: {library_id}")
        return _library_from_record(record)


DEPARTMENT_GLOSSARY_CONTEXT_CONFIG_KEYS = (
    "department_glossary_source",
    "department_glossary_library_id",
    "department_glossary_library_code",
    "department_glossary_library_name",
    "department_glossary_department_code",
    "department_glossary_entry_count",
)


def add_department_glossary_context_to_config(
    config: dict[str, object],
    context: dict[str, object],
) -> dict[str, object]:
    config.update(
        {
            "department_glossary_source": context.get("source"),
            "department_glossary_library_id": context.get("library_id"),
            "department_glossary_library_code": context.get("library_code"),
            "department_glossary_library_name": context.get("library_name"),
            "department_glossary_department_code": context.get("department_code"),
            "department_glossary_entry_count": context.get("entry_count"),
        }
    )
    return config


def department_glossary_context_config_from_mapping(mapping: Mapping[str, object]) -> dict[str, object]:
    return {
        key: mapping[key]
        for key in DEPARTMENT_GLOSSARY_CONTEXT_CONFIG_KEYS
        if key in mapping and mapping[key] is not None
    }


def department_glossary_context_config_from_artifact(
    job_dir: Path,
    *,
    filename: str = "glossary_context.json",
) -> dict[str, object]:
    path = Path(job_dir) / filename
    if not path.exists():
        return {}
    try:
        context = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        logger.debug("Unable to read Department Glossary context artifact: %s", exc)
        return {}
    if not isinstance(context, dict):
        return {}
    return add_department_glossary_context_to_config({}, context)


def _uses_reverse_glossary_direction(source_lang: str, target_lang: str) -> bool:
    normalized_source = normalize_lang_code(source_lang)
    normalized_target = normalize_lang_code(target_lang)
    return normalized_target in {"zh", "zh-cn"} and normalized_source in {"auto", "en"}


def glossary_pairs_for_translation(
    entries: list[tuple[str, str]] | None = None,
    *,
    source_lang: str = "auto",
    target_lang: str = "en",
) -> list[tuple[str, str]]:
    if entries is None:
        entries = load_glossary_entries()
    if not entries:
        return []
    reverse = _uses_reverse_glossary_direction(source_lang, target_lang)
    pairs: list[tuple[str, str]] = []
    for cn, en in entries:
        src = en if reverse else cn
        dst = cn if reverse else en
        src = str(src or "").strip()
        dst = str(dst or "").strip()
        if src and dst:
            pairs.append((src, dst))
    pairs.sort(key=lambda pair: len(pair[0]), reverse=True)
    return pairs


_CJK_SOURCE_TERM_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u309F\u30A0-\u30FF]")


def _supports_inter_cjk_word_break_match(source_term: str) -> bool:
    return bool(source_term) and _CJK_SOURCE_TERM_RE.search(source_term) is not None


def source_term_match_length(text: str, source_term: str, start: int = 0) -> int | None:
    source = str(source_term or "")
    if not source:
        return None
    if str(text or "").startswith(source, start):
        return len(source)
    if not _supports_inter_cjk_word_break_match(source):
        return None

    value = str(text or "")
    cursor = start
    for index, char in enumerate(source):
        if cursor >= len(value) or value[cursor] != char:
            return None
        cursor += 1
        if index < len(source) - 1:
            while cursor < len(value) and value[cursor].isspace():
                cursor += 1
    return cursor - start


def build_glossary_management_payload(
    *,
    library_id: object | None = None,
    include_inactive_entries: bool = False,
) -> dict[str, object]:
    if library_id is None:
        selected_library = get_or_create_default_department_glossary()
    else:
        selected = resolve_selected_department_glossary(
            library_id,
            require_active=False,
        )
        selected_library = DepartmentGlossaryLibrary(
            library_id=selected.library_id,
            code=selected.code,
            name=selected.name,
            department_code=selected.department_code,
            is_default=False,
            is_active=selected.is_active,
        )
        matching_libraries = [
            library
            for library in list_department_glossary_libraries(active_only=False)
            if library.library_id == selected.library_id
        ]
        if matching_libraries:
            selected_library = matching_libraries[0]
    libraries = list_department_glossary_libraries(active_only=False)
    entries = list_department_glossary_entries(
        selected_library.library_id,
        active_only=not include_inactive_entries,
    )
    entries.sort(key=lambda entry: entry.source_term)
    active_entries = [entry for entry in entries if entry.status == STATUS_ACTIVE]
    system_items = [_department_entry_to_compat_item(entry) for entry in active_entries]
    entry_payload = [_department_entry_to_payload(entry) for entry in entries]
    effective_items: list[dict[str, str | bool | None]] = [
        {
            "cn": entry.source_term,
            "en": entry.target_term,
            "source": "system",
            "overridden": False,
            "system_en": entry.target_term,
            "user_en": None,
        }
        for entry in entries
    ]

    return {
        "system_glossary": system_items,
        "user_glossary": [],
        "effective_glossary": effective_items,
        "libraries": [_department_library_to_payload(library) for library in libraries],
        "selected_library": _department_library_to_payload(selected_library),
        "include_inactive_entries": include_inactive_entries,
        "entries": entry_payload,
    }


def _excel_column_index(cell_ref: str) -> int:
    letters = "".join(ch for ch in str(cell_ref or "") if ch.isalpha()).upper()
    index = 0
    for char in letters:
        index = index * 26 + (ord(char) - 64)
    return max(0, index - 1)


def _load_shared_strings(zf: zipfile.ZipFile) -> list[str]:
    try:
        root = ET.fromstring(zf.read("xl/sharedStrings.xml"))
    except KeyError:
        return []
    values: list[str] = []
    for node in root.findall("x:si", _SPREADSHEET_NS):
        parts = [
            text_node.text or ""
            for text_node in node.findall(".//x:t", _SPREADSHEET_NS)
        ]
        values.append("".join(parts))
    return values


def _resolve_first_sheet_path(zf: zipfile.ZipFile) -> str:
    workbook = ET.fromstring(zf.read("xl/workbook.xml"))
    first_sheet = workbook.find("x:sheets/x:sheet", _SPREADSHEET_NS)
    if first_sheet is None:
        raise ValueError("Excel 檔案沒有工作表。")
    rel_id = first_sheet.attrib.get("{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id")
    if not rel_id:
        raise ValueError("找不到工作表關聯。")
    rels = ET.fromstring(zf.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.findall("{http://schemas.openxmlformats.org/package/2006/relationships}Relationship"):
        if rel.attrib.get("Id") != rel_id:
            continue
        target = rel.attrib.get("Target") or ""
        normalized = target.lstrip("/")
        if normalized.startswith("xl/"):
            return normalized
        return f"xl/{normalized}"
    raise ValueError("找不到第一張工作表。")


def _read_sheet_rows(zf: zipfile.ZipFile, sheet_path: str, shared_strings: list[str]) -> list[list[str]]:
    root = ET.fromstring(zf.read(sheet_path))
    rows: list[list[str]] = []
    for row in root.findall("x:sheetData/x:row", _SPREADSHEET_NS):
        row_values: list[str] = []
        for cell in row.findall("x:c", _SPREADSHEET_NS):
            col_index = _excel_column_index(cell.attrib.get("r", ""))
            while len(row_values) <= col_index:
                row_values.append("")
            cell_type = cell.attrib.get("t")
            value_node = cell.find("x:v", _SPREADSHEET_NS)
            inline_node = cell.find("x:is/x:t", _SPREADSHEET_NS)
            if inline_node is not None:
                value = inline_node.text or ""
            elif value_node is None or value_node.text is None:
                value = ""
            elif cell_type == "s":
                try:
                    value = shared_strings[int(value_node.text)]
                except Exception:
                    value = ""
            else:
                value = value_node.text
            row_values[col_index] = str(value or "")
        rows.append(row_values)
    return rows


def parse_system_glossary_excel(file_bytes: bytes) -> dict[str, object]:
    try:
        workbook = zipfile.ZipFile(BytesIO(file_bytes))
    except zipfile.BadZipFile as exc:
        raise ValueError("無法解析 Excel 檔案，請上傳 .xlsx 格式。") from exc

    with workbook as zf:
        shared_strings = _load_shared_strings(zf)
        sheet_path = _resolve_first_sheet_path(zf)
        rows = _read_sheet_rows(zf, sheet_path, shared_strings)

    if not rows:
        raise ValueError("Excel 檔案沒有資料。")

    header = [str(value or "").strip().lower() for value in rows[0]]
    if "cn" not in header or "en" not in header:
        raise ValueError("Excel 第一列必須包含 cn 與 en 欄位。")
    cn_index = header.index("cn")
    en_index = header.index("en")

    entries: list[dict[str, str]] = []
    duplicates: list[dict[str, str | int]] = []
    invalid_rows: list[dict[str, str | int]] = []
    seen: dict[str, str] = {}

    for row_number, row in enumerate(rows[1:], start=2):
        cn = str(row[cn_index] if cn_index < len(row) else "").strip()
        en = str(row[en_index] if en_index < len(row) else "").strip()
        if not cn and not en:
            continue
        if not cn or not en:
            invalid_rows.append({"row": row_number, "cn": cn, "en": en, "reason": "cn 欄位缺少中文詞彙或 en 欄位缺少英文詞彙"})
            continue
        if cn in seen:
            duplicates.append({"row": row_number, "cn": cn, "previous_en": seen[cn], "en": en})
        seen[cn] = en

    for cn, en in seen.items():
        entries.append({"cn": cn, "en": en})
    entries.sort(key=lambda item: item["cn"])
    return {
        "items": entries,
        "duplicates": duplicates,
        "invalid_rows": invalid_rows,
        "total_rows": max(0, len(rows) - 1),
    }


def parse_system_glossary_json(file_bytes: bytes) -> dict[str, object]:
    try:
        payload = json.loads(file_bytes.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("無法解析 JSON 檔案，請上傳有效的 JSON 詞彙陣列。") from exc
    if not isinstance(payload, list):
        raise ValueError("JSON 詞彙表必須是陣列。")

    entries: list[dict[str, str]] = []
    duplicates: list[dict[str, str | int]] = []
    invalid_rows: list[dict[str, str | int]] = []
    seen: dict[str, str] = {}
    accepted_sources: set[str] = set()
    for row_number, item in enumerate(payload, start=1):
        detail = _department_glossary_import_item_detail(
            item,
            row_number=row_number,
            accepted_sources=accepted_sources,
        )
        if detail is not None:
            if detail.action == IMPORT_ACTION_DUPLICATE:
                duplicates.append(
                    {
                        "row": row_number,
                        "cn": detail.source_term or "",
                        "previous_en": seen.get(detail.source_term or "", ""),
                        "en": detail.target_term or "",
                    }
                )
            else:
                invalid_rows.append(
                    {
                        "row": row_number,
                        "cn": detail.source_term or "",
                        "en": detail.target_term or "",
                        "reason": detail.reason,
                    }
                )
            continue
        assert isinstance(item, dict)
        cn = str(item.get("cn") or item.get("source_term") or "").strip()
        en = str(item.get("en") or item.get("target_term") or "").strip()
        seen[cn] = en

    for cn, en in seen.items():
        entries.append({"cn": cn, "en": en})
    entries.sort(key=lambda item: item["cn"])
    return {
        "items": entries,
        "duplicates": duplicates,
        "invalid_rows": invalid_rows,
        "total_rows": len(payload),
    }


def build_system_glossary_import_preview(
    items: list[dict[str, str]],
    *,
    library_id: int | None = None,
) -> dict[str, object]:
    current_items = load_department_glossary_items(library_id)
    current_by_cn = {item["cn"]: item["en"] for item in current_items}
    additions = 0
    updates = 0
    unchanged = 0
    preview_rows: list[dict[str, str | None]] = []

    for item in items:
        cn = str(item.get("cn") or "").strip()
        en = str(item.get("en") or "").strip()
        if not cn or not en:
            continue
        current_en = current_by_cn.get(cn)
        if current_en is None:
            status = "add"
            additions += 1
        elif current_en != en:
            status = "update"
            updates += 1
        else:
            status = "unchanged"
            unchanged += 1
        preview_rows.append(
            {
                "cn": cn,
                "current_en": current_en,
                "next_en": en,
                "status": status,
            }
        )

    preview_rows.sort(key=lambda item: (str(item["status"]), str(item["cn"])))
    return {
        "items": items,
        "preview_rows": preview_rows,
        "summary": {
            "incoming": len(items),
            "additions": additions,
            "updates": updates,
            "unchanged": unchanged,
        },
    }


def apply_system_glossary_import(
    items: list[dict[str, str]],
    *,
    library_id: int | None = None,
) -> list[dict[str, str]]:
    if library_id is None:
        return apply_default_department_glossary_import(items)
    return apply_department_glossary_import(library_id, items)


def _escape_xml_text(value: str) -> str:
    return (
        str(value or "")
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _build_xlsx_bytes(rows: list[list[str]], sheet_name: str = "Sheet1") -> bytes:
    shared_strings: list[str] = []
    shared_index: dict[str, int] = {}
    sheet_rows: list[str] = []
    for row_idx, row in enumerate(rows, start=1):
        cells: list[str] = []
        for col_idx, value in enumerate(row, start=1):
            text = str(value or "")
            if text not in shared_index:
                shared_index[text] = len(shared_strings)
                shared_strings.append(text)
            col_name = ""
            current = col_idx
            while current > 0:
                current, remainder = divmod(current - 1, 26)
                col_name = chr(65 + remainder) + col_name
            cell_ref = f"{col_name}{row_idx}"
            cells.append(f'<c r="{cell_ref}" t="s"><v>{shared_index[text]}</v></c>')
        sheet_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')

    shared_xml = "".join(f"<si><t>{_escape_xml_text(text)}</t></si>" for text in shared_strings)
    sheet_xml = "".join(sheet_rows)
    sheet_name_xml = _escape_xml_text(sheet_name)
    output = BytesIO()
    with zipfile.ZipFile(output, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>""",
        )
        zf.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        )
        zf.writestr(
            "xl/workbook.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="{sheet_name_xml}" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>""",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        )
        zf.writestr(
            "xl/sharedStrings.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">
  {shared_xml}
</sst>""",
        )
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {sheet_xml}
  </sheetData>
</worksheet>""",
        )
    return output.getvalue()


def export_system_glossary_excel(*, library_id: int | None = None) -> bytes:
    items = load_department_glossary_items(library_id)
    if xlsxwriter is None:
        rows = [["cn", "en"]]
        rows.extend([[item["cn"], item["en"]] for item in items])
        return _build_xlsx_bytes(rows, sheet_name="SystemGlossary")

    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    worksheet = workbook.add_worksheet("SystemGlossary")
    header_format = workbook.add_format({"bold": True})
    worksheet.write(0, 0, "cn", header_format)
    worksheet.write(0, 1, "en", header_format)
    for row_index, item in enumerate(items, start=1):
        worksheet.write(row_index, 0, item["cn"])
        worksheet.write(row_index, 1, item["en"])
    worksheet.set_column(0, 0, 36)
    worksheet.set_column(1, 1, 54)
    workbook.close()
    return output.getvalue()


def apply_glossary(
    text: str,
    entries: list[tuple[str, str]] | None = None,
    *,
    source_lang: str = "auto",
    target_lang: str = "en",
) -> str:
    if not text:
        return text
    pairs = glossary_pairs_for_translation(
        entries,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    if not pairs:
        return text
    out = text
    hits: list[tuple[str, str]] = []
    for src, dst in pairs:
        if src in out:
            out = out.replace(src, dst)
            hits.append((src, dst))
    if hits:
        preview = ", ".join([f"{src}->{dst}" for src, dst in hits[:6]])
        more = f" (+{len(hits) - 6})" if len(hits) > 6 else ""
        print(f"[GLOSSARY] hits={len(hits)} {preview}{more}")
    return out


def apply_required_glossary_terms(
    text: str,
    entries: list[tuple[str, str]] | None = None,
    *,
    source_lang: str = "auto",
    target_lang: str = "en",
) -> GlossaryApplication:
    if not text:
        return GlossaryApplication(text=text, required_terms=tuple())
    pairs = glossary_pairs_for_translation(
        entries,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    if not pairs:
        return GlossaryApplication(text=text, required_terms=tuple())

    out_parts: list[str] = []
    hits: list[tuple[str, str]] = []
    required_terms: list[RequiredGlossaryTerm] = []
    i = 0
    term_index = 1
    while i < len(text):
        matched = False
        for src, dst in pairs:
            match_length = source_term_match_length(text, src, i)
            if match_length is not None:
                term_id = f"{term_index:04d}"
                required_terms.append(
                    RequiredGlossaryTerm(id=term_id, source=src, target=dst)
                )
                protected = (
                    f'<term id="{term_id}">'
                    f"{_escape_required_term_target(dst)}"
                    "</term>"
                )
                out_parts.append(protected)
                hits.append((src, dst))
                i += match_length
                term_index += 1
                matched = True
                break
        if matched:
            continue
        out_parts.append(text[i])
        i += 1

    if hits:
        preview = ", ".join([f"{src}->{dst}" for src, dst in hits[:6]])
        more = f" (+{len(hits) - 6})" if len(hits) > 6 else ""
        print(f"[GLOSSARY] required_hits={len(hits)} {preview}{more}")
    return GlossaryApplication(
        text="".join(out_parts),
        required_terms=tuple(required_terms),
    )


def apply_glossary_with_protection(
    text: str,
    entries: list[tuple[str, str]] | None = None,
    *,
    source_lang: str = "auto",
    target_lang: str = "en",
) -> str:
    if not text:
        return text
    pairs = glossary_pairs_for_translation(
        entries,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    if not pairs:
        return text

    out_parts: list[str] = []
    hits: list[tuple[str, str]] = []
    i = 0
    term_index = 1
    while i < len(text):
        matched = False
        for src, dst in pairs:
            match_length = source_term_match_length(text, src, i)
            if match_length is not None:
                protected = f"{_PROTECTED_TERM_PREFIX}{term_index:04d}::{dst}]]]"
                out_parts.append(protected)
                hits.append((src, dst))
                i += match_length
                term_index += 1
                matched = True
                break
        if matched:
            continue
        out_parts.append(text[i])
        i += 1

    if hits:
        preview = ", ".join([f"{src}->{dst}" for src, dst in hits[:6]])
        more = f" (+{len(hits) - 6})" if len(hits) > 6 else ""
        print(f"[GLOSSARY] protected_hits={len(hits)} {preview}{more}")
    return "".join(out_parts)


def restore_protected_glossary_terms(
    text: str,
    required_terms: RequiredTermContext = None,
) -> str:
    if not text:
        return text
    term_targets = _required_term_target_map(required_terms)

    def restore_required_term(match: re.Match[str]) -> str:
        term_id = match.group(1)
        wrapped_target = _unescape_required_term_target(match.group(2))
        return term_targets.get(term_id, wrapped_target)

    restored_parts: list[str] = []
    previous_required_term: str | None = None
    previous_end = 0
    for match in _REQUIRED_TERM_PATTERN.finditer(text):
        between = text[previous_end : match.start()]
        restored_term = restore_required_term(match)
        if (
            between == ""
            and previous_required_term is not None
            and _required_glossary_terms_need_separator(
                previous_required_term,
                restored_term,
            )
        ):
            restored_parts.append(" ")
        restored_parts.append(between)
        restored_parts.append(restored_term)
        previous_required_term = restored_term
        previous_end = match.end()

    if restored_parts:
        restored_parts.append(text[previous_end:])
        restored = "".join(restored_parts)
    else:
        restored = text
    if _PROTECTED_TERM_PREFIX in restored:
        restored = _PROTECTED_TERM_PATTERN.sub(lambda match: match.group(1), restored)
    return restored


def _required_glossary_terms_need_separator(left: str, right: str) -> bool:
    if not left or not right:
        return False
    if left[-1].isspace() or right[0].isspace():
        return False
    if not (_ASCII_WORD_RE.search(left) and _ASCII_WORD_RE.search(right)):
        return False
    return bool(
        _ASCII_TERM_TRAILING_RE.search(left)
        and _ASCII_TERM_LEADING_RE.search(right)
    )


def required_term_targets_from_text(text: str) -> dict[str, str]:
    if not text:
        return {}
    targets: dict[str, str] = {}
    for match in _REQUIRED_TERM_PATTERN.finditer(text):
        term_id = str(match.group(1) or "").strip()
        target = _unescape_required_term_target(match.group(2))
        if term_id and target:
            targets[term_id] = target
    return targets


def _normalize_required_glossary_match_text(value: str) -> str:
    normalized = str(value or "").casefold()
    normalized = re.sub(r"\s*([()])\s*", r"\1", normalized)
    normalized = re.sub(r"\s+", " ", normalized)
    return normalized.strip()


def find_missing_required_glossary_terms(
    text: str,
    required_terms: RequiredTermContext,
) -> list[str]:
    term_targets = _required_term_target_map(required_terms)
    normalized_text = _normalize_required_glossary_match_text(text)
    missing: list[str] = []
    seen: set[str] = set()
    for target in term_targets.values():
        normalized_target = _normalize_required_glossary_match_text(target)
        if not normalized_target or normalized_target in seen:
            continue
        seen.add(normalized_target)
        if normalized_target not in normalized_text:
            missing.append(target)
    return missing
