from __future__ import annotations

import json
import threading
from types import SimpleNamespace
import uuid

import pytest
from sqlalchemy import delete

from app.services import alerts, job_store, jobs, worker


def _job_id() -> str:
    return uuid.uuid4().hex


def _delete_job(job_id: str) -> None:
    with job_store.session_scope() as session:
        record = session.get(job_store.JobRecord, job_id)
        if record is not None:
            session.delete(record)


def _delete_system_errors() -> None:
    with job_store.session_scope() as session:
        session.execute(delete(job_store.SystemErrorLogRecord))


def _system_error_rows():
    with job_store.session_scope() as session:
        return session.query(job_store.SystemErrorLogRecord).all()


def test_default_job_handler_registry_resolves_supported_job_types():
    from app.services import job_handlers

    registry = job_handlers.default_job_handler_registry()

    ocr_handler = registry.resolve("ocr_overlay")
    template_handler = registry.resolve("template_source")

    assert ocr_handler is not None
    assert template_handler is ocr_handler
    assert ocr_handler.job_type == "ocr_overlay"
    assert registry.resolve("doc_workspace").job_type == "doc_workspace"
    assert registry.resolve("word_translate").job_type == "word_translate"
    assert registry.resolve("unknown") is None


def test_process_job_dispatches_supported_job_through_registry(app, tmp_path, monkeypatch):
    job_id = _job_id()
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    monkeypatch.setattr(jobs, "job_dir", lambda value: job_dir)
    calls = []

    class FakeHandler:
        job_type = "ocr_overlay"

        def handle(self, context):
            calls.append(
                {
                    "job_id": context.job_id,
                    "job_dir": context.job_dir,
                    "payload": dict(context.payload),
                    "record_status": context.record.status,
                }
            )

    class FakeRegistry:
        def resolve(self, job_type):
            assert job_type == "ocr_overlay"
            return FakeHandler()

    monkeypatch.setattr(worker, "JOB_HANDLER_REGISTRY", FakeRegistry())
    job_store.create_job(
        job_id=job_id,
        job_type="ocr_overlay",
        stage="queued",
        status="running",
        payload={"dpi": 144},
    )

    try:
        worker.process_job(job_id)

        assert calls == [
            {
                "job_id": job_id,
                "job_dir": job_dir,
                "payload": {"dpi": 144},
                "record_status": "running",
            }
        ]
    finally:
        _delete_job(job_id)


def test_process_job_records_unknown_job_type_as_failed(app, tmp_path, monkeypatch):
    job_id = _job_id()
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    monkeypatch.setattr(jobs, "job_dir", lambda value: job_dir)
    _delete_system_errors()
    job_store.create_job(
        job_id=job_id,
        job_type="unknown_type",
        stage="queued",
        status="running",
    )

    try:
        worker.process_job(job_id)

        record = job_store.get_job(job_id)
        rows = _system_error_rows()
        assert record is not None
        assert record.status == "failed"
        assert record.stage == "failed"
        assert record.error_message == "Unsupported job type: unknown_type"
        assert len(rows) == 1
        detail = json.loads(rows[0].detail_json or "{}")
        assert rows[0].component == "worker.job"
        assert rows[0].message == "Unsupported worker job type"
        assert rows[0].job_id == job_id
        assert detail["job_type"] == "unknown_type"
        assert detail["failure_kind"] == "unsupported_job_type"
    finally:
        _delete_job(job_id)
        _delete_system_errors()


def test_ocr_handler_runs_existing_pipeline_for_new_ocr_job(app, tmp_path, monkeypatch):
    from app.services import job_handlers

    job_id = _job_id()
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    calls = []

    def fake_start_cancel_monitor(monitored_job_id, cancel_event):
        calls.append(("monitor", monitored_job_id, isinstance(cancel_event, threading.Event)))
        return None

    def fake_run_ocr_pipeline_job(**kwargs):
        calls.append(("ocr", kwargs))

    monkeypatch.setattr(job_handlers, "start_cancel_monitor", fake_start_cancel_monitor)
    monkeypatch.setattr(job_handlers.pipeline, "run_ocr_pipeline_job", fake_run_ocr_pipeline_job)
    handler = job_handlers.default_job_handler_registry().resolve("template_source")
    record = job_store.JobRecord(
        job_id=job_id,
        job_type="template_source",
        status="running",
        stage="ocr",
        progress=0.0,
    )
    context = job_handlers.JobContext(
        job_id=job_id,
        record=record,
        job_dir=job_dir,
        payload={
            "dpi": 220,
            "start_page": 2,
            "page_numbers": [2, 4],
            "enable_translate": True,
        },
    )

    assert handler is not None
    handler.handle(context)

    assert calls[0] == ("monitor", job_id, True)
    assert calls[1][0] == "ocr"
    kwargs = calls[1][1]
    assert kwargs["job_id"] == job_id
    assert kwargs["job_dir"] == job_dir
    assert kwargs["pdf_path"] == job_dir / f"{job_id}.pdf"
    assert kwargs["dpi"] == 220
    assert kwargs["start_page"] == 2
    assert kwargs["page_numbers"] == [2, 4]
    assert kwargs["enable_translate"] is True


