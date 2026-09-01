from __future__ import annotations

import csv
import hashlib
import json
import re
import time
import unicodedata
from dataclasses import dataclass, replace
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

import click
from sqlalchemy import select

from . import job_store, state

_PUNCT_TRANSLATION = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "；": ";",
        "：": ":",
        "？": "?",
        "！": "!",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "「": '"',
        "」": '"',
        "『": '"',
        "』": '"',
        "、": ",",
        "．": ".",
        "／": "/",
        "％": "%",
        "＋": "+",
        "－": "-",
        "～": "~",
        "—": "-",
        "–": "-",
        "…": "...",
    }
)

_ENGLISH_TARGETS = {"en", "english", "en-us", "en-gb"}


STATUS_APPROVED = "approved"
STATUS_DISABLED = "disabled"
MATCH_BYTE_EXACT = "byte_exact"
MATCH_NORMALIZED_EXACT = "normalized_exact"
MATCH_FUZZY = "fuzzy"
IMPORT_ACTION_CREATED = "created"
IMPORT_ACTION_UPDATED = "updated"
IMPORT_ACTION_SKIPPED = "skipped"
IMPORT_ACTION_ERROR = "error"
IMPORT_ACTION_WOULD_CREATE = "would_create"
IMPORT_ACTION_WOULD_UPDATE = "would_update"
IMPORT_REASON_NEW_ENTRY = "new_entry"
IMPORT_REASON_APPROVED_CONFLICT = "approved_conflict"
IMPORT_REASON_APPROVED_CONFLICT_OVERWRITTEN = "approved_conflict_overwritten"
IMPORT_REASON_UNSUPPORTED_STATUS = "unsupported_status"
IMPORT_REASON_STATUS_MUST_BE_APPROVED = "status_must_be_approved"
IMPORT_REASON_EMPTY_NORMALIZED_SOURCE = "empty_normalized_source"

try:
    from rapidfuzz import fuzz as _rapidfuzz_fuzz
except ModuleNotFoundError:  # pragma: no cover - local fallback when dependency is absent.
    _rapidfuzz_fuzz = None




@dataclass(frozen=True)
class TranslationMemoryEntryInput:
    source_text: str
    target_text: str
    source_lang: str
    target_lang: str
    document_mode: str
    status: str = STATUS_APPROVED
    source_normalized: str | None = None
    source: str | None = None
    source_job_id: str | None = None
    source_metadata: dict[str, Any] | None = None
    notes: str | None = None

@dataclass(frozen=True)
class SqlTranslationMemoryEntry:
    entry_id: int
    source_text: str
    source_normalized: str
    target_text: str
    source_hash: str
    source_lang: str
    target_lang: str
    document_mode: str
    status: str
    source: str | None = None
    source_job_id: str | None = None
    source_metadata: dict[str, Any] | None = None
    notes: str | None = None
    exact_reuse_count: int = 0
    reference_count: int = 0
    created_at: datetime | None = None
    updated_at: datetime | None = None
    last_used_at: datetime | None = None
    last_referenced_at: datetime | None = None


@dataclass(frozen=True)
class TranslationMemoryMatch:
    entry_id: int
    match_type: str
    source_text: str
    source_normalized: str
    target_text: str
    source_lang: str
    target_lang: str
    document_mode: str
    score: float


@dataclass(frozen=True)
class TranslationMemoryRetrievalResult:
    source_text: str
    source_normalized: str
    source_lang: str
    target_lang: str
    document_mode: str
    exact_match: TranslationMemoryMatch | None
    fuzzy_references: list[TranslationMemoryMatch]
    semantic_references: list[TranslationMemoryMatch]


REQUIRED_IMPORT_COLUMNS = frozenset(
    {
        "source_text",
        "target_text",
        "source_lang",
        "target_lang",
        "document_mode",
        "status",
    }
)


@dataclass(frozen=True)
class TranslationMemoryImportDetail:
    row_number: int
    action: str
    reason: str
    entry_id: int | None = None


