from __future__ import annotations

import uuid


from app.services import job_store, jobs, state


def _job_id() -> str:
    return uuid.uuid4().hex


def _delete_job(job_id: str) -> None:
    with job_store.session_scope() as session:
        record = session.get(job_store.JobRecord, job_id)
        if record is not None:
            session.delete(record)


def test_set_job_state_updates_sql_before_snapshot_failure(app, tmp_path, monkeypatch):
    job_id = _job_id()
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    jobs.write_job_meta(
        job_dir,
        {
            "job_type": "ocr_overlay",
            "job_name": "sql-first",
            "owner_work_id": "owner-a",
            "progress": 0.1,
        },
    )
    job_store.create_job(
        job_id=job_id,
        job_type="ocr_overlay",
        stage="queued",
        status="queued",
        progress=0.1,
        job_name="sql-first",
        owner_work_id="owner-a",
    )
    original_write_text = jobs.Path.write_text

    def fail_job_meta_snapshot(self, *args, **kwargs):
        if self == jobs.job_meta_path(job_dir):
            raise OSError("snapshot disk unavailable")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(jobs.Path, "write_text", fail_job_meta_snapshot)

    try:
        jobs.set_job_state(
            job_dir,
            status="completed",
            stage="render",
            progress=1.0,
            completed_at=123.0,
            extra_meta={"translate_completed_at": 123.0},
        )

        record = job_store.get_job(job_id)
        assert record is not None
        assert record.status == "completed"
        assert record.stage == "render"
        assert record.progress == 1.0
        payload = job_store.deserialize_payload(record)
        assert payload["translate_completed_at"] == 123.0
    finally:
        _delete_job(job_id)


def test_build_jobs_list_prefers_sql_state_over_stale_snapshot(app, tmp_path, monkeypatch):
    job_id = _job_id()
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path)
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    jobs.write_job_meta(
        job_dir,
        {
            "job_type": "ocr_overlay",
            "job_name": "stale-json",
            "owner_work_id": "owner-a",
            "progress": 0.2,
            "error": "stale filesystem error",
        },
    )
    jobs.batch_status_path(job_dir).write_text(
        '{"status":"failed","error":"stale batch error"}',
        encoding="utf-8",
    )
    job_store.create_job(
        job_id=job_id,
        job_type="ocr_overlay",
        stage="render",
        status="completed",
        progress=1.0,
        job_name="sql-state",
        owner_work_id="owner-a",
        payload={"document_mode": "general", "error": "stale payload error"},
    )

    try:
        with app.test_request_context():
            listed = jobs.build_jobs_list(owner_work_id="owner-a")

        item = next(job for job in listed if job["job_id"] == job_id)
        assert item["job_status"] == "completed"
        assert item["job_stage"] == "render"
        assert item["status_code"] == "completed"
        assert item["error"] is None
        assert item["job_name"] == "sql-state"
    finally:
        _delete_job(job_id)


def test_write_batch_status_updates_sql_before_snapshot_failure(app, tmp_path, monkeypatch):
    job_id = _job_id()
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    job_store.create_job(
        job_id=job_id,
        job_type="ocr_overlay",
        stage="ocr",
        status="running",
        progress=0.5,
        job_name="batch-status",
        owner_work_id="owner-a",
    )
    original_write_text = jobs.Path.write_text

    def fail_batch_status_snapshot(self, *args, **kwargs):
        if self == jobs.batch_status_path(job_dir):
            raise OSError("batch status disk unavailable")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(jobs.Path, "write_text", fail_batch_status_snapshot)

    try:
        jobs.write_batch_status(job_dir, "failed", error="backend failed")

        record = job_store.get_job(job_id)
        assert record is not None
        assert record.status == "failed"
        assert record.stage == "translate"
        assert record.error_message == "backend failed"
    finally:
        _delete_job(job_id)


