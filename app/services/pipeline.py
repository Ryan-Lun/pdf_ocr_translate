from __future__ import annotations

import logging
import shutil
import threading
import time
import uuid
from pathlib import Path

from werkzeug.utils import secure_filename

from pipeline_ocr_overlay import PipelineCancelled, run_pipeline

from . import batch, jobs, ocr, state

logger = logging.getLogger(__name__)


def run_ocr_pipeline_job(
    job_id: str,
    job_dir: Path,
    pdf_path: Path,
    dpi: int,
    start_page: int,
    end_page: int | None,
    translate_target_lang: str,
    translate_model: str,
    keep_lang: str,
    enable_translate: bool,
    document_mode: str,
    cancel_event: threading.Event,
    spawn_translate_thread: bool = True,
) -> None:
    logger.info("OCR pipeline start job_id=%s", job_id)
    jobs.set_active_upload({"event": cancel_event, "job_id": job_id, "started_at": time.time()})
    jobs.set_job_state(job_dir, status="running", stage="ocr", started_at=time.time())
    try:
        run_pipeline(
            pdf_path=pdf_path,
            out_root=job_dir,
            dpi=dpi,
            start_page=start_page,
            end_page=end_page,
            min_score=0.0,
            draw_boxes=True,
            draw_text=True,
            enable_translate=False,
            translate_target_lang=translate_target_lang,
            translate_model=translate_model,
            triton_url=state.TRITON_URL,
            keep_lang=keep_lang,
            document_mode=jobs.normalize_document_mode(document_mode),
            cancel_event=cancel_event,
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
        now_ts = time.time()
        jobs.set_job_state(
            job_dir,
            status="failed",
            stage="ocr",
            error_message=str(exc),
            completed_at=now_ts,
            extra_meta={"ocr_completed_at": now_ts},
        )
        return
    finally:
        jobs.clear_active_upload(job_id)

    logger.info("OCR pipeline completed job_id=%s", job_id)
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
            "target_lang": translate_target_lang,
            "model": translate_model,
            "document_mode": jobs.normalize_document_mode(document_mode),
        }
        jobs.write_batch_config(job_dir, batch_config)
        jobs.set_job_state(
            job_dir,
            status="running",
            stage="translate",
            extra_meta={"ocr_completed_at": time.time()},
        )
        if spawn_translate_thread:
            threading.Thread(
                target=batch.run_batch_translate_job, args=(job_id, job_dir, batch_config), daemon=True
            ).start()
        else:
            batch.run_batch_translate_job(job_id, job_dir, batch_config)


def enqueue_job_from_upload(
    source_pdf: Path,
    display_name: str,
    dpi: int,
    start_page: int,
    end_page: int | None,
    translate_target_lang: str,
    translate_model: str,
    keep_lang: str,
    enable_translate: bool,
    document_mode: str,
    creator_name: str = "",
) -> str:
    job_id = uuid.uuid4().hex
    job_dir = jobs.job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    job_name = display_name
    now_ts = time.time()
    normalized_document_mode = jobs.normalize_document_mode(document_mode)
    jobs.write_job_meta(
        job_dir,
        {
            "job_name": job_name,
            "creator_name": creator_name,
            "job_type": "ocr_overlay",
            "document_mode": normalized_document_mode,
            "processing_started_at": now_ts,
            "ocr_started_at": now_ts,
        },
    )
    jobs.job_store.create_job(
        job_id=job_id,
        job_type="ocr_overlay",
        stage="queued",
        job_name=job_name,
        target_lang=translate_target_lang if enable_translate else None,
        document_mode=normalized_document_mode,
        payload={
            "dpi": dpi,
            "start_page": start_page,
            "end_page": end_page,
            "translate_target_lang": translate_target_lang,
            "translate_model": translate_model,
            "keep_lang": keep_lang,
            "enable_translate": enable_translate,
            "document_mode": normalized_document_mode,
        },
    )

    pdf_filename = secure_filename(f"{job_id}.pdf")
    pdf_path = job_dir / pdf_filename
    if source_pdf.exists():
        shutil.copy2(source_pdf, pdf_path)
    else:
        raise FileNotFoundError(f"Missing PDF: {source_pdf}")

    jobs.notify_jobs_update()

    return job_id