def test_doc_and_word_handlers_wrap_existing_service_boundaries(app, tmp_path, monkeypatch):
    from app.services import job_handlers

    doc_job_id = _job_id()
    word_job_id = _job_id()
    doc_dir = tmp_path / doc_job_id
    word_dir = tmp_path / word_job_id
    doc_dir.mkdir()
    word_dir.mkdir()
    jobs.write_job_meta(word_dir, {"source_filename": "source.doc"})
    calls = []

    monkeypatch.setattr(
        job_handlers.doc_workspace,
        "run_doc_workspace_job",
        lambda **kwargs: calls.append(("doc", kwargs)),
    )
    monkeypatch.setattr(
        job_handlers.word_translate,
        "run_word_translate_job",
        lambda **kwargs: calls.append(("word", kwargs)),
    )
    registry = job_handlers.default_job_handler_registry()

    doc_handler = registry.resolve("doc_workspace")
    word_handler = registry.resolve("word_translate")
    assert doc_handler is not None
    assert word_handler is not None

    doc_handler.handle(
        job_handlers.JobContext(
            job_id=doc_job_id,
            record=job_store.JobRecord(
                job_id=doc_job_id,
                job_type="doc_workspace",
                status="running",
                stage="queued",
                progress=0.0,
                target_lang="ja",
            ),
            job_dir=doc_dir,
            payload={"source_lang": "en", "system_prompt": "doc prompt"},
        )
    )
    word_handler.handle(
        job_handlers.JobContext(
            job_id=word_job_id,
            record=job_store.JobRecord(
                job_id=word_job_id,
                job_type="word_translate",
                status="running",
                stage="queued",
                progress=0.0,
                target_lang="ko",
            ),
            job_dir=word_dir,
            payload={
                "source_lang": "zh",
                "retain_terms": ["ABC"],
                "system_prompt": "word prompt",
                "layout_mode": "bilingual_below",
                "translate_tables": False,
            },
        )
    )

    assert calls[0] == (
        "doc",
        {
            "job_id": doc_job_id,
            "job_dir": doc_dir,
            "pdf_path": doc_dir / "source.pdf",
            "source_lang": "en",
            "target_lang": "ja",
            "system_prompt": "doc prompt",
        },
    )
    assert calls[1][0] == "word"
    word_kwargs = calls[1][1]
    assert word_kwargs["job_id"] == word_job_id
    assert word_kwargs["job_dir"] == word_dir
    assert word_kwargs["source_path"] == word_dir / "source.doc"
    assert word_kwargs["processing_source_path"] == word_dir / "source.converted.docx"
    assert word_kwargs["output_path"] == word_dir / "output" / "output.docx"
    assert word_kwargs["source_lang"] == "zh"
    assert word_kwargs["target_lang"] == "ko"
    assert word_kwargs["retain_terms"] == ["ABC"]
    assert word_kwargs["system_prompt"] == "word prompt"
    assert word_kwargs["layout_mode"] == "bilingual_below"
    assert word_kwargs["translate_tables"] is False


