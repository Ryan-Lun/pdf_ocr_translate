from __future__ import annotations

import io
import json
import re
import shutil
import time
import zipfile
from pathlib import Path
from typing import Any

from flask import url_for
from werkzeug.utils import secure_filename

from . import state


def safe_job_id(job_id: str) -> bool:
    return bool(re.fullmatch(r"[a-f0-9]{32}", job_id))


def normalize_job_name(value: Any) -> str | None:
    if isinstance(value, str):
        cleaned = value.strip()
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


def build_download_base(job_id: str, job_name: str | None) -> str:
    base = job_name or "translated"
    safe = secure_filename(base) or "translated"
    return safe


def build_download_name(
    job_id: str, job_name: str | None, ext: str = "pdf", suffix: str = "translate"
) -> str:
    base = build_download_base(job_id, job_name)
    return f"{base}_{suffix}.{ext}" if suffix else f"{base}.{ext}"


def build_doc_markdown_name(job_id: str, job_name: str | None, translated: bool = False) -> str:
    suffix = "translated" if translated else "structure"
    return build_download_name(job_id, job_name, ext="md", suffix=suffix)


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


def build_jobs_list(job_type: str | None = None) -> list[dict[str, Any]]:
    state.JOB_ROOT.mkdir(parents=True, exist_ok=True)
    jobs = []
    for job_dir_path in sorted(state.JOB_ROOT.iterdir()):
        if not job_dir_path.is_dir():
            continue
        job_id = job_dir_path.name
        if not safe_job_id(job_id):
            continue
        current_job_type = get_job_type(job_dir_path)
        if job_type and current_job_type != job_type:
            continue

        pdf_path = job_dir_path / f"{job_id}.pdf"
        debug_pdf_path = job_dir_path / "overlay_debug.pdf"
        edited_pdf_path = job_dir_path / "edited.pdf"
        source_pdf_path = job_dir_path / "source.pdf"
        structure_md_path = job_dir_path / "structure" / "doc.md"
        translated_md_path = job_dir_path / "translated" / "doc.translated.md"
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
        translated_ts = job_timestamp(translated_md_path)
        docx_ts = job_timestamp(docx_path)
        updated_at = max(debug_ts, edited_ts, structure_ts, translated_ts, docx_ts, created_at)
        job_meta = load_job_meta(job_dir_path) or {}
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
                completed_at = docx_ts or translated_ts or structure_ts or None
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
            doc_stage = str(job_meta.get("doc_stage") or "uploaded").lower()
            status_map = {
                "uploaded": ("uploaded", "已上傳"),
                "structure_running": ("structure", "辨識中"),
                "structure_completed": ("structure_completed", "辨識完成"),
                "translate_running": ("translate", "翻譯中"),
                "translate_completed": ("translate_completed", "翻譯完成"),
                "docx_running": ("docx", "轉檔中"),
                "completed": ("completed", "完成"),
                "failed": ("failed", "失敗"),
            }
            status_code, status_label = status_map.get(doc_stage, ("uploaded", "已上傳"))
            jobs.append(
                {
                    "job_id": job_id,
                    "job_type": current_job_type,
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
                    "translated_md_url": url_for(
                        "jobs.job_file", job_id=job_id, filename="translated/doc.translated.md"
                    )
                    if translated_md_path.exists()
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
            word_stage = str(job_meta.get("word_stage") or "uploaded").lower()
            status_map = {
                "uploaded": ("uploaded", "已上傳"),
                "translate_running": ("translate", "翻譯中"),
                "completed": ("completed", "完成"),
                "cancelled": ("cancelled", "已取消"),
                "failed": ("failed", "失敗"),
            }
            status_code, status_label = status_map.get(word_stage, ("uploaded", "已上傳"))
            jobs.append(
                {
                    "job_id": job_id,
                    "job_type": current_job_type,
                    "created_at": created_at,
                    "updated_at": updated_at,
                    "duration_seconds": duration_seconds,
                    "ocr_duration_seconds": None,
                    "translate_duration_seconds": None,
                    "status_code": status_code,
                    "status_label": status_label,
                    "status": status_label,
                    "job_name": job_name,
                    "progress": float(job_meta.get("progress") or 0.0),
                    "avg_quality": float(job_meta.get("avg_quality") or 0.0),
                    "target_lang": job_meta.get("target_lang"),
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

        debug_ready = debug_pdf_path.exists()
        batch_status = load_batch_status(job_dir_path)
        batch_config = load_batch_config(job_dir_path)
        download_name = build_download_name(job_id, job_name)
        if not debug_ready:
            status_code = "ocr"
            status_label = "OCR"
        elif batch_config:
            batch_state = str((batch_status or {}).get("status") or "").lower()
            if batch_state in {"failed", "canceled", "cancelled"}:
                status_code = "translate_failed"
                status_label = "翻譯失敗"
            elif batch_state == "completed":
                status_code = "completed"
                status_label = "完成"
            else:
                status_code = "translate"
                status_label = "翻譯中"
        else:
            status_code = "completed"
            status_label = "完成"

        jobs.append(
            {
                "job_id": job_id,
                "job_type": current_job_type,
                "created_at": created_at,
                "updated_at": updated_at,
                "duration_seconds": duration_seconds,
                "ocr_duration_seconds": ocr_duration_seconds,
                "translate_duration_seconds": translate_duration_seconds,
                "status_code": status_code,
                "status_label": status_label,
                "status": status_label,
                "job_name": job_name,
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
        pages[page_idx] = [box for box in boxes if isinstance(box, dict)]
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
    if not job_dir_path.exists():
        return False, None
    try:
        shutil.rmtree(job_dir_path)
    except Exception as exc:
        return False, str(exc)
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
