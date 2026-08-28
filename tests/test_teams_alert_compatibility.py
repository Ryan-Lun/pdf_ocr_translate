from __future__ import annotations

import json

import app as app_pkg
from sqlalchemy import delete

import pytest
from app import create_app
from app.config import TestingConfig
from app.services import alerts, audit_service, job_store
from tests.db_safety import configure_test_database


class FakeResponse:
    def __init__(self, status_code: int = 204, text: str = "") -> None:
        self.status_code = status_code
        self.text = text


def _disable_runtime_initializers(monkeypatch) -> None:
    monkeypatch.setattr(app_pkg, "init_extensions", lambda app: None)
    monkeypatch.setattr(app_pkg, "init_auth", lambda app: None)
    monkeypatch.setattr(app_pkg, "register_blueprints", lambda app: None)
    monkeypatch.setattr(app_pkg, "register_error_handlers", lambda app: None)
    monkeypatch.setattr(app_pkg, "register_before_request", lambda app: None)


def _clean_system_errors() -> None:
    with job_store.session_scope() as session:
        session.execute(delete(job_store.SystemErrorLogRecord))


def _system_error_rows():
    with job_store.session_scope() as session:
        return session.query(job_store.SystemErrorLogRecord).all()


def _configured_alert_app(monkeypatch, **config_overrides):
    configure_test_database(monkeypatch)
    monkeypatch.setattr(TestingConfig, "AUTH_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "AUTH_STUB_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "SECRET_KEY", "test-secret")
    app = create_app("testing")
    config = {
        "TEAMS_ALERT_ENABLED": True,
        "TEAMS_ALERT_WEBHOOK_URL": "https://teams.example/webhook",
        "TEAMS_ALERT_DEDUP_SECONDS": 900.0,
        "SYSTEM_ERROR_DB_MIN_LEVEL": "ERROR",
    }
    config.update(config_overrides)
    app.config.update(config)
    _clean_system_errors()
    return app


def test_system_error_seam_delivers_sanitized_teams_alert_when_configured(monkeypatch):
    calls = []
    app = _configured_alert_app(monkeypatch)

    def fake_post(url, *, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(alerts.requests, "post", fake_post)

    with app.app_context():
        assert audit_service.record_system_error(
            "worker.loop",
            "Worker loop failure",
            detail={
                "worker_id": "worker-1",
                "job_type": "ocr_overlay",
                "failure_kind": "claim_failed",
                "path": "/admin/system-error-logs?token=secret",
                "query_string": "token=secret",
                "traceback": "secret stack",
            },
            exc=RuntimeError("boom"),
            job_id="a" * 32,
        ) is True

    rows = _system_error_rows()

    assert len(rows) == 1
    assert len(calls) == 1
    payload = calls[0]["json"]
    persisted_detail = json.loads(rows[0].detail_json or "{}")
    assert rows[0].component == "worker.loop"
    assert calls[0]["url"] == "https://teams.example/webhook"
    assert payload["source"] == "worker.loop"
    assert payload["message"] == "Worker loop failure"
    assert payload["worker_id"] == "worker-1"
    assert payload["job_type"] == "ocr_overlay"
    assert payload["failure_kind"] == "claim_failed"
    assert payload["path"] == "/admin/system-error-logs"
    assert "traceback" in persisted_detail
    assert "traceback" not in payload
    assert "query_string" not in payload
    assert "token=secret" not in json.dumps(payload, ensure_ascii=False)


@pytest.mark.parametrize(
    "config_overrides",
    [
        {"TEAMS_ALERT_ENABLED": False},
        {"TEAMS_ALERT_ENABLED": True, "TEAMS_ALERT_WEBHOOK_URL": ""},
    ],
)
def test_system_error_persists_without_alert_when_alert_config_is_disabled(
    monkeypatch,
    config_overrides,
):
    calls = []
    app = _configured_alert_app(monkeypatch, **config_overrides)
    monkeypatch.setattr(
        alerts.requests,
        "post",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with app.app_context():
        assert audit_service.record_system_error(
            "worker.loop",
            "Worker loop failure",
            detail={"worker_id": "worker-1"},
            job_id="b" * 32,
        ) is True

    rows = _system_error_rows()

    assert len(rows) == 1
    assert rows[0].component == "worker.loop"
    assert calls == []


def test_teams_delivery_failure_does_not_break_system_error_recording(monkeypatch):
    app = _configured_alert_app(monkeypatch)

    def fail_post(*args, **kwargs):
        raise alerts.requests.exceptions.RequestException("connection failed")

    monkeypatch.setattr(alerts.requests, "post", fail_post)

    with app.app_context():
        assert audit_service.record_system_error(
            "batch.translate",
            "Batch translate failed",
            detail={
                "external_service": "openai",
                "deployment": "batch-prod",
                "failure_kind": "request_failed",
            },
            job_id="c" * 32,
        ) is True

    rows = _system_error_rows()

    assert len(rows) == 1
    detail = json.loads(rows[0].detail_json or "{}")
    assert rows[0].component == "batch.translate"
    assert detail["external_service"] == "openai"


def test_startup_warning_treats_enabled_alert_without_webhook_as_disabled(monkeypatch):
    warnings = []
    _disable_runtime_initializers(monkeypatch)
    monkeypatch.setattr(TestingConfig, "TEAMS_ALERT_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "TEAMS_ALERT_WEBHOOK_URL", "")
    monkeypatch.setattr(
        alerts.logger,
        "warning",
        lambda message, *args: warnings.append((message, args)),
    )

    app = create_app("testing")

    assert app.config["TEAMS_ALERT_ENABLED"] is True
    assert warnings[0][0].startswith(
        "Teams Alert is enabled but TEAMS_ALERT_WEBHOOK_URL is empty"
    )


def test_alerts_cli_test_delivery_bypasses_deduplication(monkeypatch):
    calls = []
    monkeypatch.setattr(TestingConfig, "TEAMS_ALERT_ENABLED", True)
    monkeypatch.setattr(
        TestingConfig,
        "TEAMS_ALERT_WEBHOOK_URL",
        "https://teams.example/webhook",
    )
    monkeypatch.setattr(TestingConfig, "TEAMS_ALERT_DEDUP_SECONDS", 900.0)

    def fake_post(url, *, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr(alerts.requests, "post", fake_post)
    app = create_app("testing")
    runner = app.test_cli_runner()

    first = runner.invoke(args=["alerts", "test-teams"])
    second = runner.invoke(args=["alerts", "test-teams"])

    assert first.exit_code == 0
    assert second.exit_code == 0
    assert len(calls) == 2
    assert calls[0]["json"]["source"] == "alerts.test"
    assert calls[1]["json"]["source"] == "alerts.test"
