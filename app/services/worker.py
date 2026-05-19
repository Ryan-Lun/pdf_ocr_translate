from __future__ import annotations

import logging
import threading
import time

from . import batch, doc_workspace, job_store, jobs, pipeline, realtime_translate, state, word_translate

logger = logging.getLogger(__name__)


def _start_cancel_monitor(job_id: str, cancel_event: threading.Event) -> threading.Thread:
    def _watch() -> None:
        while not cancel_event.is_set():
            record = job_store.get_job(job_id)
            if record is None or record.cancel_requested:
                cancel_event.set()
                return
            time.sleep(1)

    thread = threading.Thread(target=_watch, daemon=True)
    thread.start()
    return thread


def process_job(job_id: str) -> None:
    record = job_store.get_job(job_id)
    if record is None:
        raise RuntimeError(f"Job not found: {job_id}")

    job_dir = jobs.job_dir(job_id)
    payload = job_store.deserialize_payload(record)
    logger.info("Worker processing job_id=%s job_type=%s", job_id, record.job_type)
    if record.cancel_requested:
        jobs.set_job_state(job_dir, status="cancelled", stage="cancelled", completed_at=time.time())
        return

    if record.job_type in {"ocr_overlay", "template_source"}:
        if bool(payload.get("resume_translate_only")) or str(record.stage or "").lower() == "translate":
            config = jobs.load_batch_config(job_dir) or {}
            translate_mode = jobs.normalize_translate_mode(
                config.get("translate_mode")
                or payload.get("translate_mode")
                or (jobs.load_job_meta(job_dir) or {}).get("translate_mode")
            )
            if translate_mode == "realtime":
                realtime_translate.run_realtime_translate_job(job_id, job_dir, config)
            else:
                batch.run_batch_translate_job(job_id, job_dir, config)
            return
        pdf_path = job_dir / f"{job_id}.pdf"
        cancel_event = threading.Event()
        _start_cancel_monitor(job_id, cancel_event)
        pipeline.run_ocr_pipeline_job(
            job_id=job_id,
            job_dir=job_dir,
            pdf_path=pdf_path,
            dpi=int(payload.get("dpi") or 200),
            start_page=int(payload.get("start_page") or 1),
            end_page=payload.get("end_page"),
            translate_source_lang=str(payload.get("translate_source_lang") or "auto"),
            translate_target_lang=str(payload.get("translate_target_lang") or "en"),
            translate_model=str(payload.get("translate_model") or state.AZURE_BATCH_MODEL),
            translate_mode=str(payload.get("translate_mode") or "batch"),
            keep_lang=str(payload.get("keep_lang") or "all"),
            enable_translate=bool(payload.get("enable_translate")),
            document_mode=str(payload.get("document_mode") or "form"),
            cancel_event=cancel_event,
        )
        return

    if record.job_type == "doc_workspace":
        doc_workspace.run_doc_workspace_job(
            job_id=job_id,
            job_dir=job_dir,
            pdf_path=job_dir / "source.pdf",
            source_lang=str(payload.get("source_lang") or "auto"),
            target_lang=str(payload.get("target_lang") or record.target_lang or "en"),
        )
        return

    if record.job_type == "word_translate":
        source_name = str((jobs.load_job_meta(job_dir) or {}).get("source_filename") or "source.docx")
        source_path = job_dir / source_name
        processing_source_path = (
            source_path
            if source_path.suffix.lower() == ".docx"
            else job_dir / f"{source_path.stem}.converted.docx"
        )
        output_path = job_dir / "output" / "output.docx"
        word_translate._run_word_job(
            job_id=job_id,
            job_dir=job_dir,
            source_path=source_path,
            processing_source_path=processing_source_path,
            output_path=output_path,
            source_lang=str(payload.get("source_lang") or "auto"),
            target_lang=str(payload.get("target_lang") or record.target_lang or "en"),
            retain_terms=list(payload.get("retain_terms") or []),
        )
        return

    raise RuntimeError(f"Unsupported job type: {record.job_type}")


def run_worker_loop(worker_id: str | None = None, poll_seconds: float | None = None) -> None:
    worker_name = worker_id or state.WORKER_ID
    delay = poll_seconds if poll_seconds is not None else state.WORKER_POLL_SECONDS
    concurrency_limits = {
        "ocr_overlay": state.WORKER_OCR_MAX_RUNNING,
        "pdf_translate": state.WORKER_PDF_TRANSLATE_MAX_RUNNING,
        "doc_workspace": state.WORKER_DOC_MAX_RUNNING,
        "word_translate": state.WORKER_WORD_MAX_RUNNING,
    }
    logger.info("Worker loop started worker_id=%s poll_seconds=%s", worker_name, delay)
    while True:
        recovered_job_ids = job_store.recover_orphaned_active_jobs()
        if recovered_job_ids:
            logger.warning(
                "Recovered orphaned active jobs count=%s job_ids=%s",
                len(recovered_job_ids),
                ",".join(recovered_job_ids),
            )
        record = job_store.claim_next_job(worker_name, concurrency_limits=concurrency_limits)
        processed_active_batch = False
        try:
            if record is not None:
                process_job(record.job_id)
            processed_active_batch = batch.poll_active_batch_jobs(limit=1) > 0
        except Exception as exc:
            job_id = record.job_id if record is not None else None
            logger.exception("Worker loop failure job_id=%s error=%s", job_id, exc)
            if job_id:
                job_store.update_job(
                    job_id,
                    status="failed",
                    error_message=str(exc),
                    completed_at=job_store.utcnow(),
                )
        finally:
            jobs.notify_jobs_update()
        if record is None and not processed_active_batch:
            time.sleep(delay)