@pytest.mark.parametrize(
    ("payload", "expected_layout_mode", "expected_translate_tables"),
    [
        ({"source_lang": "zh"}, "replace_original", True),
        ({"source_lang": "zh", "translate_tables": True}, "replace_original", True),
        ({"source_lang": "zh", "translate_tables": "unsupported"}, "replace_original", True),
    ],
)
def test_word_handler_defaults_and_normalizes_options(
    app,
    tmp_path,
    monkeypatch,
    payload,
    expected_layout_mode,
    expected_translate_tables,
):
    from app.services import job_handlers

    job_id = _job_id()
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    jobs.write_job_meta(job_dir, {"source_filename": "source.docx"})
    captured: dict[str, object] = {}

    def fake_run_word_translate_job(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(job_handlers.word_translate, "run_word_translate_job", fake_run_word_translate_job)

    handler = job_handlers.WordTranslateJobHandler()
    handler.handle(
        job_handlers.JobContext(
            job_id=job_id,
            record=job_store.JobRecord(
                job_id=job_id,
                job_type="word_translate",
                status="running",
                stage="queued",
                progress=0.0,
                target_lang="en",
            ),
            job_dir=job_dir,
            payload=payload,
        )
    )

    assert captured["layout_mode"] == expected_layout_mode
    assert captured["translate_tables"] is expected_translate_tables


def test_word_handler_defaults_legacy_job_to_cloud_provider(
    app,
    tmp_path,
    monkeypatch,
):
    from app.services import job_handlers

    job_id = _job_id()
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    jobs.write_job_meta(job_dir, {"source_filename": "source.docx"})
    captured: dict[str, object] = {}
    monkeypatch.setattr(job_handlers.state, "WORD_TRANSLATE_MODEL", "cloud-word-model")
    monkeypatch.setattr(
        job_handlers.state,
        "TRANSLATION_POST_EDIT_MODEL",
        "cloud-post-edit-model",
    )
    monkeypatch.setattr(
        job_handlers.word_translate,
        "run_word_translate_job",
        lambda **kwargs: captured.update(kwargs),
    )

    job_handlers.WordTranslateJobHandler().handle(
        job_handlers.JobContext(
            job_id=job_id,
            record=job_store.JobRecord(
                job_id=job_id,
                job_type="word_translate",
                status="running",
                stage="queued",
                progress=0.0,
                target_lang="en",
            ),
            job_dir=job_dir,
            payload={"source_lang": "zh"},
        )
    )

    assert captured["translation_model"] == "cloud-word-model"
    assert captured["post_edit_model"] == "cloud-post-edit-model"
    assert "local_model_base_url" not in captured
    assert "local_model_api_key" not in captured
    for local_option in (
        "header_footer_exclude_patterns",
        "header_footer_font_size_pt",
        "excluded_table_indices",
        "header_footer_fixed_terms",
    ):
        assert local_option not in captured


def test_word_handler_dispatches_local_provider_with_server_managed_settings(
    app,
    tmp_path,
    monkeypatch,
):
    from app.services import job_handlers

    job_id = _job_id()
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    jobs.write_job_meta(job_dir, {"source_filename": "source.docx"})
    captured: dict[str, object] = {}
    monkeypatch.setattr(job_handlers.state, "LOCAL_WORD_BASE_URL", "http://local-model.example:8000/v1")
    monkeypatch.setattr(job_handlers.state, "LOCAL_WORD_API_KEY", "server-local-key")
    monkeypatch.setattr(job_handlers.state, "LOCAL_WORD_MODEL", "quality-local-model")
    monkeypatch.setattr(job_handlers.state, "LOCAL_WORD_STAGE_2_ENABLED", False)
    monkeypatch.setattr(job_handlers.state, "LOCAL_WORD_REQUEST_CONCURRENCY", 3)
    monkeypatch.setattr(job_handlers.state, "LOCAL_WORD_REQUESTS_PER_MINUTE", 45)
    monkeypatch.setattr(job_handlers.state, "LOCAL_WORD_ENABLE_THINKING", True)

    def fake_run_word_translate_job(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(
        job_handlers.word_translate,
        "run_word_translate_job",
        fake_run_word_translate_job,
    )

    job_handlers.WordTranslateJobHandler().handle(
        job_handlers.JobContext(
            job_id=job_id,
            record=job_store.JobRecord(
                job_id=job_id,
                job_type="word_translate",
                status="running",
                stage="queued",
                progress=0.0,
                target_lang="en",
            ),
            job_dir=job_dir,
            payload={
                "source_lang": "zh",
                "translation_provider": "local",
                "translation_model": "quality-local-model",
            },
        )
    )
    assert captured["translation_model"] == "quality-local-model"
    assert captured["post_edit_model"] == "quality-local-model"
    assert captured["local_model_base_url"] == "http://local-model.example:8000/v1"
    assert captured["local_model_api_key"] == "server-local-key"
    assert captured["stage_2_enabled"] is False
    assert captured["request_concurrency_limit"] == 3
    assert captured["requests_per_minute"] == 45
    assert captured["request_extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": True}
    }


    assert captured["header_footer_layout_mode"] == "bilingual_below"
    assert captured["header_footer_exclude_patterns"] == (
        "品質作業指導書",
        "生產作業指導書",
        "聯合材料規範",
        "聯合製程規範",
        "聯合品質規範",
        "聯合測試規範",
    )
    assert captured["header_footer_font_size_pt"] == 10
    assert captured["excluded_table_indices"] == (1,)
    assert captured["header_footer_fixed_terms"] == (
        ("號碼", "No."),
        ("頁次", "Page"),
    )


def test_word_handler_local_provider_defaults_disable_thinking(
    app,
    tmp_path,
    monkeypatch,
):
    from app.services import job_handlers

    job_id = _job_id()
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    jobs.write_job_meta(job_dir, {"source_filename": "source.docx"})
    captured: dict[str, object] = {}
    monkeypatch.setattr(job_handlers.state, "LOCAL_WORD_BASE_URL", "http://local-model.example/v1")
    monkeypatch.setattr(job_handlers.state, "LOCAL_WORD_API_KEY", "local-key")
    monkeypatch.setattr(job_handlers.state, "LOCAL_WORD_MODEL", "local-model")
    monkeypatch.setattr(job_handlers.state, "LOCAL_WORD_STAGE_2_ENABLED", True)
    monkeypatch.setattr(job_handlers.state, "LOCAL_WORD_REQUEST_CONCURRENCY", 1)
    monkeypatch.setattr(job_handlers.state, "LOCAL_WORD_REQUESTS_PER_MINUTE", 60)
    monkeypatch.setattr(job_handlers.state, "LOCAL_WORD_ENABLE_THINKING", False)
    monkeypatch.setattr(
        job_handlers.word_translate,
        "run_word_translate_job",
        lambda **kwargs: captured.update(kwargs),
    )

    job_handlers.WordTranslateJobHandler().handle(
        job_handlers.JobContext(
            job_id=job_id,
            record=job_store.JobRecord(
                job_id=job_id,
                job_type="word_translate",
                status="running",
                stage="queued",
                progress=0.0,
                target_lang="en",
            ),
            job_dir=job_dir,
            payload={"source_lang": "auto", "translation_provider": "local"},
        )
    )

    assert captured["translation_model"] == "local-model"
    assert captured["post_edit_model"] == "local-model"
    assert captured["stage_2_enabled"] is True
    assert captured["request_concurrency_limit"] == 1
    assert captured["requests_per_minute"] == 60
    assert captured["request_extra_body"] == {
        "chat_template_kwargs": {"enable_thinking": False}
    }


def test_worker_loop_records_orphan_recovery_exception_and_continues(app, monkeypatch):
    _delete_system_errors()
    recovery_calls = {"count": 0}
    alert_calls = []
    app.config.update(
        TEAMS_ALERT_ENABLED=True,
        TEAMS_ALERT_WEBHOOK_URL="https://teams.example/webhook",
        TEAMS_ALERT_DEDUP_SECONDS=0,
        TEAMS_ALERT_HOST="test-host",
    )

    def fake_post(url, *, json, timeout):
        alert_calls.append({"url": url, "json": json, "timeout": timeout})
        return type("Response", (), {"status_code": 204, "text": ""})()

    monkeypatch.setattr(alerts.requests, "post", fake_post)

    def fail_then_stop_recovery():
        recovery_calls["count"] += 1
        if recovery_calls["count"] > 1:
            raise KeyboardInterrupt
        raise RuntimeError("Database connection failed: login timeout expired")

    monkeypatch.setattr(
        worker.job_store,
        "recover_orphaned_active_jobs",
        fail_then_stop_recovery,
    )
    monkeypatch.setattr(worker.job_store, "claim_next_job", lambda *args, **kwargs: None)
    monkeypatch.setattr(worker.batch, "poll_active_batch_jobs", lambda limit=1: 0)
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: None)

    try:
        with pytest.raises(KeyboardInterrupt):
            worker.run_worker_loop(worker_id="worker-test", poll_seconds=0)

        rows = _system_error_rows()
        assert len(rows) == 1
        detail = json.loads(rows[0].detail_json or "{}")
        assert rows[0].component == "worker.loop"
        assert rows[0].message == "Worker orphan recovery failure"
        assert rows[0].job_id is None
        assert detail["exception_message"] == "Database connection failed: login timeout expired"
        assert detail["worker_id"] == "worker-test"
        assert detail["failure_kind"] == "orphan_recovery_failed"
        assert len(alert_calls) == 1
        assert alert_calls[0]["json"]["message"] == (
            "Worker orphan recovery failure: Database connection failed: login timeout expired"
        )
        assert alert_calls[0]["json"]["alert_summary"] == (
            "Database connection failed: login timeout expired"
        )
        assert recovery_calls["count"] == 2
    finally:
        _delete_system_errors()


