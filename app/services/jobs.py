from __future__ import annotations

import io
import json
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


def safe_job_id(job_id: str) -> bool:
    return bool(re.fullmatch(r"[a-f0-9]{32}", job_id))


def datetime_from_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, (int, float)):
        return None
    try:
        return datetime.fromtimestamp(float(value), tz=timezone.utc)
    except (OverflowError, OSError, ValueError):
        return None


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
    return "ocr_overlay"


def normalize_document_mode(value: Any) -> str:
    mode = str(value or "").strip().lower()
    if mode == "general":
        return "general"
    if mode == "scanned":
        return "scanned"
    return "form"


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


def job_dir(job_id: str) -> Path:
    return state.JOB_ROOT / job_id


def job_timestamp(path: Path) -> float:
    try:
        return path.stat().st_mtime
    except FileNotFoundError:
        return 0.0


def notify_jobs_update() -> None:
    with state.JOBS_EVENT:
        state.JOBS_VERSION += 1
        state.JOBS_EVENT.notify_all()


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
    job_type = str(meta.get("job_type") or get_job_type(job_dir_path))
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
        meta.update({k: v for k, v in extra_meta.items() if v is not None})
    job_meta_path(job_dir_path).write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    _safe_update_job_store(
        job_id,
        job_type=job_type,
        status=status,
        stage=stage,
        progress=float(progress) if progress is not None else float(meta.get("progress") or 0.0),
        error_message=error_message,
        started_at=datetime_from_timestamp(started_at or meta.get("processing_started_at")),
        completed_at=datetime_from_timestamp(completed_at or meta.get("processing_completed_at")),
        job_name=normalize_job_name(meta.get("job_name")),
        target_lang=str(meta.get("target_lang") or "") or None,
        document_mode=str(meta.get("document_mode") or "") or None,
    )
    notify_jobs_update()


def _safe_update_job_store(job_id: str, **updates: Any) -> None:
    try:
        job_store.update_job(job_id, **updates)
    except Exception:
        return


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


def build_jobs_list(job_type: str | None = None) -> list[dict[str, Any]]:
    state.JOB_ROOT.mkdir(parents=True, exist_ok=True)
    jobs = []
    records = job_store.list_jobs(job_type)

    for record in records:
        job_dir_path = job_dir(record.job_id)
        current_job_type = record.job_type
        job_id = record.job_id
        job_meta = load_job_meta(job_dir_path) or {}

        pdf_path = job_dir_path / f"{job_id}.pdf"
        debug_pdf_path = job_dir_path / "overlay_debug.pdf"
        edited_pdf_path = job_dir_path / "edited.pdf"
        source_pdf_path = job_dir_path / "source.pdf"
        structure_md_path = job_dir_path / "structure" / "doc.md"
        structure_html_path = job_dir_path / "structure" / "doc.html"
        translated_html_path = job_dir_path / "translated" / "doc.translated.html"
        docx_path = job_dir_path / "output" / "output.docx"
        source_docx_path = None
        word_source_name = ""

        created_at = (
            job_timestamp(pdf_path)
            or job_timestamp(source_pdf_path)
            or job_timestamp(job_dir_path)
        )
        debug_ts = job_timestamp(debug_pdf_path)
        edited_ts = job_timestamp(edited_pdf_path)
        structure_ts = job_timestamp(structure_md_path)
        structure_html_ts = job_timestamp(structure_html_path)
        translated_html_ts = job_timestamp(translated_html_path)
        docx_ts = job_timestamp(docx_path)
        updated_at = max(
            debug_ts,
            edited_ts,
            structure_ts,
            structure_html_ts,
            translated_html_ts,
            docx_ts,
            created_at,
        )
        word_source_name = str(job_meta.get("source_filename") or "").strip()
        if word_source_name:
            source_docx_path = job_dir_path / word_source_name
            created_at = job_timestamp(source_docx_path) or created_at
            updated_at = max(updated_at, job_timestamp(source_docx_path))
        started_at = job_meta.get("processing_started_at") or created_at
        completed_at = job_meta.get("processing_completed_at")
        job_name = normalize_job_name(job_meta.get("job_name"))
        if not isinstance(completed_at, (int, float)):
            if current_job_type == "doc_workspace":
                completed_at = docx_ts or translated_html_ts or structure_html_ts or structure_ts or None
            elif current_job_type == "word_translate":
                completed_at = docx_ts or None
            else:
                if debug_ts:
                    completed_at = debug_ts
                elif edited_ts:
                    completed_at = edited_ts
        if isinstance(completed_at, (int, float)) and isinstance(started_at, (int, float)):
            duration_seconds = max(0.0, float(completed_at) - float(started_at))
        elif isinstance(started_at, (int, float)):
            duration_seconds = max(0.0, time.time() - float(started_at))
        else:
            duration_seconds = max(0.0, updated_at - created_at)

        if current_job_type == "doc_workspace":
            status_code, status_label = map_status_display(
                current_job_type, record.status, record.stage or "queued"
            )
            jobs.append(
                {
                    "job_id": job_id,
                    "job_type": current_job_type,
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
                    "download_name": build_docx_name(job_id, job_name),
                    "source_pdf_url": url_for(
                        "jobs.job_file", job_id=job_id, filename="source.pdf"
                    )
                    if source_pdf_path.exists()
                    else None,
                    "structure_md_url": url_for(
                        "jobs.job_file", job_id=job_id, filename="structure/doc.md"
                    )
                    if structure_md_path.exists()
                    else None,
                    "structure_html_url": url_for(
                        "jobs.job_file", job_id=job_id, filename="structure/doc.html"
                    )
                    if structure_html_path.exists()
                    else None,
                    "translated_html_url": url_for(
                        "jobs.job_file", job_id=job_id, filename="translated/doc.translated.html"
                    )
                    if translated_html_path.exists()
                    else None,
                    "docx_url": url_for(
                        "jobs.job_file", job_id=job_id, filename="output/output.docx"
                    )
                    if docx_path.exists()
                    else None,
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
                    "progress": float(job_meta.get("progress") or record.progress or 0.0),
                    "avg_quality": float(job_meta.get("avg_quality") or 0.0),
                    "target_lang": record.target_lang or job_meta.get("target_lang"),
                    "download_name": build_docx_name(job_id, job_name),
                    "source_docx_url": url_for(
                        "jobs.job_file", job_id=job_id, filename=word_source_name
                    )
                    if source_docx_path and source_docx_path.exists()
                    else None,
                    "docx_url": url_for(
                        "jobs.job_file", job_id=job_id, filename="output/output.docx"
                    )
                    if docx_path.exists()
                    else None,
                }
            )
            continue

        ocr_started_at = job_meta.get("ocr_started_at") or created_at
        ocr_completed_at = job_meta.get("ocr_completed_at") or debug_ts or None
        if isinstance(ocr_completed_at, (int, float)) and isinstance(ocr_started_at, (int, float)):
            ocr_duration_seconds = max(0.0, float(ocr_completed_at) - float(ocr_started_at))
        else:
            ocr_duration_seconds = None
        translate_started_at = job_meta.get("translate_started_at")
        translate_completed_at = job_meta.get("translate_completed_at") or edited_ts or None
        if isinstance(translate_completed_at, (int, float)) and isinstance(translate_started_at, (int, float)):
            translate_duration_seconds = max(0.0, float(translate_completed_at) - float(translate_started_at))
        else:
            translate_duration_seconds = None

        download_name = build_download_name(job_id, job_name)
        debug_ready = debug_pdf_path.exists()
        status_code, status_label = map_status_display(
            current_job_type, record.status, record.stage or "queued"
        )

        jobs.append(
            {
                "job_id": job_id,
                "job_type": current_job_type,
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
                "creator_name": str(job_meta.get("creator_name") or "").strip() or None,
                "document_mode": normalize_document_mode(
                    record.document_mode or job_meta.get("document_mode")
                ),
                "download_name": download_name,
                "editor_url": url_for("editor.editor", job_id=job_id),
                "debug_pdf_url": url_for(
                    "jobs.job_file", job_id=job_id, filename="overlay_debug.pdf"
                )
                if debug_ready
                else None,
                "edited_pdf_url": url_for(
                    "jobs.job_file", job_id=job_id, filename="edited.pdf"
                )
                if edited_pdf_path.exists()
                else None,
                }
            )
    jobs.sort(key=lambda item: item["updated_at"], reverse=True)
    return jobs


