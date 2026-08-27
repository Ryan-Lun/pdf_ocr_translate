from __future__ import annotations

import io
import json
import logging
import re
import shutil
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from flask import url_for

from . import job_store, state

DB_STATUS_BY_BATCH = {
    "running": "running",
    "queued": "queued",
    "completed": "completed",
    "failed": "failed",
    "canceled": "cancelled",
    "cancelled": "cancelled",
}

LEGACY_STAGE_KEY_BY_TYPE = {
    "doc_workspace": "doc_stage",
    "word_translate": "word_stage",
}

DOC_STAGE_DISPLAY = {
    "queued": ("uploaded", "已上傳"),
    "extract": ("structure", "辨識中"),
    "html": ("html", "HTML 轉檔中"),
    "translate": ("translate", "翻譯中"),
    "docx": ("docx", "轉檔中"),
    "completed": ("completed", "完成"),
    "failed": ("failed", "失敗"),
    "cancelled": ("cancelled", "已取消"),
}

WORD_STAGE_DISPLAY = {
    "queued": ("uploaded", "已上傳"),
    "prepare": ("prepare", "準備中"),
    "translate": ("translate", "翻譯中"),
    "save": ("save", "輸出中"),
    "completed": ("completed", "完成"),
    "failed": ("failed", "失敗"),
    "cancelled": ("cancelled", "已取消"),
}

OCR_STAGE_DISPLAY = {
    "queued": ("uploaded", "已上傳"),
    "ocr": ("ocr", "OCR"),
    "translate": ("translate", "翻譯中"),
    "render": ("render", "輸出中"),
    "completed": ("completed", "完成"),
    "failed": ("failed", "失敗"),
    "cancelled": ("cancelled", "已取消"),
}


logger = logging.getLogger(__name__)


_CONNECTION_POOL_RE = re.compile(r"\bHTTPS?ConnectionPool\([^)]*\):\s*", re.IGNORECASE)


