from __future__ import annotations

import uuid

from app.services import job_store


def _delete_job_if_exists(job_id: str) -> None:
    with job_store.session_scope() as session:
        record = session.get(job_store.JobRecord, job_id)
        if record is not None:
            session.delete(record)


def test_claim_next_job_ignores_orphaned_active_rows(app):
    orphaned_job_id = uuid.uuid4().hex
    queued_job_id = uuid.uuid4().hex

    try:
        job_store.create_job(
            job_id=orphaned_job_id,
            job_type="word_translate",
            stage="translate",
            status="running",
            job_name="orphaned",
        )
        job_store.create_job(
            job_id=queued_job_id,
            job_type="word_translate",
            stage="queued",
            status="queued",
            job_name="queued",
        )

        claimed = job_store.claim_next_job(
            "test-worker",
            concurrency_limits={"word_translate": 1},
        )

        assert claimed is not None
        assert claimed.job_id == queued_job_id
    finally:
        _delete_job_if_exists(orphaned_job_id)
        _delete_job_if_exists(queued_job_id)


def test_recover_orphaned_active_jobs_requeues_running_rows(app):
    orphaned_job_id = uuid.uuid4().hex

    try:
        job_store.create_job(
            job_id=orphaned_job_id,
            job_type="ocr_overlay",
            stage="ocr",
            status="running",
            job_name="orphaned",
        )

        recovered = job_store.recover_orphaned_active_jobs()
        record = job_store.get_job(orphaned_job_id)

        assert orphaned_job_id in recovered
        assert record is not None
        assert record.status == "queued"
        assert record.stage == "queued"
        assert record.worker_id is None
        assert record.started_at is None
    finally:
        _delete_job_if_exists(orphaned_job_id)


def test_recover_orphaned_active_jobs_requeues_dead_local_worker_rows(app, monkeypatch):
    orphaned_job_id = uuid.uuid4().hex

    try:
        job_store.create_job(
            job_id=orphaned_job_id,
            job_type="ocr_overlay",
            stage="ocr",
            status="running",
            job_name="dead-worker",
        )
        job_store.update_job(orphaned_job_id, worker_id="worker-999999")

        def _fake_kill(pid: int, sig: int) -> None:
            raise ProcessLookupError()

        monkeypatch.setattr(job_store.os, "kill", _fake_kill)

        recovered = job_store.recover_orphaned_active_jobs()
        record = job_store.get_job(orphaned_job_id)

        assert orphaned_job_id in recovered
        assert record is not None
        assert record.status == "queued"
        assert record.stage == "queued"
        assert record.worker_id is None
    finally:
        _delete_job_if_exists(orphaned_job_id)
