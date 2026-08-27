from __future__ import annotations

import threading
import uuid

from app.services import job_store, jobs, worker


def _job_id() -> str:
    return uuid.uuid4().hex


def _delete_job(job_id: str) -> None:
    with job_store.session_scope() as session:
        record = session.get(job_store.JobRecord, job_id)
        if record is not None:
            session.delete(record)


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
    job_store.create_job(
        job_id=job_id,
        job_type="unknown_type",
        stage="queued",
        status="running",
    )

    try:
        worker.process_job(job_id)

        record = job_store.get_job(job_id)
        assert record is not None
        assert record.status == "failed"
        assert record.stage == "failed"
        assert record.error_message == "Unsupported job type: unknown_type"
    finally:
        _delete_job(job_id)


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
            payload={"source_lang": "zh", "retain_terms": ["ABC"], "system_prompt": "word prompt"},
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
