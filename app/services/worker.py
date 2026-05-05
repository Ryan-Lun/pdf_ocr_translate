from __future__ import annotations

import logging
import threading
import time

from . import batch, doc_workspace, job_store, jobs, pipeline, state, word_translate

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

    if record.job_type == "ocr_overlay":
        if bool(payload.get("resume_translate_only")):
            config = jobs.load_batch_config(job_dir) or {}
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
            translate_target_lang=str(payload.get("translate_target_lang") or "en"),
            translate_model=str(payload.get("translate_model") or state.AZURE_BATCH_MODEL),
            keep_lang=str(payload.get("keep_lang") or "all"),
            enable_translate=bool(payload.get("enable_translate")),
            document_mode=str(payload.get("document_mode") or "form"),
            cancel_event=cancel_event,
            spawn_translate_thread=False,
        )
        return

    if record.job_type == "doc_workspace":
        doc_workspace.run_doc_workspace_job(
            job_id=job_id,
            job_dir=job_dir,
            pdf_path=job_dir / "source.pdf",
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
            target_lang=str(payload.get("target_lang") or record.target_lang or "en"),
            retain_terms=list(payload.get("retain_terms") or []),
        )
        return

    raise RuntimeError(f"Unsupported job type: {record.job_type}")


def run_worker_loop(worker_id: str | None = None, poll_seconds: float | None = None) -> None:
    worker_name = worker_id or state.WORKER_ID
    delay = poll_seconds if poll_seconds is not None else state.WORKER_POLL_SECONDS
    logger.info("Worker loop started worker_id=%s poll_seconds=%s", worker_name, delay)
    while True:
        record = job_store.claim_next_job(worker_name)
        if record is None:
            time.sleep(delay)
            continue
        try:
            process_job(record.job_id)
        except Exception as exc:
            logger.exception("Worker job failed job_id=%s error=%s", record.job_id, exc)
            job_store.update_job(
                record.job_id,
                status="failed",
                error_message=str(exc),
                completed_at=job_store.utcnow(),
            )
        finally:
            jobs.notify_jobs_update()