def test_queue_batch_translation_updates_sql_payload_and_snapshot(app, tmp_path):
    job_id = _job_id()
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    jobs.write_job_meta(
        job_dir,
        {
            "job_type": "ocr_overlay",
            "job_name": "resume-translate",
            "processing_completed_at": 12.0,
            "error": "stale error",
        },
    )
    job_store.create_job(
        job_id=job_id,
        job_type="ocr_overlay",
        stage="completed",
        status="failed",
        progress=1.0,
        job_name="resume-translate",
        payload={"translate_mode": "realtime"},
        completed_at=job_store.utcnow(),
    )

    try:
        status_payload = jobs.queue_batch_translation(
            job_dir,
            model="gpt-test",
            target_lang="zh-TW",
            translate_mode="batch",
            extra_meta={"ocr_completed_at": 99.0},
        )

        record = job_store.get_job(job_id)
        assert status_payload == {"status": "queued"}
        assert record is not None
        assert record.status == "queued"
        assert record.stage == "translate"
        assert record.error_message is None
        assert record.completed_at is None
        payload = job_store.deserialize_payload(record)
        assert payload["resume_translate_only"] is True
        assert payload["translate_mode"] == "batch"
        assert payload["ocr_completed_at"] == 99.0

        meta = jobs.load_job_meta(job_dir)
        assert meta is not None
        assert meta["translate_mode"] == "batch"
        assert meta["ocr_completed_at"] == 99.0
        assert "error" not in meta
        assert "processing_completed_at" not in meta
        batch_status = jobs.load_batch_status(job_dir)
        assert batch_status is not None
        assert batch_status["status"] == "queued"
        assert batch_status["model"] == "gpt-test"
        assert batch_status["target_lang"] == "zh-TW"
        assert batch_status["translate_mode"] == "batch"
    finally:
        _delete_job(job_id)


def test_build_batch_status_prefers_sql_over_stale_json_snapshot(app, tmp_path):
    job_id = _job_id()
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    jobs.batch_status_path(job_dir).write_text(
        '{"status":"running","error":"stale json error"}',
        encoding="utf-8",
    )
    job_store.create_job(
        job_id=job_id,
        job_type="ocr_overlay",
        stage="completed",
        status="completed",
        progress=1.0,
        job_name="sql-batch-status",
    )

    try:
        status = jobs.build_batch_status(job_dir)

        assert status["status"] == "completed"
        assert status["job_status"] == "completed"
        assert status["job_stage"] == "completed"
        assert status["progress"] == 1.0
        assert "error" not in status
    finally:
        _delete_job(job_id)


def test_batch_translation_active_requires_sql_translate_stage(app, tmp_path):
    queued_ocr_job_id = _job_id()
    completed_translate_job_id = _job_id()
    queued_ocr_dir = tmp_path / queued_ocr_job_id
    completed_translate_dir = tmp_path / completed_translate_job_id
    queued_ocr_dir.mkdir()
    completed_translate_dir.mkdir()
    jobs.batch_status_path(completed_translate_dir).write_text(
        '{"status":"queued"}',
        encoding="utf-8",
    )
    job_store.create_job(
        job_id=queued_ocr_job_id,
        job_type="ocr_overlay",
        stage="ocr",
        status="queued",
        job_name="queued-ocr",
    )
    job_store.create_job(
        job_id=completed_translate_job_id,
        job_type="ocr_overlay",
        stage="translate",
        status="completed",
        job_name="completed-translate",
    )

    try:
        assert jobs.batch_translation_active(queued_ocr_dir) is False
        assert jobs.batch_translation_active(completed_translate_dir) is False
    finally:
        _delete_job(queued_ocr_job_id)
        _delete_job(completed_translate_job_id)


def test_build_batch_status_does_not_report_ocr_stage_as_batch_running(app, tmp_path):
    job_id = _job_id()
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    jobs.batch_status_path(job_dir).write_text(
        '{"status":"running","error":"stale batch error"}',
        encoding="utf-8",
    )
    job_store.create_job(
        job_id=job_id,
        job_type="ocr_overlay",
        stage="ocr",
        status="running",
        progress=0.4,
        job_name="ocr-running",
    )

    try:
        status = jobs.build_batch_status(job_dir)

        assert status["status"] == "not_started"
        assert status["job_status"] == "running"
        assert status["job_stage"] == "ocr"
        assert "error" not in status
    finally:
        _delete_job(job_id)