def test_worker_loop_records_claim_exception_and_continues(app, monkeypatch):
    _delete_system_errors()
    claim_calls = {"count": 0}

    def fail_then_stop_claim(*args, **kwargs):
        claim_calls["count"] += 1
        if claim_calls["count"] > 1:
            raise KeyboardInterrupt
        raise RuntimeError("claim unavailable")

    monkeypatch.setattr(worker.job_store, "recover_orphaned_active_jobs", lambda: [])
    monkeypatch.setattr(worker.job_store, "claim_next_job", fail_then_stop_claim)
    monkeypatch.setattr(worker.batch, "poll_active_batch_jobs", lambda limit=1: 0)
    monkeypatch.setattr(worker.time, "sleep", lambda seconds: None)

    try:
        with pytest.raises(KeyboardInterrupt):
            worker.run_worker_loop(worker_id="worker-test", poll_seconds=0)

        rows = _system_error_rows()
        assert len(rows) == 1
        detail = json.loads(rows[0].detail_json or "{}")
        assert rows[0].component == "worker.loop"
        assert rows[0].message == "Worker job claim failure"
        assert rows[0].job_id is None
        assert detail["worker_id"] == "worker-test"
        assert detail["failure_kind"] == "claim_failed"
        assert claim_calls["count"] == 2
    finally:
        _delete_system_errors()