@dataclass(frozen=True)
class TranslationMemoryImportSummary:
    dry_run: bool
    overwrite: bool
    scanned: int = 0
    created: int = 0
    updated: int = 0
    skipped: int = 0
    would_create: int = 0
    would_update: int = 0
    errors: int = 0
    details: tuple[TranslationMemoryImportDetail, ...] = ()


def _empty_retrieval_result(
    source_text: str,
    *,
    source_lang: str,
    target_lang: str,
    document_mode: str,
    source_normalized: str | None = None,
) -> TranslationMemoryRetrievalResult:
    normalized_source = (
        source_normalized
        if source_normalized is not None
        else normalize_source_text(source_text)
    )
    return TranslationMemoryRetrievalResult(
        source_text=str(source_text or ""),
        source_normalized=normalized_source,
        source_lang=normalize_source_lang(source_lang),
        target_lang=normalize_target_lang(target_lang),
        document_mode=normalize_document_mode(document_mode),
        exact_match=None,
        fuzzy_references=[],
        semantic_references=[],
    )


def normalize_source_lang(source_lang: str | None) -> str:
    cleaned = str(source_lang or "auto").strip().lower().replace("_", "-")
    return cleaned or "auto"


def normalize_status(status: str | None) -> str:
    cleaned = str(status or STATUS_APPROVED).strip().lower()
    if cleaned in {STATUS_APPROVED, STATUS_DISABLED}:
        return cleaned
    raise ValueError(f"Unsupported Translation Memory status: {status}")


def source_hash(source_normalized: str) -> str:
    return hashlib.sha256(str(source_normalized or "").encode("utf-8")).hexdigest()


def _serialize_metadata(payload: dict[str, Any] | None) -> str | None:
    if not payload:
        return None
    return json.dumps(payload, ensure_ascii=False)


