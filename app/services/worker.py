from __future__ import annotations

import logging
import time

from . import audit_service, batch, job_handlers, job_store, jobs, state

logger = logging.getLogger(__name__)


JOB_HANDLER_REGISTRY = job_handlers.default_job_handler_registry()


def _worker_error_detail(
    *,
    worker_id: str | None = None,
    job_type: str | None = None,
    failure_kind: str,
) -> dict[str, str]:
    detail = {"failure_kind": failure_kind}
    if worker_id:
        detail["worker_id"] = worker_id
    if job_type:
        detail["job_type"] = job_type
    return detail


def _record_worker_system_error(
    component: str,
    message: str,
    *,
    exc: Exception | None = None,
    job_id: str | None = None,
    worker_id: str | None = None,
    job_type: str | None = None,
    failure_kind: str,
) -> None:
    try:
        audit_service.record_system_error(
            component,
            message,
            exc=exc,
            job_id=job_id,
            detail=_worker_error_detail(
                worker_id=worker_id,
                job_type=job_type,
                failure_kind=failure_kind,
            ),
        )
    except Exception:
        logger.exception("Failed to record worker system error component=%s", component)


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

    handler = JOB_HANDLER_REGISTRY.resolve(record.job_type)
    if handler is None:
        jobs.fail_job(job_dir, error_message=f"Unsupported job type: {record.job_type}")
        _record_worker_system_error(
            "worker.job",
            "Unsupported worker job type",
            job_id=job_id,
            job_type=record.job_type,
            failure_kind="unsupported_job_type",
        )
        return

    handler.handle(
        job_handlers.JobContext(
            job_id=job_id,
            record=record,
            job_dir=job_dir,
            payload=payload,
        )
    )


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
        record = None
        processed_active_batch = False
        loop_step_failed = False
        try:
            try:
                recovered_job_ids = job_store.recover_orphaned_active_jobs()
            except Exception as exc:
                loop_step_failed = True
                logger.exception(
                    "Worker orphan recovery failure worker_id=%s error=%s",
                    worker_name,
                    exc,
                )
                _record_worker_system_error(
                    "worker.loop",
                    "Worker orphan recovery failure",
                    exc=exc,
                    worker_id=worker_name,
                    failure_kind="orphan_recovery_failed",
                )
            else:
                if recovered_job_ids:
                    logger.warning(
                        "Recovered orphaned active jobs count=%s job_ids=%s",
                        len(recovered_job_ids),
                        ",".join(recovered_job_ids),
                    )

            if not loop_step_failed:
                try:
                    record = job_store.claim_next_job(
                        worker_name,
                        concurrency_limits=concurrency_limits,
                    )
                except Exception as exc:
                    loop_step_failed = True
                    logger.exception(
                        "Worker job claim failure worker_id=%s error=%s",
                        worker_name,
                        exc,
                    )
                    _record_worker_system_error(
                        "worker.loop",
                        "Worker job claim failure",
                        exc=exc,
                        worker_id=worker_name,
                        failure_kind="claim_failed",
                    )

            if not loop_step_failed:
                try:
                    if record is not None:
                        process_job(record.job_id)
                    processed_active_batch = batch.poll_active_batch_jobs(limit=1) > 0
                except Exception as exc:
                    job_id = record.job_id if record is not None else None
                    job_type = record.job_type if record is not None else None
                    logger.exception("Worker loop failure job_id=%s error=%s", job_id, exc)
                    _record_worker_system_error(
                        "worker.loop",
                        "Worker loop failure",
                        exc=exc,
                        job_id=job_id,
                        worker_id=worker_name,
                        job_type=job_type,
                        failure_kind="unhandled_exception",
                    )
                    if job_id:
                        jobs.fail_job(jobs.job_dir(job_id), error_message=str(exc))
        finally:
            jobs.notify_jobs_update()
        if record is None and not processed_active_batch:
            time.sleep(delay)
