from __future__ import annotations

import json
import re
import threading
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from html import escape as _html_escape, unescape as _html_unescape
from io import BytesIO
from pathlib import Path
from typing import TypeAlias
import zipfile

from sqlalchemy import select, true
from xml.etree import ElementTree as ET

from lang_utils import normalize_lang_code

from . import job_store, state

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
class DepartmentGlossaryEntry:
    entry_id: int
    library_id: int
    source_lang: str
    target_lang: str
    source_term: str
    target_term: str
    status: str
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
        priority=int(record.priority or 0),
        notes=record.notes,
        created_by_work_id=record.created_by_work_id,
        updated_by_work_id=record.updated_by_work_id,
    )


def get_or_create_department_glossary_library(
    *,
    code: str,
    name: str,
    department_code: str,
    is_default: bool = False,
    is_active: bool = True,
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
        else:
            record.name = cleaned_name
            record.department_code = cleaned_department_code
            record.is_default = bool(is_default)
            record.is_active = bool(is_active)
            record.updated_at = now
            session.flush()
        return _library_from_record(record)


def get_or_create_default_department_glossary() -> DepartmentGlossaryLibrary:
    return get_or_create_department_glossary_library(
        code=DEFAULT_DEPARTMENT_GLOSSARY_CODE,
        name=DEFAULT_DEPARTMENT_GLOSSARY_NAME,
        department_code=DEFAULT_DEPARTMENT_GLOSSARY_NAME,
        is_default=True,
        is_active=True,
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


def upsert_department_glossary_entry(
    *,
    library_id: int,
    source_lang: str,
    target_lang: str,
    source_term: str,
    target_term: str,
    status: str = STATUS_ACTIVE,
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
            return int(record.id)
        record.target_term = cleaned_target_term
        record.priority = int(priority or 0)
        record.notes = str(notes).strip() if notes is not None and str(notes).strip() else None
        record.updated_by_work_id = (
            str(updated_by_work_id or created_by_work_id or "").strip() or record.updated_by_work_id
        )
        record.updated_at = now
        session.flush()
        return int(record.id)


def disable_department_glossary_entry(
    entry_id: int,
    *,
    updated_by_work_id: str | None = None,
) -> bool:
    with job_store.session_scope() as session:
        record = session.get(job_store.DepartmentGlossaryEntryRecord, int(entry_id))
        if record is None:
            return False
        record.status = STATUS_DISABLED
        record.updated_by_work_id = str(updated_by_work_id or "").strip() or record.updated_by_work_id
        record.updated_at = job_store.utcnow()
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


def load_default_department_glossary_items() -> list[dict[str, str]]:
    library = get_or_create_default_department_glossary()
    entries = list_department_glossary_entries(library.library_id, active_only=True)
    items = [_department_entry_to_compat_item(entry) for entry in entries]
    items.sort(key=lambda item: item["cn"])
    return items


def sync_default_department_glossary_items(
    items: list[dict[str, str]],
    *,
    replace: bool = True,
    updated_by_work_id: str | None = None,
) -> list[dict[str, str]]:
    library = get_or_create_default_department_glossary()
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
            library_id=library.library_id,
            source_lang="zh",
            target_lang="en",
            source_term=cn,
            target_term=en,
            updated_by_work_id=updated_by_work_id,
        )
    if replace:
        for entry in list_department_glossary_entries(library.library_id, active_only=True):
            if entry.source_term not in cleaned_by_cn:
                disable_department_glossary_entry(
                    entry.entry_id,
                    updated_by_work_id=updated_by_work_id,
                )
    return load_default_department_glossary_items()


def apply_default_department_glossary_import(items: list[dict[str, str]]) -> list[dict[str, str]]:
    return sync_default_department_glossary_items(items, replace=False)


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
        get_or_create_default_department_glossary()
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


def load_glossary_entries() -> list[tuple[str, str]]:
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


def load_combined_glossary() -> list[tuple[str, str]]:
    return load_glossary_entries()


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


def build_glossary_management_payload() -> dict[str, object]:
    selected_library = get_or_create_default_department_glossary()
    libraries = list_department_glossary_libraries(active_only=True)
    entries = list_department_glossary_entries(selected_library.library_id, active_only=True)
    entries.sort(key=lambda entry: entry.source_term)
    system_items = [_department_entry_to_compat_item(entry) for entry in entries]
    entry_payload = [_department_entry_to_payload(entry) for entry in entries]
    effective_items: list[dict[str, str | bool | None]] = [
        {
            "cn": item["cn"],
            "en": item["en"],
            "source": "system",
            "overridden": False,
            "system_en": item["en"],
            "user_en": None,
        }
        for item in system_items
    ]

    return {
        "system_glossary": system_items,
        "user_glossary": [],
        "effective_glossary": effective_items,
        "libraries": [_department_library_to_payload(library) for library in libraries],
        "selected_library": _department_library_to_payload(selected_library),
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


def build_system_glossary_import_preview(items: list[dict[str, str]]) -> dict[str, object]:
    current_items = load_default_department_glossary_items()
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


def apply_system_glossary_import(items: list[dict[str, str]]) -> list[dict[str, str]]:
    return apply_default_department_glossary_import(items)


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


def export_system_glossary_excel() -> bytes:
    items = load_default_department_glossary_items()
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
            if text.startswith(src, i):
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
                i += len(src)
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
            if text.startswith(src, i):
                protected = f"{_PROTECTED_TERM_PREFIX}{term_index:04d}::{dst}]]]"
                out_parts.append(protected)
                hits.append((src, dst))
                i += len(src)
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

    restored = _REQUIRED_TERM_PATTERN.sub(restore_required_term, text)
    if _PROTECTED_TERM_PREFIX in restored:
        restored = _PROTECTED_TERM_PATTERN.sub(lambda match: match.group(1), restored)
    return restored


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


def find_missing_required_glossary_terms(
    text: str,
    required_terms: RequiredTermContext,
) -> list[str]:
    term_targets = _required_term_target_map(required_terms)
    missing: list[str] = []
    seen: set[str] = set()
    for target in term_targets.values():
        if not target or target in seen:
            continue
        seen.add(target)
        if target not in text:
            missing.append(target)
    return missing