def sanitize_job_message(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    return _CONNECTION_POOL_RE.sub("", text).strip() or None


def _job_error_message(
    record: Any, *fallbacks: Any
) -> str | None:
    record_error = sanitize_job_message(getattr(record, "error_message", None))
    if record_error:
        return record_error
    record_status = str(getattr(record, "status", "") or "").lower()
    if record_status in {"completed", "queued"}:
        return None
    for fallback in fallbacks:
        cleaned = sanitize_job_message(fallback)
        if cleaned:
            return cleaned
    return None


def _serialize_warning_events(events: list[Any]) -> list[dict[str, Any]]:
    warnings: list[dict[str, Any]] = []
    for event in events:
        message = sanitize_job_message(getattr(event, "message", ""))
        if not message:
            continue
        warnings.append(
            {
                "message": message,
                "stage": str(getattr(event, "stage", "") or "") or None,
                "created_at": timestamp_from_datetime(getattr(event, "created_at", None)),
            }
        )
    return warnings


def record_job_warning(job_dir_path: Path, *, stage: str, message: str, progress: float | None = None) -> None:
    cleaned_message = sanitize_job_message(message)
    if not cleaned_message:
        return
    job_store.append_event(job_dir_path.name, "warning", stage=stage, message=cleaned_message)
    set_job_state(
        job_dir_path,
        status="running",
        stage=stage,
        progress=progress,
        extra_meta={
            "last_warning": cleaned_message,
            "last_warning_at": time.time(),
        },
    )


def safe_job_id(job_id: str) -> bool:
    return bool(re.fullmatch(r"[a-f0-9]{32}", job_id))


def datetime_from_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


def timestamp_from_datetime(value: datetime | None) -> float | None:
    if value is None:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.timestamp()


def normalize_job_name(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = sanitize_unicode_filename(value, fallback="")
        cleaned = re.sub(r"_[a-f0-9]{8}$", "", cleaned)
        return cleaned or None
    return None


def get_job_name(job_dir_path: Path) -> str | None:
    meta = load_job_meta(job_dir_path) or {}
    return normalize_job_name(meta.get("job_name"))


def get_job_type(job_dir_path: Path) -> str:
    meta = load_job_meta(job_dir_path) or {}
    job_type = str(meta.get("job_type") or "").strip().lower()
    if job_type == "doc_workspace":
        return "doc_workspace"
    if job_type == "word_translate":
        return "word_translate"
    if job_type == "template_source":
        return "template_source"
    return "ocr_overlay"


def normalize_document_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode in {"other", "other_document", "other_documents"}:
        return "other"
    if mode in {"general_force_translate", "general_force"}:
        return "general_force"
    if mode == "general":
        return "general"
    if mode == "scanned":
        return "scanned"
    return "form"


def normalize_translate_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode == "realtime":
        return "realtime"
    return "batch"


def build_download_base(job_id: str, job_name: str | None) -> str:
    base = job_name or "translated"
    safe = sanitize_unicode_filename(base, fallback="translated")
    return safe


def sanitize_unicode_filename(value: Any, fallback: str = "file") -> str:
    if value is None:
        return fallback
    cleaned = str(value).strip()
    cleaned = cleaned.replace("\x00", "")
    cleaned = re.sub(r"[<>:\"/\\\\|?*\x00-\x1f]", "_", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    return cleaned or fallback


def build_download_name(
    job_id: str, job_name: str | None, ext: str = "pdf", suffix: str = "translate"
) -> str:
    base = build_download_base(job_id, job_name)
    return f"{base}_{suffix}.{ext}" if suffix else f"{base}.{ext}"


def build_doc_markdown_name(job_id: str, job_name: str | None, translated: bool = False) -> str:
    suffix = "translated" if translated else "structure"
    return build_download_name(job_id, job_name, ext="md", suffix=suffix)


def build_doc_html_name(job_id: str, job_name: str | None, translated: bool = False) -> str:
    suffix = "translated" if translated else "structure"
    return build_download_name(job_id, job_name, ext="html", suffix=suffix)


def build_docx_name(job_id: str, job_name: str | None) -> str:
    return build_download_name(job_id, job_name, ext="docx", suffix="translated")


def _custom_job_root_active() -> bool:
    return Path(state.JOB_ROOT) != Path(getattr(state, "DEFAULT_JOB_ROOT", state.JOB_ROOT))


def job_root_for_type(job_type: str | None) -> Path:
    if _custom_job_root_active():
        return state.JOB_ROOT
    normalized = str(job_type or "").strip().lower()
    if normalized == "doc_workspace":
        return state.DOC_WORKSPACE_JOB_ROOT
    if normalized == "word_translate":
        return state.WORD_TRANSLATE_JOB_ROOT
    if normalized == "template_source":
        return state.TEMPLATE_JOB_ROOT
    return state.PDF_OVERLAY_JOB_ROOT


def iter_job_roots() -> list[Path]:
    roots = [
        state.PDF_OVERLAY_JOB_ROOT,
        state.DOC_WORKSPACE_JOB_ROOT,
        state.WORD_TRANSLATE_JOB_ROOT,
        state.JOB_ROOT,
        state.TEMPLATE_JOB_ROOT,
    ]
    seen: set[Path] = set()
    result: list[Path] = []
    for root in roots:
        resolved = Path(root)
        if resolved in seen:
            continue
        seen.add(resolved)
        result.append(resolved)
    return result


def iter_job_dirs(job_type: str | None = None, include_templates: bool = False) -> list[Path]:
    if job_type:
        roots = [job_root_for_type(job_type)]
        if state.JOB_ROOT not in roots:
            roots.append(state.JOB_ROOT)
    else:
        roots = iter_job_roots()
    if include_templates and state.TEMPLATE_JOB_ROOT not in roots:
        roots.append(state.TEMPLATE_JOB_ROOT)
    dirs: list[Path] = []
    seen: set[str] = set()
    for root in roots:
        if not root.exists():
            continue
        for job_dir_path in sorted(root.iterdir()):
            if not job_dir_path.is_dir() or not safe_job_id(job_dir_path.name):
                continue
            if job_dir_path.name in seen:
                continue
            if job_type and get_job_type(job_dir_path) != job_type:
                continue
            seen.add(job_dir_path.name)
            dirs.append(job_dir_path)
    return dirs


def job_dir(job_id: str, *, job_root: Path | None = None) -> Path:
    if job_root is not None:
        return job_root / job_id
    for root in iter_job_roots():
        candidate = root / job_id
        if candidate.exists():
            return candidate
    return job_root_for_type(None) / job_id


def job_timestamp(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def notify_jobs_update() -> None:
    with state.JOBS_EVENT:
        state.JOBS_VERSION += 1
        state.JOBS_EVENT.notify_all()


def _without_none(values: dict[str, Any] | None) -> dict[str, Any]:
    return {k: v for k, v in (values or {}).items() if v is not None}


def _write_json_snapshot(
    path: Path, payload: dict[str, Any], *, job_id: str, snapshot_name: str
) -> None:
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError as exc:
        logger.warning(
            "Job JSON snapshot write failed job_id=%s snapshot=%s error=%s",
            job_id,
            snapshot_name,
            exc,
        )


def map_status_display(job_type: str, status: str, stage: str) -> tuple[str, str]:
    normalized_stage = str(stage or "").strip().lower()
    normalized_status = str(status or "").strip().lower()
    if normalized_status == "failed":
        return "failed", "失敗"
    if normalized_status == "cancel_requested":
        return "cancelled", "取消中"
    if normalized_status == "cancelled":
        return "cancelled", "已取消"
    if normalized_status == "completed":
        return "completed", "完成"
    if job_type == "doc_workspace":
        return DOC_STAGE_DISPLAY.get(normalized_stage or "queued", ("uploaded", "已上傳"))
    if job_type == "word_translate":
        return WORD_STAGE_DISPLAY.get(normalized_stage or "queued", ("uploaded", "已上傳"))
    return OCR_STAGE_DISPLAY.get(normalized_stage or "queued", ("uploaded", "已上傳"))


def create_job_state(
    job_dir_path: Path,
    *,
    job_type: str,
    stage: str,
    status: str = "queued",
    progress: float = 0.0,
    job_name: str | None = None,
    owner_work_id: str | None = None,
    target_lang: str | None = None,
    document_mode: str | None = None,
    payload: dict[str, Any] | None = None,
    meta: dict[str, Any] | None = None,
    started_at: float | None = None,
    completed_at: float | None = None,
) -> None:
    job_id = job_dir_path.name
    job_store.create_job(
        job_id=job_id,
        job_type=job_type,
        stage=stage,
        status=status,
        progress=progress,
        job_name=job_name,
        owner_work_id=owner_work_id,
        target_lang=target_lang,
        document_mode=document_mode,
        payload=payload,
        started_at=datetime_from_timestamp(started_at),
        completed_at=datetime_from_timestamp(completed_at),
    )
    snapshot = dict(meta or {})
    if snapshot:
        snapshot.setdefault("state_source", "sql")
        _write_json_snapshot(
            job_meta_path(job_dir_path),
            snapshot,
            job_id=job_id,
            snapshot_name="job_meta",
        )


def set_job_state(
    job_dir_path: Path,
    *,
    status: str,
    stage: str,
    progress: float | None = None,
    error_message: str | None = None,
    started_at: float | None = None,
    completed_at: float | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> None:
    job_id = job_dir_path.name
    meta = load_job_meta(job_dir_path) or {}
    record = job_store.get_job(job_id)
    job_type = str(
        meta.get("job_type") or getattr(record, "job_type", None) or get_job_type(job_dir_path)
    )
    legacy_stage_key = LEGACY_STAGE_KEY_BY_TYPE.get(job_type)
    if legacy_stage_key:
        meta[legacy_stage_key] = stage
    if progress is not None:
        meta["progress"] = float(progress)
    if error_message is not None:
        meta["error"] = error_message
    if started_at is not None and "processing_started_at" not in meta:
        meta["processing_started_at"] = started_at
    if completed_at is not None:
        meta["processing_completed_at"] = completed_at
    if extra_meta:
        meta.update(_without_none(extra_meta))
    if status == "completed":
        meta.pop("last_warning", None)
        meta.pop("last_warning_at", None)

    payload = job_store.deserialize_payload(record)
    if extra_meta:
        payload.update(_without_none(extra_meta))
    if status == "completed":
        payload.pop("last_warning", None)
        payload.pop("last_warning_at", None)

    store_updates: dict[str, Any] = {
        "job_type": job_type,
        "status": status,
        "stage": stage,
        "progress": (
            float(progress)
            if progress is not None
            else float(meta.get("progress") or getattr(record, "progress", 0.0) or 0.0)
        ),
        "error_message": error_message,
        "started_at": datetime_from_timestamp(started_at or meta.get("processing_started_at")),
        "completed_at": datetime_from_timestamp(completed_at or meta.get("processing_completed_at")),
        "job_name": normalize_job_name(meta.get("job_name"))
        or normalize_job_name(getattr(record, "job_name", None)),
        "target_lang": str(
            meta.get("target_lang") or getattr(record, "target_lang", "") or ""
        )
        or None,
        "document_mode": str(
            meta.get("document_mode") or getattr(record, "document_mode", "") or ""
        )
        or None,
    }
    if extra_meta or status == "completed":
        store_updates["payload_json"] = json.dumps(payload, ensure_ascii=False)

    job_store.update_job(job_id, **store_updates)
    _write_json_snapshot(
        job_meta_path(job_dir_path),
        meta,
        job_id=job_id,
        snapshot_name="job_meta",
    )
    notify_jobs_update()


def fail_job(
    job_dir_path: Path,
    *,
    stage: str = "failed",
    error_message: str,
    completed_at: float | None = None,
    progress: float | None = None,
    extra_meta: dict[str, Any] | None = None,
) -> float:
    now_ts = completed_at if completed_at is not None else time.time()
    merged_meta = dict(extra_meta or {})
    merged_meta.setdefault("failed_at", now_ts)
    set_job_state(
        job_dir_path,
        status="failed",
        stage=stage,
        progress=progress,
        error_message=error_message,
        completed_at=now_ts,
        extra_meta=merged_meta,
    )
    return now_ts


def _safe_update_job_store(job_id: str, **updates: Any) -> None:
    try:
        job_store.update_job(job_id, **updates)
    except Exception:
        return


def queue_batch_translation(
    job_dir_path: Path,
    *,
    model: Any = None,
    target_lang: Any = None,
    translate_mode: Any = None,
    extra_meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    job_id = job_dir_path.name
    record = job_store.get_job(job_id)
    payload = job_store.deserialize_payload(record)
    normalized_translate_mode = normalize_translate_mode(
        translate_mode or payload.get("translate_mode")
    )
    payload["resume_translate_only"] = True
    payload["translate_mode"] = normalized_translate_mode
    if extra_meta:
        payload.update(_without_none(extra_meta))

    job_store.update_job(
        job_id,
        status="queued",
        stage="translate",
        payload_json=json.dumps(payload, ensure_ascii=False),
        error_message=None,
        completed_at=None,
    )

    meta = load_job_meta(job_dir_path) or {}
    meta.pop("error", None)
    meta.pop("processing_completed_at", None)
    meta["translate_mode"] = normalized_translate_mode
    if extra_meta:
        meta.update(_without_none(extra_meta))
    batch_status_payload = _batch_status_payload(
        "queued",
        job_id=job_id,
        model=model,
        target_lang=target_lang,
        translate_mode=normalized_translate_mode,
    )
    _write_json_snapshot(
        job_meta_path(job_dir_path),
        meta,
        job_id=job_id,
        snapshot_name="job_meta",
    )
    _write_json_snapshot(
        batch_status_path(job_dir_path),
        batch_status_payload,
        job_id=job_id,
        snapshot_name="batch_status",
    )
    notify_jobs_update()
    return {"status": "queued"}


def _job_store_status_for_doc_stage(doc_stage: str) -> str:
    if doc_stage == "failed":
        return "failed"
    if doc_stage == "completed":
        return "completed"
    return "running"


def _job_store_status_for_word_stage(word_stage: str) -> str:
    if word_stage == "failed":
        return "failed"
    if word_stage == "cancelled":
        return "cancelled"
    if word_stage == "completed":
        return "completed"
    if word_stage == "uploaded":
        return "queued"
    return "running"


def _job_store_status_for_ocr(job_dir_path: Path, meta: dict[str, Any] | None = None) -> tuple[str, str]:
    job_id = job_dir_path.name
    batch_config = load_batch_config(job_dir_path)
    batch_state = str((load_batch_status(job_dir_path) or {}).get("status") or "").lower()
    debug_ready = (job_dir_path / "overlay_debug.pdf").exists()
    edited_ready = (job_dir_path / "edited.pdf").exists()
    meta = meta or load_job_meta(job_dir_path) or {}
    if batch_state in {"failed", "canceled", "cancelled"}:
        return "failed", "translate"
    if edited_ready and (batch_state == "completed" or not batch_config):
        return "completed", "render"
    if batch_state in {"running", "validating", "finalizing", "in_progress"}:
        return "running", "translate"
    if debug_ready:
        return "running" if batch_config else "completed", "ocr"
    if meta.get("ocr_completed_at") and not batch_config:
        return "completed", "ocr"
    return "running", "ocr"


def infer_job_store_status(job_dir_path: Path, meta: dict[str, Any]) -> tuple[str, str]:
    job_type = str(meta.get("job_type") or get_job_type(job_dir_path))
    if job_type == "doc_workspace":
        stage = str(meta.get("doc_stage") or "uploaded").lower()
        return _job_store_status_for_doc_stage(stage), stage
    if job_type == "word_translate":
        stage = str(meta.get("word_stage") or "uploaded").lower()
        return _job_store_status_for_word_stage(stage), stage
    return _job_store_status_for_ocr(job_dir_path, meta)


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _path_timestamp(path: Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except FileNotFoundError:
        return 0.0


def _collect_legacy_relevant_paths(job_dir_path: Path, job_type: str, meta: dict[str, Any]) -> list[Path]:
    paths = [job_dir_path, job_meta_path(job_dir_path)]
    if job_type in {"ocr_overlay", "template_source"}:
        paths.extend(
            [
                job_dir_path / f"{job_dir_path.name}.pdf",
                job_dir_path / "source.pdf",
                job_dir_path / "overlay_debug.pdf",
                job_dir_path / "edited.pdf",
                batch_config_path(job_dir_path),
                batch_status_path(job_dir_path),
            ]
        )
    elif job_type == "doc_workspace":
        paths.extend(
            [
                job_dir_path / "source.pdf",
                job_dir_path / "structure" / "doc.md",
                job_dir_path / "structure" / "doc.html",
                job_dir_path / "translated" / "doc.translated.html",
                job_dir_path / "output" / "output.docx",
                doc_status_path(job_dir_path),
            ]
        )
    elif job_type == "word_translate":
        source_name = str(meta.get("source_filename") or "").strip()
        if source_name:
            paths.append(job_dir_path / source_name)
        paths.append(job_dir_path / "output" / "output.docx")
    return paths


def _infer_legacy_timestamps(
    job_dir_path: Path, job_type: str, meta: dict[str, Any], status: str
) -> tuple[Any, Any, Any]:
    paths = _collect_legacy_relevant_paths(job_dir_path, job_type, meta)
    existing_ts = [_path_timestamp(path) for path in paths if path.exists()]
    fallback_created = existing_ts[0] if existing_ts else 0.0
    created_ts = 0.0

    if job_type in {"ocr_overlay", "template_source"}:
        created_ts = _path_timestamp(job_dir_path / f"{job_dir_path.name}.pdf") or _path_timestamp(
            job_dir_path / "source.pdf"
        )
    elif job_type == "doc_workspace":
        created_ts = _path_timestamp(job_dir_path / "source.pdf")
    elif job_type == "word_translate":
        source_name = str(meta.get("source_filename") or "").strip()
        if source_name:
            created_ts = _path_timestamp(job_dir_path / source_name)

    if not created_ts:
        created_ts = fallback_created or _path_timestamp(job_dir_path)

    updated_ts = max(existing_ts) if existing_ts else created_ts
    completed_ts = _safe_float(meta.get("processing_completed_at"), 0.0)
    if not completed_ts and status in {"completed", "failed", "cancelled"}:
        completed_ts = updated_ts

    return (
        datetime_from_timestamp(created_ts),
        datetime_from_timestamp(updated_ts),
        datetime_from_timestamp(completed_ts),
    )


def _build_legacy_payload(job_dir_path: Path, job_type: str, meta: dict[str, Any]) -> dict[str, Any] | None:
    if job_type in {"ocr_overlay", "template_source"}:
        batch_config = load_batch_config(job_dir_path) or {}
        payload = {
            "dpi": int(meta.get("dpi") or 200),
            "start_page": int(meta.get("start_page") or 1),
            "end_page": meta.get("end_page"),
            "translate_source_lang": str(
                batch_config.get("source_lang") or meta.get("source_lang") or "auto"
            ),
            "translate_target_lang": str(
                batch_config.get("target_lang") or meta.get("target_lang") or "en"
            ),
            "translate_model": str(batch_config.get("model") or meta.get("translate_model") or ""),
            "translate_mode": normalize_translate_mode(
                batch_config.get("translate_mode") or meta.get("translate_mode")
            ),
            "keep_lang": str(meta.get("keep_lang") or "all"),
            "enable_translate": bool(batch_config),
            "document_mode": normalize_document_mode(
                batch_config.get("document_mode") or meta.get("document_mode")
            ),
            "creator_name": str(meta.get("creator_name") or "").strip(),
            "owner_work_id": str(meta.get("owner_work_id") or "").strip(),
        }
        if not payload["translate_model"]:
            payload.pop("translate_model")
        return payload

    if job_type == "doc_workspace":
        return {
            "source_lang": str(meta.get("source_lang") or "auto"),
            "target_lang": str(meta.get("target_lang") or "en"),
            "creator_name": str(meta.get("creator_name") or "").strip(),
            "owner_work_id": str(meta.get("owner_work_id") or "").strip(),
        }

    if job_type == "word_translate":
        retain_terms = meta.get("retain_terms")
        if not isinstance(retain_terms, list):
            retain_terms = []
        return {
            "source_lang": str(meta.get("source_lang") or "auto"),
            "target_lang": str(meta.get("target_lang") or "en"),
            "retain_terms": [str(item) for item in retain_terms if str(item).strip()],
            "creator_name": str(meta.get("creator_name") or "").strip(),
            "owner_work_id": str(meta.get("owner_work_id") or "").strip(),
        }

    return None


def _collect_legacy_artifacts(job_dir_path: Path, job_type: str, meta: dict[str, Any]) -> dict[str, str]:
    artifacts: dict[str, str] = {}

    def add_if_exists(artifact_type: str, rel_path: str) -> None:
        if (job_dir_path / rel_path).exists():
            artifacts[artifact_type] = rel_path

    if job_type in {"ocr_overlay", "template_source"}:
        source_name = str(meta.get("source_filename") or "").strip()
        if source_name:
            add_if_exists("source_pdf", source_name)
        add_if_exists("source_pdf", "source.pdf")
        add_if_exists("source_pdf", f"{job_dir_path.name}.pdf")
        add_if_exists("debug_pdf", "overlay_debug.pdf")
        add_if_exists("edited_pdf", "edited.pdf")
    elif job_type == "doc_workspace":
        add_if_exists("source_pdf", "source.pdf")
        add_if_exists("structure_md", "structure/doc.md")
        add_if_exists("structure_html", "structure/doc.html")
        add_if_exists("translated_html", "translated/doc.translated.html")
        add_if_exists("docx", "output/output.docx")
    elif job_type == "word_translate":
        source_name = str(meta.get("source_filename") or "").strip()
        if source_name:
            add_if_exists("source_docx", source_name)
        add_if_exists("docx", "output/output.docx")

    return artifacts


def _sql_first_snapshot(meta: dict[str, Any]) -> bool:
    return str(meta.get("state_source") or "").strip().lower() == "sql"


def _missing_sql_field_updates(record: Any, job_dir_path: Path, job_type: str, meta: dict[str, Any]) -> dict[str, Any]:
    batch_config = load_batch_config(job_dir_path) or {}
    legacy_payload = _build_legacy_payload(job_dir_path, job_type, meta) or {}
    updates: dict[str, Any] = {}

    if not normalize_job_name(getattr(record, "job_name", None)):
        job_name = normalize_job_name(meta.get("job_name"))
        if job_name:
            updates["job_name"] = job_name
    if not str(getattr(record, "owner_work_id", "") or "").strip():
        owner = str(meta.get("owner_work_id") or legacy_payload.get("owner_work_id") or "").strip()
        if owner:
            updates["owner_work_id"] = owner
    if job_type in {"ocr_overlay", "template_source"} and not str(getattr(record, "target_lang", "") or "").strip():
        target_lang = str(batch_config.get("target_lang") or meta.get("target_lang") or "").strip()
        if target_lang:
            updates["target_lang"] = target_lang
    if job_type in {"ocr_overlay", "template_source"} and not str(getattr(record, "document_mode", "") or "").strip():
        raw_document_mode = batch_config.get("document_mode") or meta.get("document_mode")
        if raw_document_mode:
            updates["document_mode"] = normalize_document_mode(raw_document_mode)
    if not str(getattr(record, "stage", "") or "").strip():
        _status, stage = infer_job_store_status(job_dir_path, meta)
        updates["stage"] = stage
    return updates


def sync_legacy_jobs_from_disk(*, dry_run: bool = False) -> dict[str, Any]:
    result: dict[str, Any] = {
        "scanned": 0,
        "created": 0,
        "updated": 0,
        "would_create": 0,
        "skipped": 0,
        "errors": [],
        "details": [],
    }
    for root in iter_job_roots():
        if not root.exists():
            continue
        for job_dir_path in sorted(root.iterdir()):
            if not job_dir_path.is_dir() or not safe_job_id(job_dir_path.name):
                continue
            result["scanned"] += 1
            try:
                detail = _sync_legacy_job_from_disk(job_dir_path, dry_run=dry_run)
            except Exception as exc:
                error_detail = {"job_id": job_dir_path.name, "action": "error", "reason": str(exc)}
                result["errors"].append(error_detail)
                result["details"].append(error_detail)
                continue
            result[detail["action"]] += 1
            result["details"].append(detail)
    return result


def _sync_legacy_job_from_disk(job_dir_path: Path, *, dry_run: bool = False) -> dict[str, Any]:
    job_id = job_dir_path.name
    meta = load_job_meta(job_dir_path) or {}
    job_type = str(meta.get("job_type") or get_job_type(job_dir_path))
    existing = job_store.get_job(job_id)
    if existing is not None:
        updates = _missing_sql_field_updates(existing, job_dir_path, job_type, meta)
        if dry_run and updates:
            return {"job_id": job_id, "action": "updated", "reason": "would_fill_missing_sql_fields"}
        if updates:
            job_store.update_job(job_id, **updates)
            return {"job_id": job_id, "action": "updated", "reason": "filled_missing_sql_fields"}
        return {"job_id": job_id, "action": "skipped", "reason": "sql_exists_complete"}

    if _sql_first_snapshot(meta):
        return {"job_id": job_id, "action": "skipped", "reason": "sql_first_snapshot_missing_sql"}

    status, stage = infer_job_store_status(job_dir_path, meta)
    if dry_run:
        return {"job_id": job_id, "action": "would_create", "reason": "missing_sql_record"}

    batch_config = load_batch_config(job_dir_path) or {}
    batch_status = load_batch_status(job_dir_path) or {}
    created_at, updated_at, completed_at = _infer_legacy_timestamps(
        job_dir_path, job_type, meta, status
    )
    started_at = datetime_from_timestamp(_safe_float(meta.get("processing_started_at"), 0.0))
    target_lang = str(batch_config.get("target_lang") or meta.get("target_lang") or "").strip() or None
    document_mode = (
        normalize_document_mode(batch_config.get("document_mode") or meta.get("document_mode"))
        if job_type in {"ocr_overlay", "template_source"}
        else None
    )
    error_message = str(meta.get("error") or batch_status.get("error") or "").strip() or None
    job_store.create_job(
        job_id=job_id,
        job_type=job_type,
        stage=stage,
        status=status,
        progress=_safe_float(meta.get("progress"), 100.0 if status == "completed" else 0.0),
        job_name=normalize_job_name(meta.get("job_name")),
        owner_work_id=str(meta.get("owner_work_id") or "").strip() or None,
        target_lang=target_lang,
        document_mode=document_mode,
        payload=_build_legacy_payload(job_dir_path, job_type, meta),
        error_message=error_message,
        started_at=started_at,
        completed_at=completed_at,
        created_at=created_at,
        updated_at=updated_at,
    )
    job_store.replace_artifacts(job_id, _collect_legacy_artifacts(job_dir_path, job_type, meta))
    return {"job_id": job_id, "action": "created", "reason": "missing_sql_record"}


def _legacy_artifact_url(job_id: str, artifacts: dict[str, str], artifact_type: str) -> str | None:
    file_path = artifacts.get(artifact_type)
    if not file_path:
        return None
    return url_for("jobs.job_file", job_id=job_id, filename=file_path)


def _build_legacy_job_list_item(job_dir_path: Path) -> dict[str, Any] | None:
    meta = load_job_meta(job_dir_path) or {}
    job_id = job_dir_path.name
    job_type = str(meta.get("job_type") or get_job_type(job_dir_path))
    status, stage = infer_job_store_status(job_dir_path, meta)
    created_at, updated_at, completed_at = _infer_legacy_timestamps(
        job_dir_path, job_type, meta, status
    )
    created_ts = timestamp_from_datetime(created_at) or job_timestamp(job_dir_path)
    updated_ts = timestamp_from_datetime(updated_at) or created_ts
    started_ts = (
        timestamp_from_datetime(
            datetime_from_timestamp(_safe_float(meta.get("processing_started_at"), 0.0))
        )
        or created_ts
    )
    completed_ts = timestamp_from_datetime(completed_at)
    if completed_ts is not None:
        duration_seconds = max(0.0, completed_ts - started_ts)
    elif status == "queued":
        duration_seconds = 0.0
    else:
        duration_seconds = max(0.0, time.time() - started_ts)

    job_name = normalize_job_name(meta.get("job_name"))
    creator_name = str(meta.get("creator_name") or "").strip() or None
    owner_work_id = str(meta.get("owner_work_id") or "").strip() or None
    status_code, status_label = map_status_display(job_type, status, stage)
    artifacts = _collect_legacy_artifacts(job_dir_path, job_type, meta)
    common = {
        "job_id": job_id,
        "job_type": job_type,
        "legacy_state": True,
        "job_status": status,
        "job_stage": stage,
        "created_at": created_ts,
        "updated_at": updated_ts,
        "duration_seconds": duration_seconds,
        "ocr_duration_seconds": None,
        "translate_duration_seconds": None,
        "status_code": status_code,
        "status_label": status_label,
        "status": status_label,
        "job_name": job_name,
        "creator_name": creator_name,
        "owner_work_id": owner_work_id,
        "active_editors": [],
        "last_warning": sanitize_job_message(meta.get("last_warning")),
        "last_warning_at": meta.get("last_warning_at"),
        "recent_warnings": [],
        "error": sanitize_job_message(meta.get("error")),
    }

    if job_type == "doc_workspace":
        return {
            **common,
            "download_name": build_docx_name(job_id, job_name),
            "structure_download_name": build_doc_markdown_name(job_id, job_name, translated=False),
            "source_pdf_url": _legacy_artifact_url(job_id, artifacts, "source_pdf"),
            "structure_md_url": _legacy_artifact_url(job_id, artifacts, "structure_md"),
            "structure_html_url": _legacy_artifact_url(job_id, artifacts, "structure_html"),
            "translated_html_url": _legacy_artifact_url(job_id, artifacts, "translated_html"),
            "docx_url": _legacy_artifact_url(job_id, artifacts, "docx"),
        }

    if job_type == "word_translate":
        return {
            **common,
            "progress": _safe_float(meta.get("progress"), 0.0),
            "avg_quality": _safe_float(meta.get("avg_quality"), 0.0),
            "target_lang": meta.get("target_lang"),
            "download_name": build_docx_name(job_id, job_name),
            "source_docx_url": _legacy_artifact_url(job_id, artifacts, "source_docx"),
            "docx_url": _legacy_artifact_url(job_id, artifacts, "docx"),
        }

    batch_status = load_batch_status(job_dir_path) or {}
    return {
        **common,
        "template_source": job_type == "template_source",
        "document_mode": normalize_document_mode(meta.get("document_mode")),
        "translate_mode": normalize_translate_mode(meta.get("translate_mode")),
        "error": sanitize_job_message(meta.get("error") or batch_status.get("error")),
        "download_name": build_download_name(job_id, job_name),
        "editor_url": url_for("editor.editor", job_id=job_id),
        "debug_pdf_url": _legacy_artifact_url(job_id, artifacts, "debug_pdf"),
        "edited_pdf_url": _legacy_artifact_url(job_id, artifacts, "edited_pdf"),
    }


def build_jobs_list(
    job_type: str | None = None,
    owner_work_id: str | None = None,
    include_all: bool = False,
    include_active_editors: bool | None = None,
) -> list[dict[str, Any]]:
    jobs = []
    normalized_owner = " ".join(str(owner_work_id or "").split()).strip()
    if not include_all and not normalized_owner:
        return jobs
    records = job_store.list_jobs(job_type)
    record_ids = [record.job_id for record in records]
    record_id_set = set(record_ids)
    artifacts_by_job_id = job_store.list_artifacts(record_ids)
    warning_events_by_job_id = job_store.list_recent_events(record_ids, event_type="warning", limit_per_job=3)
    should_include_active_editors = include_all if include_active_editors is None else bool(include_active_editors)
    active_editors_by_job_id = (
        job_store.list_active_editor_presence([record.job_id for record in records])
        if should_include_active_editors
        else {}
    )

    def _artifact_url(job_id: str, artifacts: dict[str, Any], artifact_type: str) -> str | None:
        artifact = artifacts.get(artifact_type)
        if artifact is None:
            return None
        file_path = str(getattr(artifact, "file_path", "") or "").replace("\\", "/").lstrip("/")
        if not file_path:
            return None
        return url_for("jobs.job_file", job_id=job_id, filename=file_path)

    for record in records:
        current_job_type = record.job_type
        job_id = record.job_id
        payload = job_store.deserialize_payload(record)
        disk_meta = load_job_meta(job_dir(job_id)) or {}
        recent_warnings = _serialize_warning_events(warning_events_by_job_id.get(job_id, []))
        artifacts = artifacts_by_job_id.get(job_id, {})
        active_editors = active_editors_by_job_id.get(job_id, [])
        record_owner_work_id = str(
            record.owner_work_id or payload.get("owner_work_id") or disk_meta.get("owner_work_id") or ""
        ).strip()
        if not include_all and record_owner_work_id != normalized_owner:
            continue
        is_template_source = current_job_type == "template_source"

        created_at = timestamp_from_datetime(record.created_at) or 0.0
        updated_at = timestamp_from_datetime(record.updated_at) or created_at
        started_at = timestamp_from_datetime(record.started_at) or created_at
        completed_at = timestamp_from_datetime(record.completed_at)
        if completed_at is not None:
            duration_seconds = max(0.0, completed_at - started_at)
        elif record.status in {"queued"}:
            duration_seconds = 0.0
        else:
            duration_seconds = max(0.0, time.time() - started_at)
        job_name = normalize_job_name(record.job_name) or normalize_job_name(disk_meta.get("job_name"))
        creator_name = str(payload.get("creator_name") or disk_meta.get("creator_name") or "").strip() or None

        if current_job_type == "doc_workspace":
            status_code, status_label = map_status_display(
                current_job_type, record.status, record.stage or "queued"
            )
            doc_status = load_doc_status(job_dir(job_id)) or {}
            error_message = _job_error_message(record, payload.get("error"), doc_status.get("error"))
            jobs.append(
                {
                    "job_id": job_id,
                    "job_type": current_job_type,
                    "legacy_state": False,
                    "job_status": record.status,
                    "job_stage": record.stage,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "duration_seconds": duration_seconds,
                    "ocr_duration_seconds": None,
                    "translate_duration_seconds": None,
                    "status_code": status_code,
                    "status_label": status_label,
                    "status": status_label,
                    "job_name": job_name,
                    "creator_name": creator_name,
                    "owner_work_id": record_owner_work_id or None,
                    "active_editors": active_editors,
                    "last_warning": sanitize_job_message(payload.get("last_warning")),
                    "last_warning_at": payload.get("last_warning_at"),
                    "recent_warnings": recent_warnings,
                    "error": error_message,
                    "download_name": build_docx_name(job_id, job_name),
                    "structure_download_name": build_doc_markdown_name(job_id, job_name, translated=False),
                    "source_pdf_url": _artifact_url(job_id, artifacts, "source_pdf"),
                    "structure_md_url": _artifact_url(job_id, artifacts, "structure_md"),
                    "structure_html_url": _artifact_url(job_id, artifacts, "structure_html"),
                    "translated_html_url": _artifact_url(job_id, artifacts, "translated_html"),
                    "docx_url": _artifact_url(job_id, artifacts, "docx"),
                }
            )
            continue

        if current_job_type == "word_translate":
            status_code, status_label = map_status_display(
                current_job_type, record.status, record.stage or "queued"
            )
            jobs.append(
                {
                    "job_id": job_id,
                    "job_type": current_job_type,
                    "legacy_state": False,
                    "job_status": record.status,
                    "job_stage": record.stage,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "duration_seconds": duration_seconds,
                    "ocr_duration_seconds": None,
                    "translate_duration_seconds": None,
                    "status_code": status_code,
                    "status_label": status_label,
                    "status": status_label,
                    "job_name": job_name,
                    "creator_name": creator_name,
                    "owner_work_id": record_owner_work_id or None,
                    "active_editors": active_editors,
                    "progress": float(record.progress or 0.0),
                    "avg_quality": float(payload.get("avg_quality") or 0.0),
                    "last_warning": sanitize_job_message(payload.get("last_warning")),
                    "last_warning_at": payload.get("last_warning_at"),
                    "recent_warnings": recent_warnings,
                    "error": _job_error_message(record, payload.get("error")),
                    "target_lang": record.target_lang or payload.get("target_lang"),
                    "download_name": build_docx_name(job_id, job_name),
                    "source_docx_url": _artifact_url(job_id, artifacts, "source_docx"),
                    "docx_url": _artifact_url(job_id, artifacts, "docx"),
                }
            )
            continue

        ocr_started_at = payload.get("ocr_started_at") or created_at
        ocr_completed_at = payload.get("ocr_completed_at")
        if isinstance(ocr_completed_at, (int, float)) and isinstance(ocr_started_at, (int, float)):
            ocr_duration_seconds = max(0.0, float(ocr_completed_at) - float(ocr_started_at))
        else:
            ocr_duration_seconds = None
        translate_started_at = payload.get("translate_started_at")
        translate_completed_at = payload.get("translate_completed_at")
        if isinstance(translate_completed_at, (int, float)) and isinstance(translate_started_at, (int, float)):
            translate_duration_seconds = max(0.0, float(translate_completed_at) - float(translate_started_at))
        else:
            translate_duration_seconds = None

        download_name = build_download_name(job_id, job_name)
        status_code, status_label = map_status_display(
            current_job_type, record.status, record.stage or "queued"
        )
        batch_status = build_batch_status(job_dir(job_id))
        error_message = _job_error_message(record, payload.get("error"), batch_status.get("error"))

        jobs.append(
            {
                "job_id": job_id,
                "job_type": current_job_type,
                "legacy_state": False,
                "job_status": record.status,
                "job_stage": record.stage,
                "created_at": created_at,
                "updated_at": updated_at,
                "duration_seconds": duration_seconds,
                "ocr_duration_seconds": ocr_duration_seconds,
                "translate_duration_seconds": translate_duration_seconds,
                "status_code": status_code,
                "status_label": status_label,
                "status": status_label,
                "job_name": job_name,
                "template_source": is_template_source,
                "creator_name": creator_name,
                "owner_work_id": record_owner_work_id or None,
                "active_editors": active_editors,
                "document_mode": normalize_document_mode(
                    record.document_mode or payload.get("document_mode")
                ),
                "translate_mode": normalize_translate_mode(
                    payload.get("translate_mode")
                ),
                "last_warning": sanitize_job_message(payload.get("last_warning")),
                "last_warning_at": payload.get("last_warning_at"),
                "recent_warnings": recent_warnings,
                "error": error_message,
                "download_name": download_name,
                "editor_url": url_for("editor.editor", job_id=job_id),
                "debug_pdf_url": _artifact_url(job_id, artifacts, "debug_pdf"),
                "edited_pdf_url": _artifact_url(job_id, artifacts, "edited_pdf"),
                }
            )
    for job_dir_path in iter_job_dirs(job_type, include_templates=job_type == "template_source"):
        if job_dir_path.name in record_id_set:
            continue
        legacy_meta = load_job_meta(job_dir_path) or {}
        if _sql_first_snapshot(legacy_meta):
            continue
        legacy_item = _build_legacy_job_list_item(job_dir_path)
        if legacy_item is None:
            continue
        legacy_owner = str(legacy_item.get("owner_work_id") or "").strip()
        if not include_all and legacy_owner != normalized_owner:
            continue
        jobs.append(legacy_item)

    jobs.sort(key=lambda item: item["updated_at"], reverse=True)
    return jobs


def get_job_owner_work_id(job_id: str) -> str:
    if not safe_job_id(job_id):
        return ""
    record = job_store.get_job(job_id)
    if record is not None:
        owner = str(record.owner_work_id or "").strip()
        if owner:
            return owner
    meta = load_job_meta(job_dir(job_id)) or {}
    return str(meta.get("owner_work_id") or "").strip()


def list_accessible_job_ids(
    *,
    job_type: str | None = None,
    owner_work_id: str | None = None,
    include_all: bool = False,
) -> set[str]:
    normalized_owner = " ".join(str(owner_work_id or "").split()).strip()
    if not include_all and not normalized_owner:
        return set()
    accessible: set[str] = set()
    for record in job_store.list_jobs(job_type):
        job_id = str(record.job_id or "").strip()
        if not safe_job_id(job_id):
            continue
        if include_all:
            accessible.add(job_id)
            continue
        owner = str(record.owner_work_id or "").strip() or get_job_owner_work_id(job_id)
        if owner == normalized_owner:
            accessible.add(job_id)

    for job_dir_path in iter_job_dirs(job_type, include_templates=job_type == "template_source"):
        job_id = job_dir_path.name
        if job_id in accessible or job_store.get_job(job_id) is not None:
            continue
        if include_all:
            accessible.add(job_id)
            continue
        meta = load_job_meta(job_dir_path) or {}
        if _sql_first_snapshot(meta):
            continue
        owner = str(meta.get("owner_work_id") or "").strip()
        if owner == normalized_owner:
            accessible.add(job_id)
    return accessible


def batch_status_path(job_dir_path: Path) -> Path:
    return job_dir_path / state.BATCH_STATUS_NAME


def batch_config_path(job_dir_path: Path) -> Path:
    return job_dir_path / "batch_config.json"


def batch_alias_path(job_dir_path: Path) -> Path:
    return job_dir_path / state.BATCH_ALIAS_NAME


def batch_prefill_path(job_dir_path: Path) -> Path:
    return job_dir_path / state.BATCH_PREFILL_NAME


def merge_notices_path(job_dir_path: Path) -> Path:
    return job_dir_path / "merge_notices.json"


def job_meta_path(job_dir_path: Path) -> Path:
    return job_dir_path / "job_meta.json"


def write_job_meta(job_dir_path: Path, meta: dict[str, Any]) -> None:
    job_meta_path(job_dir_path).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    job_id = job_dir_path.name
    if not safe_job_id(job_id):
        return
    job_type = str(meta.get("job_type") or get_job_type(job_dir_path))
    progress = float(meta.get("progress") or 0.0)
    _safe_update_job_store(
        job_id,
        job_type=job_type,
        progress=progress,
        job_name=normalize_job_name(meta.get("job_name")),
        target_lang=str(meta.get("target_lang") or "") or None,
        document_mode=str(meta.get("document_mode") or "") or None,
        owner_work_id=str(meta.get("owner_work_id") or "") or None,
        started_at=datetime_from_timestamp(meta.get("processing_started_at")),
        completed_at=datetime_from_timestamp(meta.get("processing_completed_at")),
    )


def load_job_meta(job_dir_path: Path) -> dict[str, Any] | None:
    path = job_meta_path(job_dir_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def update_job_meta(job_dir_path: Path, **updates: Any) -> None:
    meta = load_job_meta(job_dir_path) or {}
    meta.update({k: v for k, v in updates.items() if v is not None})
    write_job_meta(job_dir_path, meta)


def write_batch_config(job_dir_path: Path, config: dict[str, Any]) -> None:
    batch_config_path(job_dir_path).write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_batch_config(job_dir_path: Path) -> dict[str, Any] | None:
    path = batch_config_path(job_dir_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _batch_stage_for_status(status: str) -> str:
    normalized = status.lower()
    if normalized == "completed":
        return "completed"
    return "translate"


def _batch_status_payload(status: str, **meta: Any) -> dict[str, Any]:
    return {
        "status": status,
        "updated_at": time.time(),
        **meta,
    }


def write_batch_status(job_dir_path: Path, status: str, **meta: Any) -> None:
    job_id = job_dir_path.name
    payload = _batch_status_payload(status, **meta)
    normalized = status.lower()
    job_store.update_job(
        job_id,
        status=DB_STATUS_BY_BATCH.get(normalized, "running"),
        stage=_batch_stage_for_status(normalized),
        error_message=str(meta.get("error") or "") or None,
    )
    _write_json_snapshot(
        batch_status_path(job_dir_path),
        payload,
        job_id=job_id,
        snapshot_name="batch_status",
    )
    notify_jobs_update()


def load_batch_status(job_dir_path: Path) -> dict[str, Any] | None:
    path = batch_status_path(job_dir_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def _batch_status_from_record(record: Any) -> str:
    record_status = str(getattr(record, "status", "") or "").lower()
    record_stage = str(getattr(record, "stage", "") or "").lower()
    if record_stage == "translate":
        return record_status or "not_started"
    if record_status in {"completed", "failed", "cancelled", "cancel_requested"}:
        return record_status
    return "not_started"


def build_batch_status(job_dir_path: Path) -> dict[str, Any]:
    job_id = job_dir_path.name
    status = dict(load_batch_status(job_dir_path) or {"status": "not_started"})
    record = job_store.get_job(job_id)
    if record is None:
        return status
    status["status"] = _batch_status_from_record(record)
    status["job_status"] = record.status
    status["job_stage"] = record.stage
    status["progress"] = record.progress
    if record.error_message:
        status["error"] = sanitize_job_message(record.error_message)
    elif status["status"] in {"completed", "queued", "not_started"}:
        status.pop("error", None)
    return status


def batch_translation_active(job_dir_path: Path) -> bool:
    record = job_store.get_job(job_dir_path.name)
    if record is not None:
        return record.status in {"running", "queued"} and record.stage == "translate"
    status = load_batch_status(job_dir_path)
    return bool(status and status.get("status") in {"running", "queued"})


def doc_status_path(job_dir_path: Path) -> Path:
    return job_dir_path / state.DOC_STATUS_NAME


def load_doc_status(job_dir_path: Path) -> dict[str, Any] | None:
    path = doc_status_path(job_dir_path)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def write_batch_alias_map(job_dir_path: Path, alias_map: dict[str, str]) -> None:
    batch_alias_path(job_dir_path).write_text(
        json.dumps(alias_map, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_batch_alias_map(job_dir_path: Path) -> dict[str, str]:
    path = batch_alias_path(job_dir_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    cleaned: dict[str, str] = {}
    for k, v in data.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        cleaned[k] = v
    return cleaned


def write_batch_prefill_map(job_dir_path: Path, prefill: dict[str, str]) -> None:
    batch_prefill_path(job_dir_path).write_text(
        json.dumps(prefill, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_batch_prefill_map(job_dir_path: Path) -> dict[str, str]:
    path = batch_prefill_path(job_dir_path)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    cleaned: dict[str, str] = {}
    for k, v in data.items():
        if not isinstance(k, str) or not isinstance(v, str):
            continue
        cleaned[k] = v
    return cleaned


def write_merge_notices(job_dir_path: Path, notices: list[dict[str, Any]]) -> None:
    merge_notices_path(job_dir_path).write_text(
        json.dumps(notices, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_merge_notices(job_dir_path: Path) -> list[dict[str, Any]]:
    path = merge_notices_path(job_dir_path)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        notice_id = str(item.get("notice_id") or "").strip()
        if not notice_id:
            continue
        item = dict(item)
        item["notice_id"] = notice_id
        item["status"] = str(item.get("status") or "pending").strip().lower() or "pending"
        cleaned.append(item)
    return cleaned


def upsert_merge_notice(job_dir_path: Path, notice: dict[str, Any]) -> dict[str, Any] | None:
    if not isinstance(notice, dict):
        return None
    notice_id = str(notice.get("notice_id") or "").strip()
    if not notice_id:
        return None
    notices = load_merge_notices(job_dir_path)
    payload = dict(notice)
    payload["notice_id"] = notice_id
    payload["status"] = str(payload.get("status") or "pending").strip().lower() or "pending"
    payload["updated_at"] = time.time()
    for idx, existing in enumerate(notices):
        if str(existing.get("notice_id") or "") != notice_id:
            continue
        preserved_status = str(existing.get("status") or "pending").strip().lower() or "pending"
        payload["status"] = preserved_status if preserved_status != "pending" else payload["status"]
        payload["created_at"] = existing.get("created_at") or payload.get("created_at") or payload["updated_at"]
        notices[idx] = payload
        write_merge_notices(job_dir_path, notices)
        return payload
    payload["created_at"] = payload.get("created_at") or payload["updated_at"]
    notices.append(payload)
    write_merge_notices(job_dir_path, notices)
    return payload


def update_merge_notice_status(job_dir_path: Path, notice_id: str, status: str) -> dict[str, Any] | None:
    normalized_notice_id = str(notice_id or "").strip()
    normalized_status = str(status or "").strip().lower()
    if not normalized_notice_id or normalized_status not in {"pending", "accepted", "rejected"}:
        return None
    notices = load_merge_notices(job_dir_path)
    for idx, notice in enumerate(notices):
        if str(notice.get("notice_id") or "") != normalized_notice_id:
            continue
        updated = dict(notice)
        updated["status"] = normalized_status
        updated["updated_at"] = time.time()
        notices[idx] = updated
        write_merge_notices(job_dir_path, notices)
        return updated
    return None


def load_edits_map(job_dir_path: Path) -> dict[int, list[dict[str, Any]]]:
    edits_path = job_dir_path / "edits.json"
    if not edits_path.exists():
        return {}
    data = json.loads(edits_path.read_text(encoding="utf-8"))
    pages: dict[int, list[dict[str, Any]]] = {}
    for page in data.get("pages", []):
        if not isinstance(page, dict):
            continue
        page_idx = int(page.get("page_index_0based", 0))
        boxes = page.get("boxes", [])
        if not isinstance(boxes, list):
            boxes = []
        deduped: list[dict[str, Any]] = []
        seen: set[tuple[Any, ...]] = set()
        for box in boxes:
            if not isinstance(box, dict):
                continue
            if not bool(box.get("auto_generated", True)):
                deduped.append(box)
                continue
            bbox = box.get("bbox")
            text = str(box.get("text", "")).strip()
            deleted = bool(box.get("deleted"))
            if isinstance(bbox, dict):
                try:
                    signature = (
                        round(float(bbox.get("x", 0.0)), 1),
                        round(float(bbox.get("y", 0.0)), 1),
                        round(float(bbox.get("w", 0.0)), 1),
                        round(float(bbox.get("h", 0.0)), 1),
                        text,
                        deleted,
                    )
                except (TypeError, ValueError):
                    signature = None
            else:
                signature = None
            if signature is not None:
                if signature in seen:
                    continue
                seen.add(signature)
            deduped.append(box)
        pages[page_idx] = deduped
    return pages


def build_translated_zip(job_ids: set[str] | None) -> tuple[io.BytesIO, int]:
    job_root_for_type("ocr_overlay").mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    names: set[str] = set()
    base_counts: dict[str, int] = {}
    count = 0
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for job_dir_path in iter_job_dirs("ocr_overlay"):
            job_id = job_dir_path.name
            if job_ids is not None and job_id not in job_ids:
                continue
            edited_path = job_dir_path / "edited.pdf"
            if not edited_path.exists():
                continue
            job_name = get_job_name(job_dir_path)
            safe_name = build_download_base(job_id, job_name)
            count = base_counts.get(safe_name, 0) + 1
            base_counts[safe_name] = count
            filename = f"{safe_name}.pdf"
            if filename in names:
                filename = f"{safe_name}_{count}.pdf"
            names.add(filename)
            zf.write(edited_path, arcname=filename)
            count += 1
    buf.seek(0)
    return buf, count


def build_docx_zip(job_ids: set[str], job_type: str) -> tuple[io.BytesIO, int]:
    job_root_for_type(job_type).mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    names: set[str] = set()
    base_counts: dict[str, int] = {}
    file_count = 0
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for record in job_store.list_jobs(job_type):
            job_id = record.job_id
            if not safe_job_id(job_id) or job_id not in job_ids:
                continue
            job_dir_path = job_dir(job_id)
            docx_path = job_dir_path / "output" / "output.docx"
            if not docx_path.exists():
                continue
            job_name = normalize_job_name(getattr(record, "job_name", None)) or get_job_name(job_dir_path)
            safe_name = build_download_base(job_id, job_name)
            duplicate_count = base_counts.get(safe_name, 0) + 1
            base_counts[safe_name] = duplicate_count
            filename = build_docx_name(job_id, job_name)
            if filename in names:
                filename = f"{safe_name}_translated_{duplicate_count}.docx"
            names.add(filename)
            zf.write(docx_path, arcname=filename)
            file_count += 1
    buf.seek(0)
    return buf, file_count


def delete_job_dir(job_id: str) -> tuple[bool, str | None]:
    removed = False
    errors: list[str] = []
    for root in iter_job_roots():
        job_dir_path = root / job_id
        if not job_dir_path.exists():
            continue
        try:
            shutil.rmtree(job_dir_path)
            removed = True
        except Exception as exc:
            errors.append(str(exc))
    if errors:
        return False, "; ".join(errors)
    job_store.delete_job(job_id)
    notify_jobs_update()
    return True, None


def request_job_cancel(job_id: str) -> bool:
    cancelled = job_store.request_cancel(job_id)
    if cancelled:
        notify_jobs_update()
    return cancelled


def retry_job(job_id: str) -> tuple[bool, str | None]:
    record = job_store.get_job(job_id)
    if record is None:
        return False, "Job not found."
    if record.status in {"queued", "running"}:
        return False, "Job is already active."

    job_dir_path = job_dir(job_id)
    if not job_dir_path.exists():
        return False, "Job directory not found."

    payload = job_store.deserialize_payload(record)
    stage = "queued"
    if record.job_type in {"ocr_overlay", "template_source"}:
        has_ocr_output = (job_dir_path / "ocr_json").exists()
        has_batch_config = load_batch_config(job_dir_path) is not None
        if has_ocr_output and has_batch_config:
            payload["resume_translate_only"] = True
            stage = "translate"
            config = load_batch_config(job_dir_path) or {}
            payload["translate_mode"] = normalize_translate_mode(config.get("translate_mode"))
        else:
            config = {}
            payload.pop("resume_translate_only", None)
    else:
        payload.pop("resume_translate_only", None)

    requeued = job_store.requeue_job(
        job_id,
        stage=stage,
        payload=payload,
        progress=0.0,
    )
    if not requeued:
        return False, "Job could not be requeued."

    meta = load_job_meta(job_dir_path) or {}
    meta["progress"] = 0.0
    meta.pop("error", None)
    meta.pop("processing_completed_at", None)
    if stage == "translate":
        meta["translate_mode"] = payload.get("translate_mode")
        batch_status_payload = _batch_status_payload(
            "queued",
            job_id=job_id,
            model=config.get("model"),
            target_lang=config.get("target_lang"),
            translate_mode=payload.get("translate_mode"),
        )
    else:
        batch_status_payload = None

    _write_json_snapshot(
        job_meta_path(job_dir_path),
        meta,
        job_id=job_id,
        snapshot_name="job_meta",
    )
    if batch_status_payload is not None:
        _write_json_snapshot(
            batch_status_path(job_dir_path),
            batch_status_payload,
            job_id=job_id,
            snapshot_name="batch_status",
        )
    notify_jobs_update()
    return True, None


def get_active_upload() -> dict[str, object] | None:
    with state.ACTIVE_UPLOAD_LOCK:
        return state.ACTIVE_UPLOAD


def set_active_upload(payload: dict[str, object] | None) -> None:
    with state.ACTIVE_UPLOAD_LOCK:
        state.ACTIVE_UPLOAD = payload


def clear_active_upload(job_id: str) -> None:
    with state.ACTIVE_UPLOAD_LOCK:
        if state.ACTIVE_UPLOAD and state.ACTIVE_UPLOAD.get("job_id") == job_id:
            state.ACTIVE_UPLOAD = None
