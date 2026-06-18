from __future__ import annotations

import logging
import json
import shutil
import threading
import time
import uuid
from pathlib import Path

from werkzeug.utils import secure_filename

from ocr_pipeline.pipeline import PipelineCancelled, run_pipeline

from . import audit_service, batch, jobs, ocr, state

logger = logging.getLogger(__name__)


def run_ocr_pipeline_job(
    job_id: str,
    job_dir: Path,
    pdf_path: Path,
    dpi: int,
    start_page: int,
    end_page: int | None,
    page_numbers: list[int] | None,
    translate_source_lang: str,
    translate_target_lang: str,
    translate_model: str,
    translate_mode: str,
    keep_lang: str,
    enable_translate: bool,
    document_mode: str,
    cancel_event: threading.Event,
) -> None:
    logger.info("OCR pipeline start job_id=%s", job_id)
    normalized_document_mode = jobs.normalize_document_mode(document_mode)
    jobs.set_active_upload({"event": cancel_event, "job_id": job_id, "started_at": time.time()})
    jobs.set_job_state(
        job_dir,
        status="running",
        stage="ocr",
        started_at=time.time(),
        extra_meta={"last_warning": ""},
    )

    def record_progress(stage: str, current: int, total: int, message: str) -> None:
        progress = round((max(0, current) / max(1, total)) * 100.0, 2) if total else None
        if "請求失敗" in str(message):
            jobs.record_job_warning(job_dir, stage=stage or "ocr", message=str(message), progress=progress)
            return
        jobs.set_job_state(
            job_dir,
            status="running",
            stage=stage or "ocr",
            progress=progress,
        )

    try:
        run_pipeline(
            pdf_path=pdf_path,
            out_root=job_dir,
            dpi=dpi,
            start_page=start_page,
            end_page=end_page,
            page_numbers=page_numbers,
            min_score=0.0,
            draw_boxes=True,
            draw_text=True,
            enable_translate=False,
            translate_target_lang=translate_target_lang,
            translate_model=translate_model,
            triton_url=state.TABLE_RECOGNTION_V2_URL,
            keep_lang=keep_lang,
            document_mode=normalized_document_mode,
            cancel_event=cancel_event,
            progress_cb=record_progress,
        )
    except PipelineCancelled:
        logger.info("OCR pipeline cancelled job_id=%s", job_id)
        jobs.set_job_state(job_dir, status="cancelled", stage="ocr", completed_at=time.time())
        try:
            shutil.rmtree(job_dir)
        except Exception as exc:
            logger.warning("Failed to delete cancelled job_dir=%s error=%s", job_dir, exc)
        jobs.notify_jobs_update()
        return
    except Exception as exc:
        logger.exception("OCR pipeline failed job_id=%s error=%s", job_id, exc)
        audit_service.record_system_error(
            "ocr.pipeline",
            "OCR pipeline failed",
            exc=exc,
            job_id=job_id,
            detail={"stage": "ocr", "job_dir": str(job_dir)},
        )
        now_ts = time.time()
        jobs.fail_job(
            job_dir,
            stage="ocr",
            error_message=str(exc),
            completed_at=now_ts,
            extra_meta={"ocr_completed_at": now_ts},
        )
        return
    finally:
        jobs.clear_active_upload(job_id)

    logger.info("OCR pipeline completed job_id=%s", job_id)
    jobs.job_store.register_artifact(job_id, "debug_pdf", "overlay_debug.pdf")
    if normalized_document_mode != "general_force":
        ocr.update_pp_json_should_translate(job_dir)
    if not enable_translate:
        now_ts = time.time()
        jobs.set_job_state(
            job_dir,
            status="completed",
            stage="completed",
            completed_at=now_ts,
            progress=100.0,
            extra_meta={"ocr_completed_at": now_ts},
        )
    if enable_translate:
        batch_config = {
            "source_lang": translate_source_lang,
            "target_lang": translate_target_lang,
            "model": translate_model,
            "translate_mode": jobs.normalize_translate_mode(translate_mode),
            "document_mode": normalized_document_mode,
        }
        jobs.write_batch_config(job_dir, batch_config)
        jobs.set_job_state(
            job_dir,
            status="queued",
            stage="translate",
            extra_meta={"ocr_completed_at": time.time()},
        )
        record = jobs.job_store.get_job(job_id)
        payload = jobs.job_store.deserialize_payload(record)
        payload["resume_translate_only"] = True
        payload["translate_mode"] = batch_config["translate_mode"]
        jobs.job_store.update_job(
            job_id,
            status="queued",
            stage="translate",
            payload_json=json.dumps(payload, ensure_ascii=False),
            error_message=None,
            completed_at=None,
        )
        jobs.write_batch_status(
            job_dir,
            "queued",
            job_id=job_id,
            model=batch_config.get("model"),
            target_lang=batch_config.get("target_lang"),
            translate_mode=batch_config.get("translate_mode"),
        )


def enqueue_job_from_upload(
    source_pdf: Path,
    display_name: str,
    dpi: int,
    start_page: int,
    end_page: int | None,
    translate_source_lang: str,
    translate_target_lang: str,
    translate_model: str,
    translate_mode: str,
    keep_lang: str,
    enable_translate: bool,
    document_mode: str,
    creator_name: str = "",
    owner_work_id: str = "",
    job_root: Path | None = None,
    job_type: str = "ocr_overlay",
    page_numbers: list[int] | None = None,
) -> str:
    job_id = uuid.uuid4().hex
    job_dir = jobs.job_dir(job_id, job_root=job_root)
    job_dir.mkdir(parents=True, exist_ok=True)
    job_name = display_name
    now_ts = time.time()
    normalized_document_mode = jobs.normalize_document_mode(document_mode)
    jobs.write_job_meta(
        job_dir,
        {
            "job_name": job_name,
            "creator_name": creator_name,
            "owner_work_id": str(owner_work_id or "").strip(),
            "job_type": job_type,
            "document_mode": normalized_document_mode,
            "translate_mode": jobs.normalize_translate_mode(translate_mode),
            "processing_started_at": now_ts,
            "ocr_started_at": now_ts,
        },
    )
    jobs.job_store.create_job(
        job_id=job_id,
        job_type=job_type,
        stage="queued",
        job_name=job_name,
        owner_work_id=str(owner_work_id or "").strip() or None,
        target_lang=translate_target_lang if enable_translate else None,
        document_mode=normalized_document_mode,
        payload={
            "dpi": dpi,
            "start_page": start_page,
            "end_page": end_page,
            "page_numbers": page_numbers or None,
            "translate_source_lang": translate_source_lang,
            "translate_target_lang": translate_target_lang,
            "translate_model": translate_model,
            "translate_mode": jobs.normalize_translate_mode(translate_mode),
            "keep_lang": keep_lang,
            "enable_translate": enable_translate,
            "document_mode": normalized_document_mode,
            "creator_name": creator_name,
            "owner_work_id": str(owner_work_id or "").strip(),
            "processing_started_at": now_ts,
            "ocr_started_at": now_ts,
        },
    )

    pdf_filename = secure_filename(f"{job_id}.pdf")
    pdf_path = job_dir / pdf_filename
    if source_pdf.exists():
        shutil.copy2(source_pdf, pdf_path)
        jobs.job_store.register_artifact(job_id, "source_pdf", pdf_filename)
    else:
        raise FileNotFoundError(f"Missing PDF: {source_pdf}")

    jobs.notify_jobs_update()

    return job_id