def _deserialize_metadata(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return payload if isinstance(payload, dict) else {}


def _row_to_entry(row: job_store.TranslationMemoryEntryRecord) -> SqlTranslationMemoryEntry:
    return SqlTranslationMemoryEntry(
        entry_id=int(row.id),
        source_text=str(row.source_text or ""),
        source_normalized=str(row.source_normalized or ""),
        target_text=str(row.target_text or ""),
        source_hash=str(row.source_hash or ""),
        source_lang=str(row.source_lang or ""),
        target_lang=str(row.target_lang or ""),
        document_mode=str(row.document_mode or ""),
        status=str(row.status or ""),
        source=row.source,
        source_job_id=row.source_job_id,
        source_metadata=_deserialize_metadata(row.source_metadata_json),
        notes=row.notes,
        exact_reuse_count=int(row.exact_reuse_count or 0),
        reference_count=int(row.reference_count or 0),
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_used_at=row.last_used_at,
        last_referenced_at=row.last_referenced_at,
    )


def _row_to_match(
    row: job_store.TranslationMemoryEntryRecord,
    *,
    match_type: str,
    score: float,
) -> TranslationMemoryMatch:
    return TranslationMemoryMatch(
        entry_id=int(row.id),
        match_type=match_type,
        source_text=str(row.source_text or ""),
        source_normalized=str(row.source_normalized or ""),
        target_text=str(row.target_text or ""),
        source_lang=str(row.source_lang or ""),
        target_lang=str(row.target_lang or ""),
        document_mode=str(row.document_mode or ""),
        score=float(score),
    )


def _fuzzy_score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if _rapidfuzz_fuzz is not None:
        return float(_rapidfuzz_fuzz.ratio(left, right)) / 100.0
    return SequenceMatcher(None, left, right).ratio()


def _approved_candidates(
    *,
    source_lang: str,
    target_lang: str,
) -> list[job_store.TranslationMemoryEntryRecord]:
    with job_store.session_scope() as session:
        stmt = (
            select(job_store.TranslationMemoryEntryRecord)
            .where(job_store.TranslationMemoryEntryRecord.status == STATUS_APPROVED)
            .where(
                job_store.TranslationMemoryEntryRecord.source_lang
                == normalize_source_lang(source_lang)
            )
            .where(
                job_store.TranslationMemoryEntryRecord.target_lang
                == normalize_target_lang(target_lang)
            )
            .order_by(
                job_store.TranslationMemoryEntryRecord.updated_at.desc(),
                job_store.TranslationMemoryEntryRecord.id.desc(),
            )
        )
        return list(session.scalars(stmt).all())


def get_sql_entry(entry_id: int) -> SqlTranslationMemoryEntry | None:
    with job_store.session_scope() as session:
        row = session.get(job_store.TranslationMemoryEntryRecord, int(entry_id))
        return _row_to_entry(row) if row is not None else None


def _sql_entry_lookup_stmt(
    *,
    source_normalized: str,
    source_lang: str,
    target_lang: str,
    document_mode: str,
    status: str,
):
    return (
        select(job_store.TranslationMemoryEntryRecord)
        .where(
            job_store.TranslationMemoryEntryRecord.source_hash
            == source_hash(source_normalized)
        )
        .where(job_store.TranslationMemoryEntryRecord.source_normalized == source_normalized)
        .where(
            job_store.TranslationMemoryEntryRecord.source_lang
            == normalize_source_lang(source_lang)
        )
        .where(
            job_store.TranslationMemoryEntryRecord.target_lang
            == normalize_target_lang(target_lang)
        )
        .where(
            job_store.TranslationMemoryEntryRecord.document_mode
            == normalize_document_mode(document_mode)
        )
        .where(job_store.TranslationMemoryEntryRecord.status == normalize_status(status))
        .order_by(
            job_store.TranslationMemoryEntryRecord.updated_at.desc(),
            job_store.TranslationMemoryEntryRecord.id.desc(),
        )
    )


def find_sql_entry(
    source_text: str,
    *,
    source_lang: str,
    target_lang: str,
    document_mode: str,
    status: str = STATUS_APPROVED,
    source_normalized: str | None = None,
) -> SqlTranslationMemoryEntry | None:
    normalized_source = (
        source_normalized
        if source_normalized is not None
        else normalize_source_text(source_text)
    )
    normalized_source = normalize_source_text(normalized_source)
    if not normalized_source:
        return None
    stmt = _sql_entry_lookup_stmt(
        source_normalized=normalized_source,
        source_lang=source_lang,
        target_lang=target_lang,
        document_mode=document_mode,
        status=status,
    )
    with job_store.session_scope() as session:
        row = session.scalars(stmt).first()
        return _row_to_entry(row) if row is not None else None


def _validate_import_columns(fieldnames: list[str] | None) -> None:
    supplied = {
        str(field or "").strip()
        for field in (fieldnames or [])
        if str(field or "").strip()
    }
    missing = sorted(REQUIRED_IMPORT_COLUMNS - supplied)
    if missing:
        raise ValueError("missing required CSV columns: " + ", ".join(missing))


def _validate_import_row(
    row: dict[str, str],
) -> tuple[TranslationMemoryEntryInput | None, str | None]:
    try:
        status = normalize_status(row.get("status"))
    except ValueError:
        return None, IMPORT_REASON_UNSUPPORTED_STATUS
    if status != STATUS_APPROVED:
        return None, IMPORT_REASON_STATUS_MUST_BE_APPROVED

    required_values = {
        column: str(row.get(column) or "").strip()
        for column in REQUIRED_IMPORT_COLUMNS
    }
    missing_values = sorted(
        column for column, value in required_values.items() if not value
    )
    if missing_values:
        return None, "missing_required_values:" + ",".join(missing_values)

    source_text = required_values["source_text"]
    target_text = required_values["target_text"]
    if not normalize_source_text(source_text):
        return None, IMPORT_REASON_EMPTY_NORMALIZED_SOURCE
    return (
        TranslationMemoryEntryInput(
            source_text=source_text,
            target_text=target_text,
            source_lang=required_values["source_lang"],
            target_lang=required_values["target_lang"],
            document_mode=required_values["document_mode"],
            status=status,
            source="csv_import",
            notes=str(row.get("notes") or "").strip() or None,
        ),
        None,
    )


def _process_import_row(
    row: dict[str, str],
    *,
    row_number: int,
    apply: bool,
    overwrite: bool,
) -> TranslationMemoryImportDetail:
    entry, error_reason = _validate_import_row(row)
    if entry is None:
        return TranslationMemoryImportDetail(
            row_number=row_number,
            action=IMPORT_ACTION_ERROR,
            reason=error_reason or "invalid_row",
        )

    existing = find_sql_entry(
        entry.source_text,
        source_lang=entry.source_lang,
        target_lang=entry.target_lang,
        document_mode=entry.document_mode,
        status=STATUS_APPROVED,
    )
    if existing is not None and not overwrite:
        return TranslationMemoryImportDetail(
            row_number=row_number,
            action=IMPORT_ACTION_SKIPPED,
            reason=IMPORT_REASON_APPROVED_CONFLICT,
            entry_id=existing.entry_id,
        )

    if not apply:
        if existing is not None:
            return TranslationMemoryImportDetail(
                row_number=row_number,
                action=IMPORT_ACTION_WOULD_UPDATE,
                reason=IMPORT_REASON_APPROVED_CONFLICT,
                entry_id=existing.entry_id,
            )
        return TranslationMemoryImportDetail(
            row_number=row_number,
            action=IMPORT_ACTION_WOULD_CREATE,
            reason=IMPORT_REASON_NEW_ENTRY,
        )

    entry_id = upsert_sql_entry_input(entry)
    if existing is not None:
        return TranslationMemoryImportDetail(
            row_number=row_number,
            action=IMPORT_ACTION_UPDATED,
            reason=IMPORT_REASON_APPROVED_CONFLICT_OVERWRITTEN,
            entry_id=entry_id,
        )
    return TranslationMemoryImportDetail(
        row_number=row_number,
        action=IMPORT_ACTION_CREATED,
        reason=IMPORT_REASON_NEW_ENTRY,
        entry_id=entry_id,
    )


def _summary_from_details(
    *,
    apply: bool,
    overwrite: bool,
    scanned: int,
    details: list[TranslationMemoryImportDetail],
) -> TranslationMemoryImportSummary:
    counts = {
        IMPORT_ACTION_CREATED: 0,
        IMPORT_ACTION_UPDATED: 0,
        IMPORT_ACTION_SKIPPED: 0,
        IMPORT_ACTION_WOULD_CREATE: 0,
        IMPORT_ACTION_WOULD_UPDATE: 0,
        IMPORT_ACTION_ERROR: 0,
    }
    for detail in details:
        counts[detail.action] = counts.get(detail.action, 0) + 1
    return TranslationMemoryImportSummary(
        dry_run=not apply,
        overwrite=overwrite,
        scanned=scanned,
        created=counts[IMPORT_ACTION_CREATED],
        updated=counts[IMPORT_ACTION_UPDATED],
        skipped=counts[IMPORT_ACTION_SKIPPED],
        would_create=counts[IMPORT_ACTION_WOULD_CREATE],
        would_update=counts[IMPORT_ACTION_WOULD_UPDATE],
        errors=counts[IMPORT_ACTION_ERROR],
        details=tuple(details),
    )


def import_csv(
    csv_path: Path | str,
    *,
    apply: bool = False,
    overwrite: bool = False,
) -> TranslationMemoryImportSummary:
    path = Path(csv_path)
    details: list[TranslationMemoryImportDetail] = []
    scanned = 0
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        _validate_import_columns(reader.fieldnames)
        for row_number, row in enumerate(reader, start=2):
            scanned += 1
            details.append(
                _process_import_row(
                    row,
                    row_number=row_number,
                    apply=apply,
                    overwrite=overwrite,
                )
            )
    return _summary_from_details(
        apply=apply,
        overwrite=overwrite,
        scanned=scanned,
        details=details,
    )


def register_translation_memory_cli(app) -> None:
    @app.cli.command("tm-import")
    @click.argument(
        "csv_path",
        type=click.Path(exists=True, dir_okay=False, path_type=Path),
    )
    @click.option(
        "--apply",
        "apply_changes",
        is_flag=True,
        help="Write approved CSV entries to SQL. Defaults to dry-run.",
    )
    @click.option(
        "--overwrite",
        is_flag=True,
        help="Overwrite existing approved entries with matching source/language/mode.",
    )
    def tm_import_command(
        csv_path: Path,
        apply_changes: bool,
        overwrite: bool,
    ) -> None:
        try:
            summary = import_csv(
                csv_path,
                apply=apply_changes,
                overwrite=overwrite,
            )
        except ValueError as exc:
            raise click.ClickException(str(exc)) from exc
        click.echo(
            "tm_import "
            f"dry_run={'1' if summary.dry_run else '0'} "
            f"overwrite={'1' if summary.overwrite else '0'} "
            f"scanned={summary.scanned} "
            f"created={summary.created} "
            f"updated={summary.updated} "
            f"would_create={summary.would_create} "
            f"would_update={summary.would_update} "
            f"skipped={summary.skipped} "
            f"errors={summary.errors}"
        )
        for detail in summary.details:
            parts = [
                "tm_import_detail",
                f"row={detail.row_number}",
                f"action={detail.action}",
                f"reason={detail.reason}",
            ]
            if detail.entry_id is not None:
                parts.append(f"entry_id={detail.entry_id}")
            click.echo(" ".join(parts))
        if summary.errors:
            raise click.ClickException(
                "Some Translation Memory rows could not be imported."
            )


def upsert_sql_entry_input(entry: TranslationMemoryEntryInput, *, now: datetime | None = None) -> int | None:
    return upsert_sql_entry(
        source_text=entry.source_text,
        target_text=entry.target_text,
        source_lang=entry.source_lang,
        target_lang=entry.target_lang,
        document_mode=entry.document_mode,
        status=entry.status,
        source_normalized=entry.source_normalized,
        source=entry.source,
        source_job_id=entry.source_job_id,
        source_metadata=entry.source_metadata,
        notes=entry.notes,
        now=now,
    )

def upsert_sql_entry(
    *,
    source_text: str,
    target_text: str,
    source_lang: str,
    target_lang: str,
    document_mode: str,
    status: str = STATUS_APPROVED,
    source_normalized: str | None = None,
    source: str | None = None,
    source_job_id: str | None = None,
    source_metadata: dict[str, Any] | None = None,
    notes: str | None = None,
    now: datetime | None = None,
) -> int | None:
    normalized_source = (
        source_normalized
        if source_normalized is not None
        else normalize_source_text(source_text)
    )
    normalized_source = normalize_source_text(normalized_source)
    cleaned_target = str(target_text or "").strip()
    if not normalized_source or not cleaned_target:
        return None

    normalized_source_lang = normalize_source_lang(source_lang)
    normalized_target_lang = normalize_target_lang(target_lang)
    normalized_mode = normalize_document_mode(document_mode)
    normalized_status = normalize_status(status)
    normalized_hash = source_hash(normalized_source)
    timestamp = now or job_store.utcnow()
    with job_store.session_scope() as session:
        stmt = _sql_entry_lookup_stmt(
            source_normalized=normalized_source,
            source_lang=normalized_source_lang,
            target_lang=normalized_target_lang,
            document_mode=normalized_mode,
            status=normalized_status,
        )
        row = session.scalars(stmt).first()
        if row is None:
            row = job_store.TranslationMemoryEntryRecord(
                source_text=str(source_text or ""),
                source_normalized=normalized_source,
                target_text=cleaned_target,
                source_hash=normalized_hash,
                source_lang=normalized_source_lang,
                target_lang=normalized_target_lang,
                document_mode=normalized_mode,
                status=normalized_status,
                source=str(source or "").strip() or None,
                source_job_id=str(source_job_id or "").strip() or None,
                source_metadata_json=_serialize_metadata(source_metadata),
                notes=str(notes or "").strip() or None,
                exact_reuse_count=0,
                reference_count=0,
                created_at=timestamp,
                updated_at=timestamp,
                last_used_at=None,
                last_referenced_at=None,
            )
            session.add(row)
            session.flush()
            return int(row.id)
        row.source_text = str(source_text or "")
        row.source_normalized = normalized_source
        row.source_hash = normalized_hash
        row.target_text = cleaned_target
        row.source = str(source or "").strip() or row.source
        row.source_job_id = str(source_job_id or "").strip() or row.source_job_id
        row.source_metadata_json = _serialize_metadata(source_metadata) or row.source_metadata_json
        row.notes = str(notes or "").strip() or row.notes
        row.updated_at = timestamp
        session.flush()
        return int(row.id)


def retrieve_sql(
    source_text: str,
    *,
    source_lang: str,
    target_lang: str,
    document_mode: str,
    fuzzy_threshold: float | None = None,
    fuzzy_limit: int | None = None,
    min_fuzzy_chars: int | None = None,
) -> TranslationMemoryRetrievalResult:
    normalized_source = normalize_source_text(source_text)
    normalized_source_lang = normalize_source_lang(source_lang)
    normalized_target_lang = normalize_target_lang(target_lang)
    normalized_mode = normalize_document_mode(document_mode)
    result = _empty_retrieval_result(
        source_text,
        source_lang=normalized_source_lang,
        target_lang=normalized_target_lang,
        document_mode=normalized_mode,
        source_normalized=normalized_source,
    )
    if not bool(getattr(state, "TRANSLATION_MEMORY_ENABLED", False)) or not normalized_source:
        return result

    candidates = _approved_candidates(
        source_lang=normalized_source_lang,
        target_lang=normalized_target_lang,
    )
    same_mode = [row for row in candidates if row.document_mode == normalized_mode]
    source_string = str(source_text or "")
    for row in same_mode:
        if (
            str(row.source_text or "") == source_string
            and str(row.source_normalized or "") == normalized_source
        ):
            return replace(
                result,
                exact_match=_row_to_match(
                    row, match_type=MATCH_BYTE_EXACT, score=1.0
                ),
            )
    for row in same_mode:
        if str(row.source_normalized or "") == normalized_source:
            return replace(
                result,
                exact_match=_row_to_match(
                    row, match_type=MATCH_NORMALIZED_EXACT, score=1.0
                ),
            )

    limit = (
        state.TRANSLATION_MEMORY_FUZZY_LIMIT
        if fuzzy_limit is None
        else max(0, int(fuzzy_limit))
    )
    threshold = (
        state.TRANSLATION_MEMORY_FUZZY_THRESHOLD
        if fuzzy_threshold is None
        else float(fuzzy_threshold)
    )
    min_chars = (
        state.TRANSLATION_MEMORY_MIN_FUZZY_CHARS
        if min_fuzzy_chars is None
        else max(0, int(min_fuzzy_chars))
    )
    if limit <= 0 or len(normalized_source) < min_chars:
        return result

    scored: list[tuple[float, job_store.TranslationMemoryEntryRecord]] = []
    for row in candidates:
        score = _fuzzy_score(normalized_source, str(row.source_normalized or ""))
        if score >= threshold:
            scored.append((score, row))
    scored.sort(
        key=lambda item: (item[0], item[1].updated_at, item[1].id),
        reverse=True,
    )
    references = [
        _row_to_match(row, match_type=MATCH_FUZZY, score=score)
        for score, row in scored[:limit]
    ]
    return replace(
        result,
        fuzzy_references=references,
        semantic_references=retrieve_semantic_references(
            source_text,
            source_lang=normalized_source_lang,
            target_lang=normalized_target_lang,
            document_mode=normalized_mode,
        ),
    )




def retrieve_semantic_references(
    source_text: str,
    *,
    source_lang: str,
    target_lang: str,
    document_mode: str,
    limit: int | None = None,
) -> list[TranslationMemoryMatch]:
    # First-phase semantic retrieval seam. Embedding/vector search plugs in here later.
    return []

def _record_counter(
    entry_ids: list[int] | tuple[int, ...],
    *,
    counter_field: str,
    timestamp_field: str,
) -> None:
    ids = [int(entry_id) for entry_id in entry_ids if entry_id]
    if not ids:
        return
    now = job_store.utcnow()
    with job_store.session_scope() as session:
        rows = session.scalars(
            select(job_store.TranslationMemoryEntryRecord).where(
                job_store.TranslationMemoryEntryRecord.id.in_(ids)
            )
        ).all()
        for row in rows:
            increment = ids.count(int(row.id))
            setattr(row, counter_field, int(getattr(row, counter_field) or 0) + increment)
            setattr(row, timestamp_field, now)
            row.updated_at = now


def record_exact_reuse(entry_ids: list[int] | tuple[int, ...]) -> None:
    _record_counter(
        entry_ids,
        counter_field="exact_reuse_count",
        timestamp_field="last_used_at",
    )


def record_reference_use(entry_ids: list[int] | tuple[int, ...]) -> None:
    _record_counter(
        entry_ids,
        counter_field="reference_count",
        timestamp_field="last_referenced_at",
    )

def normalize_source_text(text: str | None) -> str:
    if text is None:
        return ""
    cleaned = unicodedata.normalize("NFKC", str(text))
    cleaned = cleaned.translate(_PUNCT_TRANSLATION)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def normalize_target_lang(target_lang: str | None) -> str:
    cleaned = str(target_lang or "").strip().lower()
    if not cleaned:
        return "en"
    if cleaned in _ENGLISH_TARGETS:
        return "en"
    return cleaned


def normalize_document_mode(document_mode: str | None) -> str:
    cleaned = str(document_mode or "").strip().lower()
    if cleaned == "word":
        return "word"
    if cleaned == "general":
        return "general"
    if cleaned == "scanned":
        return "scanned"
    return "form"


def make_tm_key(
    source_text: str,
    target_lang: str,
    document_mode: str,
    *,
    source_normalized: str | None = None,
) -> str:
    normalized_source = (
        source_normalized
        if source_normalized is not None
        else normalize_source_text(source_text)
    )
    return (
        f"{normalize_document_mode(document_mode)}|"
        f"{normalize_target_lang(target_lang)}|"
        f"{normalized_source}"
    )


def _normalize_tm_entry(
    key: str,
    value: Any,
    now_ts: float,
) -> dict[str, Any] | None:
    if isinstance(value, str):
        value = {"target_text": value, "last_used": now_ts}
    if not isinstance(value, dict):
        return None

    target_text = value.get("target_text")
    if not isinstance(target_text, str):
        legacy_text = value.get("text")
        if not isinstance(legacy_text, str):
            return None
        target_text = legacy_text

    source_text = value.get("source_text")
    if source_text is not None:
        source_text = str(source_text)

    source_normalized = value.get("source_normalized")
    if source_normalized is None and source_text:
        source_normalized = normalize_source_text(source_text)
    elif source_normalized is not None:
        source_normalized = normalize_source_text(str(source_normalized))

    target_lang = value.get("target_lang")
    if target_lang is not None:
        target_lang = normalize_target_lang(str(target_lang))

    document_mode = value.get("document_mode")
    if document_mode is not None:
        document_mode = normalize_document_mode(str(document_mode))

    last_used = value.get("last_used")
    try:
        last_used_ts = float(last_used) if last_used is not None else now_ts
    except (TypeError, ValueError):
        last_used_ts = now_ts

    created_at = value.get("created_at")
    try:
        created_at_ts = float(created_at) if created_at is not None else last_used_ts
    except (TypeError, ValueError):
        created_at_ts = last_used_ts

    count = value.get("count")
    try:
        count_int = max(1, int(count)) if count is not None else 1
    except (TypeError, ValueError):
        count_int = 1

    entry_source = str(value.get("source") or "batch").strip() or "batch"
    normalized = {
        "source_text": source_text,
        "source_normalized": source_normalized,
        "target_text": target_text,
        "target_lang": target_lang,
        "document_mode": document_mode,
        "created_at": created_at_ts,
        "last_used": last_used_ts,
        "source": entry_source,
        "count": count_int,
    }

    # Keep legacy English form entries readable until they are promoted.
    if (
        "|" not in key
        and normalized["source_normalized"] is None
        and isinstance(key, str)
        and key.strip()
    ):
        normalized["source_normalized"] = normalize_source_text(key)

    return normalized


def load_translation_memory() -> dict[str, dict[str, Any]]:
    path = state.TRANSLATION_MEMORY_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    now_ts = time.time()
    ttl_seconds = state.TRANSLATION_MEMORY_TTL_SECONDS
    cleaned: dict[str, dict[str, Any]] = {}
    changed = False
    for k, v in data.items():
        if not isinstance(k, str):
            changed = True
            continue
        entry = _normalize_tm_entry(k, v, now_ts)
        if not entry:
            changed = True
            continue
        last_used = entry.get("last_used", now_ts)
        if ttl_seconds and (now_ts - float(last_used) > ttl_seconds):
            changed = True
            continue
        cleaned[k] = entry
        if entry != v:
            changed = True
    if changed:
        write_translation_memory(cleaned)
    return cleaned


def write_translation_memory(memory: dict[str, dict[str, Any]]) -> None:
    path = state.TRANSLATION_MEMORY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_target_text(entry: dict[str, Any] | None) -> str:
    if not isinstance(entry, dict):
        return ""
    target_text = entry.get("target_text")
    if isinstance(target_text, str):
        return target_text
    legacy_text = entry.get("text")
    return str(legacy_text or "")


def get_tm_entry(
    memory: dict[str, dict[str, Any]],
    source_text: str,
    target_lang: str,
    document_mode: str,
    *,
    source_normalized: str | None = None,
) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    normalized_source = (
        source_normalized
        if source_normalized is not None
        else normalize_source_text(source_text)
    )
    if not normalized_source:
        return None, None

    key = make_tm_key(
        source_text,
        target_lang,
        document_mode,
        source_normalized=normalized_source,
    )
    entry = memory.get(key)
    if entry:
        return key, entry

    legacy_key = normalized_source
    legacy_entry = memory.get(legacy_key)
    if (
        legacy_entry
        and normalize_document_mode(document_mode) == "form"
        and normalize_target_lang(target_lang) in _ENGLISH_TARGETS
    ):
        return legacy_key, legacy_entry
    return None, None


def touch_entry(entry: dict[str, Any], now_ts: float | None = None) -> None:
    entry["last_used"] = float(now_ts if now_ts is not None else time.time())


def upsert_entry(
    memory: dict[str, dict[str, Any]],
    source_text: str,
    target_text: str,
    target_lang: str,
    document_mode: str,
    *,
    source_normalized: str | None = None,
    source: str = "batch",
    now_ts: float | None = None,
) -> str | None:
    normalized_source = (
        source_normalized
        if source_normalized is not None
        else normalize_source_text(source_text)
    )
    cleaned_target = str(target_text or "").strip()
    if not normalized_source or not cleaned_target:
        return None

    now = float(now_ts if now_ts is not None else time.time())
    key = make_tm_key(
        source_text,
        target_lang,
        document_mode,
        source_normalized=normalized_source,
    )
    existing = memory.get(key)
    created_at = now
    count = 1
    if existing:
        created_at = float(existing.get("created_at") or now)
        try:
            count = max(1, int(existing.get("count") or 0)) + 1
        except (TypeError, ValueError):
            count = 1

    memory[key] = {
        "source_text": str(source_text or ""),
        "source_normalized": normalized_source,
        "target_text": cleaned_target,
        "target_lang": normalize_target_lang(target_lang),
        "document_mode": normalize_document_mode(document_mode),
        "created_at": created_at,
        "last_used": now,
        "source": str(source or "batch").strip() or "batch",
        "count": count,
    }
    return key
