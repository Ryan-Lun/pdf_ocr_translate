from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest
from sqlalchemy import delete

from app import create_app
from app.config import TestingConfig
from app.services import alerts, batch, job_store, jobs, realtime_translate
from tests.db_safety import configure_test_database


class FakeResponse:
    status_code = 204
    text = ""


@pytest.fixture
def external_error_app(monkeypatch):
    configure_test_database(monkeypatch)
    monkeypatch.setattr(TestingConfig, "AUTH_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "AUTH_STUB_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "SECRET_KEY", "test-secret")
    app = create_app("testing")
    app.config.update(
        TEAMS_ALERT_ENABLED=True,
        TEAMS_ALERT_WEBHOOK_URL="https://teams.example/webhook",
        SYSTEM_ERROR_DB_MIN_LEVEL="ERROR",
    )
    return app


@pytest.fixture(autouse=True)
def clean_records(request):
    if "external_error_app" not in request.fixturenames:
        yield
        return

    request.getfixturevalue("external_error_app")
    _delete_records()
    yield
    _delete_records()


def _delete_records() -> None:
    with job_store.session_scope() as session:
        session.execute(delete(job_store.SystemErrorLogRecord))
        session.execute(delete(job_store.JobRecord))


def _create_translate_job(job_dir, *, translate_mode="batch") -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    jobs.create_job_state(
        job_dir,
        job_type="pdf_translate",
        stage="translate",
        status="queued",
        target_lang="en",
        payload={"translate_mode": translate_mode},
        meta={"translate_mode": translate_mode},
    )


def _system_error_rows():
    with job_store.session_scope() as session:
        return session.query(job_store.SystemErrorLogRecord).all()


def _job_record(job_id: str):
    with job_store.session_scope() as session:
        return session.get(job_store.JobRecord, job_id)


def _enable_fake_alert_delivery(monkeypatch):
    calls = []

    def fake_post(url, *, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(alerts.requests, "post", fake_post)
    return calls


def test_batch_submit_failure_records_system_error_and_preserves_job_failure(
    external_error_app, tmp_path, monkeypatch
):
    job_id = "a" * 32
    job_dir = tmp_path / job_id
    _create_translate_job(job_dir)
    alert_calls = _enable_fake_alert_delivery(monkeypatch)

    monkeypatch.setattr(batch.ocr, "load_ocr_pages", lambda _job_dir: [{"page": 1}])
    monkeypatch.setattr(batch.ocr, "load_pp_pages", lambda _job_dir: [])
    monkeypatch.setattr(batch.glossary, "load_combined_glossary", lambda: [])
    monkeypatch.setattr(
        batch,
        "build_batch_items",
        lambda *args, **kwargs: (
            [{"custom_id": "item-1", "method": "POST", "url": "/v1/chat/completions", "body": {}}],
            {},
            {"item-1": "box-1"},
            {},
        ),
    )

    class FailingClient:
        files = SimpleNamespace(
            create=lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("timed out"))
        )

    monkeypatch.setattr(batch, "get_azure_client", lambda: FailingClient())

    with external_error_app.app_context():
        result = batch.run_batch_translate_job(
            job_id,
            job_dir,
            {"target_lang": "en", "model": "batch-prod-deployment"},
        )

    rows = _system_error_rows()
    record = _job_record(job_id)
    batch_status = jobs.load_batch_status(job_dir)

    assert result is False
    assert record.status == "failed"
    assert record.stage == "translate"
    assert "timed out" in (record.error_message or "")
    assert batch_status["status"] == "failed"
    assert "timed out" in batch_status["error"]
    assert len(rows) == 1
    assert rows[0].component == "batch.translate"
    assert rows[0].job_id == job_id
    assert len(alert_calls) == 1
    assert alert_calls[0]["json"]["external_service"] == "openai"
    assert alert_calls[0]["json"]["deployment"] == "batch-prod-deployment"
    assert alert_calls[0]["json"]["failure_kind"] == "timeout"


def test_batch_poll_failure_records_system_error_and_preserves_job_failure(
    external_error_app, tmp_path, monkeypatch
):
    job_id = "b" * 32
    job_dir = tmp_path / job_id
    _create_translate_job(job_dir)
    jobs.write_batch_status(
        job_dir,
        "running",
        job_id=job_id,
        model="batch-prod-deployment",
        target_lang="en",
        translate_mode="batch",
        batch_id="batch-123",
    )
    alert_calls = _enable_fake_alert_delivery(monkeypatch)

    class FailingClient:
        batches = SimpleNamespace(
            retrieve=lambda *args, **kwargs: (_ for _ in ()).throw(
                ConnectionError("connection failed")
            )
        )

    monkeypatch.setattr(batch, "get_azure_client", lambda: FailingClient())

    with external_error_app.app_context():
        result = batch.run_batch_translate_job(
            job_id,
            job_dir,
            {"target_lang": "en", "model": "batch-prod-deployment"},
            poll_only=True,
        )

    rows = _system_error_rows()
    record = _job_record(job_id)
    batch_status = jobs.load_batch_status(job_dir)

    assert result is False
    assert record.status == "failed"
    assert record.stage == "translate"
    assert "connection failed" in (record.error_message or "")
    assert batch_status["status"] == "failed"
    assert batch_status["batch_id"] == "batch-123"
    assert "connection failed" in batch_status["error"]
    assert len(rows) == 1
    assert rows[0].component == "batch.translate"
    assert rows[0].job_id == job_id
    assert len(alert_calls) == 1
    assert alert_calls[0]["json"]["external_service"] == "openai"
    assert alert_calls[0]["json"]["deployment"] == "batch-prod-deployment"
    assert alert_calls[0]["json"]["failure_kind"] == "request_failed"