def test_retry_job_requeues_sql_before_snapshot_failure(app, tmp_path, monkeypatch):
    job_id = _job_id()
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path)
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    (job_dir / "ocr_json").mkdir()
    jobs.write_job_meta(
        job_dir,
        {
            "job_type": "ocr_overlay",
            "job_name": "retry-sql-first",
            "processing_completed_at": 12.0,
            "error": "stale failure",
        },
    )
    jobs.write_batch_config(
        job_dir,
        {
            "model": "gpt-test",
            "target_lang": "zh-TW",
            "translate_mode": "batch",
        },
    )
    job_store.create_job(
        job_id=job_id,
        job_type="ocr_overlay",
        stage="failed",
        status="failed",
        progress=1.0,
        job_name="retry-sql-first",
    )
    job_store.update_job(job_id, error_message="failed")
    original_write_text = jobs.Path.write_text

    def fail_status_snapshots(self, *args, **kwargs):
        if self in {jobs.job_meta_path(job_dir), jobs.batch_status_path(job_dir)}:
            raise OSError("snapshot disk unavailable")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(jobs.Path, "write_text", fail_status_snapshots)

    try:
        retried, error = jobs.retry_job(job_id)

        record = job_store.get_job(job_id)
        assert retried is True
        assert error is None
        assert record is not None
        assert record.status == "queued"
        assert record.stage == "translate"
        assert record.error_message is None
        payload = job_store.deserialize_payload(record)
        assert payload["resume_translate_only"] is True
        assert payload["translate_mode"] == "batch"
    finally:
        _delete_job(job_id)


def test_create_job_state_creates_sql_before_snapshot_failure(app, tmp_path, monkeypatch):
    job_id = _job_id()
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    original_write_text = jobs.Path.write_text

    def fail_job_meta_snapshot(self, *args, **kwargs):
        if self == jobs.job_meta_path(job_dir):
            raise OSError("job meta disk unavailable")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(jobs.Path, "write_text", fail_job_meta_snapshot)

    try:
        jobs.create_job_state(
            job_dir,
            job_type="ocr_overlay",
            stage="queued",
            job_name="create-sql-first",
            owner_work_id="owner-a",
            payload={"creator_name": "Owner A"},
            meta={"job_type": "ocr_overlay", "job_name": "create-sql-first"},
            started_at=123.0,
        )

        record = job_store.get_job(job_id)
        assert record is not None
        assert record.status == "queued"
        assert record.stage == "queued"
        assert record.job_name == "create-sql-first"
        assert record.owner_work_id == "owner-a"
        payload = job_store.deserialize_payload(record)
        assert payload["creator_name"] == "Owner A"
    finally:
        _delete_job(job_id)


def test_queue_batch_translation_updates_sql_before_snapshot_failure(app, tmp_path, monkeypatch):
    job_id = _job_id()
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    jobs.write_job_meta(job_dir, {"job_type": "ocr_overlay", "job_name": "queue-sql-first"})
    job_store.create_job(
        job_id=job_id,
        job_type="ocr_overlay",
        stage="completed",
        status="failed",
        progress=1.0,
        job_name="queue-sql-first",
        payload={"translate_mode": "realtime"},
    )
    original_write_text = jobs.Path.write_text

    def fail_status_snapshots(self, *args, **kwargs):
        if self in {jobs.job_meta_path(job_dir), jobs.batch_status_path(job_dir)}:
            raise OSError("snapshot disk unavailable")
        return original_write_text(self, *args, **kwargs)

    monkeypatch.setattr(jobs.Path, "write_text", fail_status_snapshots)

    try:
        jobs.queue_batch_translation(
            job_dir,
            model="gpt-test",
            target_lang="zh-TW",
            translate_mode="batch",
        )

        record = job_store.get_job(job_id)
        assert record is not None
        assert record.status == "queued"
        assert record.stage == "translate"
        assert record.completed_at is None
        payload = job_store.deserialize_payload(record)
        assert payload["resume_translate_only"] is True
        assert payload["translate_mode"] == "batch"
    finally:
        _delete_job(job_id)