def test_process_job_cancel_requested_does_not_record_system_error(app, tmp_path, monkeypatch):
    job_id = _job_id()
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    monkeypatch.setattr(jobs, "job_dir", lambda value: job_dir)
    _delete_system_errors()
    job_store.create_job(
        job_id=job_id,
        job_type="ocr_overlay",
        stage="queued",
        status="running",
    )
    job_store.update_job(job_id, cancel_requested=True)

    try:
        worker.process_job(job_id)

        record = job_store.get_job(job_id)
        assert record is not None
        assert record.status == "cancelled"
        assert _system_error_rows() == []
    finally:
        _delete_job(job_id)
        _delete_system_errors()


def test_worker_loop_records_handler_exception_and_marks_job_failed(app, tmp_path, monkeypatch):
    job_id = _job_id()
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    _delete_system_errors()
    failed_jobs = []
    claim_calls = {"count": 0}

    def claim_once(*args, **kwargs):
        claim_calls["count"] += 1
        if claim_calls["count"] > 1:
            raise KeyboardInterrupt
        return SimpleNamespace(job_id=job_id, job_type="ocr_overlay")

    def fail_process(processed_job_id):
        assert processed_job_id == job_id
        raise RuntimeError("handler failed")

    def fake_fail_job(failed_job_dir, *, error_message):
        failed_jobs.append({"job_dir": failed_job_dir, "error_message": error_message})

    def stop_sleep(seconds):
        raise KeyboardInterrupt

    monkeypatch.setattr(worker.job_store, "recover_orphaned_active_jobs", lambda: [])
    monkeypatch.setattr(worker.job_store, "claim_next_job", claim_once)
    monkeypatch.setattr(worker, "process_job", fail_process)
    monkeypatch.setattr(worker.jobs, "job_dir", lambda value: job_dir)
    monkeypatch.setattr(worker.jobs, "fail_job", fake_fail_job)
    monkeypatch.setattr(worker.time, "sleep", stop_sleep)

    try:
        with pytest.raises(KeyboardInterrupt):
            worker.run_worker_loop(worker_id="worker-test", poll_seconds=0)

        rows = _system_error_rows()
        assert len(rows) == 1
        detail = json.loads(rows[0].detail_json or "{}")
        assert rows[0].component == "worker.loop"
        assert rows[0].message == "Worker loop failure"
        assert rows[0].job_id == job_id
        assert detail["worker_id"] == "worker-test"
        assert detail["job_type"] == "ocr_overlay"
        assert detail["failure_kind"] == "unhandled_exception"
        assert claim_calls["count"] == 2
        assert failed_jobs == [{"job_dir": job_dir, "error_message": "handler failed"}]
    finally:
        _delete_system_errors()