def test_realtime_translate_failure_records_system_error_and_preserves_job_failure(
    external_error_app, tmp_path, monkeypatch
):
    job_id = "c" * 32
    job_dir = tmp_path / job_id
    _create_translate_job(job_dir, translate_mode="realtime")
    alert_calls = _enable_fake_alert_delivery(monkeypatch)
    monkeypatch.setattr(
        realtime_translate,
        "_prepare_realtime_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(TimeoutError("timed out")),
    )

    with external_error_app.app_context():
        result = realtime_translate.run_realtime_translate_job(
            job_id,
            job_dir,
            {"target_lang": "en", "model": "realtime-prod-deployment"},
        )

    rows = _system_error_rows()
    record = _job_record(job_id)
    batch_status = jobs.load_batch_status(job_dir)

    assert result is False
    assert record.status == "failed"
    assert record.stage == "translate"
    assert "timed out" in (record.error_message or "")
    assert batch_status["status"] == "failed"
    assert batch_status["translate_mode"] == "realtime"
    assert "timed out" in batch_status["error"]
    assert len(rows) == 1
    assert rows[0].component == "realtime.translate"
    assert rows[0].job_id == job_id
    assert len(alert_calls) == 1
    assert alert_calls[0]["json"]["external_service"] == "openai"
    assert alert_calls[0]["json"]["deployment"] == "realtime-prod-deployment"
    assert alert_calls[0]["json"]["failure_kind"] == "timeout"


def test_realtime_retry_that_recovers_does_not_record_system_error_or_alert(
    external_error_app, tmp_path, monkeypatch
):
    alert_calls = _enable_fake_alert_delivery(monkeypatch)
    create_calls = {"count": 0}

    async def fake_acquire_async(model_name, estimated_tokens):
        return None

    async def fake_sleep(seconds):
        return None

    class RecoveringRawResponse:
        async def create(self, **kwargs):
            create_calls["count"] += 1
            if create_calls["count"] == 1:
                raise TimeoutError("timed out")
            return SimpleNamespace(
                headers={},
                parse=lambda: SimpleNamespace(
                    choices=[
                        SimpleNamespace(
                            message=SimpleNamespace(content="translated text")
                        )
                    ]
                ),
            )

    class RecoveringClient:
        chat = SimpleNamespace(
            completions=SimpleNamespace(with_raw_response=RecoveringRawResponse())
        )

    monkeypatch.setattr(
        realtime_translate.rate_limiter.REALTIME_RATE_LIMITER,
        "acquire_async",
        fake_acquire_async,
    )
    monkeypatch.setattr(
        realtime_translate.rate_limiter.REALTIME_RATE_LIMITER,
        "update_from_headers",
        lambda model_name, headers: None,
    )
    monkeypatch.setattr(realtime_translate.asyncio, "sleep", fake_sleep)

    item = {
        "custom_id": "p0000-l0001",
        "body": {
            "messages": [
                {"role": "system", "content": "base prompt"},
                {"role": "user", "content": "source text"},
            ]
        },
    }
    warnings: list[str] = []

    with external_error_app.app_context():
        result = asyncio.run(
            realtime_translate._translate_item(
                RecoveringClient(),
                job_dir=tmp_path,
                chunk_label="chunk_0001",
                item=item,
                model_name="realtime-prod-deployment",
                request_delay=0,
                max_retries=2,
                warning_callback=warnings.append,
            )
        )

    assert result == ("p0000-l0001", "translated text")
    assert create_calls["count"] == 2
    assert len(warnings) == 1
    assert _system_error_rows() == []
    assert alert_calls == []


def test_batch_terminal_failed_status_records_system_error_and_preserves_poll_result(
    external_error_app, tmp_path, monkeypatch
):
    job_id = "d" * 32
    job_dir = tmp_path / job_id
    _create_translate_job(job_dir)
    jobs.write_batch_status(
        job_dir,
        "running",
        job_id=job_id,
        model="batch-prod-deployment",
        target_lang="en",
        translate_mode="batch",
        batch_id="batch-failed",
    )
    alert_calls = _enable_fake_alert_delivery(monkeypatch)

    class FailedBatchClient:
        batches = SimpleNamespace(
            retrieve=lambda *args, **kwargs: SimpleNamespace(
                status="failed",
                output_file_id="",
                error_file_id="",
            )
        )

    monkeypatch.setattr(batch, "get_azure_client", lambda: FailedBatchClient())

    with external_error_app.app_context():
        result = batch.run_batch_translate_job(
            job_id,
            job_dir,
            {"target_lang": "en", "model": "batch-prod-deployment"},
            poll_only=True,
        )

    rows = _system_error_rows()
    record = _job_record(job_id)
    batch_status = jobs.load_batch_status(job_dir)

    assert result is True
    assert record.status == "failed"
    assert record.stage == "translate"
    assert record.error_message == "Batch status = failed"
    assert batch_status["status"] == "failed"
    assert batch_status["batch_id"] == "batch-failed"
    assert len(rows) == 1
    assert rows[0].component == "batch.translate"
    assert rows[0].message == "Batch translate batch failed"
    assert rows[0].job_id == job_id
    assert len(alert_calls) == 1
    assert alert_calls[0]["json"]["external_service"] == "openai"
    assert alert_calls[0]["json"]["deployment"] == "batch-prod-deployment"
    assert alert_calls[0]["json"]["failure_kind"] == "unknown"