def batch_status_path(job_dir_path: Path) -> Path:
    return job_dir_path / state.BATCH_STATUS_NAME


def batch_config_path(job_dir_path: Path) -> Path:
    return job_dir_path / "batch_config.json"


def batch_alias_path(job_dir_path: Path) -> Path:
    return job_dir_path / state.BATCH_ALIAS_NAME


def batch_prefill_path(job_dir_path: Path) -> Path:
    return job_dir_path / state.BATCH_PREFILL_NAME


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


def write_batch_status(job_dir_path: Path, status: str, **meta: Any) -> None:
    payload = {
        "status": status,
        "updated_at": time.time(),
        **meta,
    }
    batch_status_path(job_dir_path).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    normalized = status.lower()
    if normalized == "completed":
        stage = "completed"
    elif normalized in {"failed", "canceled", "cancelled"}:
        stage = "translate"
    elif normalized == "queued":
        stage = "translate"
    else:
        stage = "translate"
    _safe_update_job_store(
        job_dir_path.name,
        status=DB_STATUS_BY_BATCH.get(normalized, "running"),
        stage=stage,
        error_message=str(meta.get("error") or "") or None,
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
    state.JOB_ROOT.mkdir(parents=True, exist_ok=True)
    buf = io.BytesIO()
    names: set[str] = set()
    base_counts: dict[str, int] = {}
    count = 0
    with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for job_dir_path in sorted(state.JOB_ROOT.iterdir()):
            if not job_dir_path.is_dir():
                continue
            job_id = job_dir_path.name
            if not safe_job_id(job_id):
                continue
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


def delete_job_dir(job_id: str) -> tuple[bool, str | None]:
    job_dir_path = job_dir(job_id)
    if job_dir_path.exists():
        try:
            shutil.rmtree(job_dir_path)
        except Exception as exc:
            return False, str(exc)
    job_store.delete_job(job_id)
    notify_jobs_update()
    return True, None


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
    if record.job_type == "ocr_overlay":
        has_ocr_output = (job_dir_path / "ocr_json").exists()
        has_batch_config = load_batch_config(job_dir_path) is not None
        if has_ocr_output and has_batch_config:
            payload["resume_translate_only"] = True
            stage = "translate"
            config = load_batch_config(job_dir_path) or {}
            write_batch_status(
                job_dir_path,
                "queued",
                job_id=job_id,
                model=config.get("model"),
                target_lang=config.get("target_lang"),
            )
        else:
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
    write_job_meta(job_dir_path, meta)
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
