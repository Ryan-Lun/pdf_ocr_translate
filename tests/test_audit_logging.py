from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import delete

from app import create_app
from app.config import TestingConfig
from app.services import alerts, audit_service, job_store
from tests.db_safety import configure_test_database


@pytest.fixture
def audit_app(monkeypatch):
    configure_test_database(monkeypatch)
    monkeypatch.setattr(TestingConfig, "AUTH_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "AUTH_STUB_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "SECRET_KEY", "test-secret")
    monkeypatch.setattr(TestingConfig, "INITIAL_ADMIN_WORK_IDS", "admin1")
    app = create_app("testing")
    return app


@pytest.fixture
def audit_client(audit_app):
    return audit_app.test_client()


@pytest.fixture(autouse=True)
def clean_logs(request):
    if "audit_app" not in request.fixturenames:
        yield
        return

    request.getfixturevalue("audit_app")
    with job_store.session_scope() as session:
        session.execute(delete(job_store.AuditLogRecord))
        session.execute(delete(job_store.SystemErrorLogRecord))
    yield
    with job_store.session_scope() as session:
        session.execute(delete(job_store.AuditLogRecord))
        session.execute(delete(job_store.SystemErrorLogRecord))


def _login_admin(client) -> None:
    resp = client.post(
        "/auth/login",
        data={"username": "admin1", "display_name": "Admin One"},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def _enable_teams_alerts(app, **overrides) -> None:
    config = {
        "TEAMS_ALERT_ENABLED": True,
        "TEAMS_ALERT_WEBHOOK_URL": "https://teams.example/webhook",
        "SYSTEM_ERROR_DB_MIN_LEVEL": "ERROR",
    }
    config.update(overrides)
    app.config.update(config)


def test_testing_config_disables_file_logging(audit_app):
    assert audit_app.config["APP_LOG_TO_FILE"] is False
    assert audit_app.config["APP_LOG_STDOUT"] is False


def test_login_and_logout_write_audit_rows(audit_client):
    _login_admin(audit_client)
    audit_client.get("/auth/logout", follow_redirects=False)

    with job_store.session_scope() as session:
        rows = session.query(job_store.AuditLogRecord).order_by(job_store.AuditLogRecord.id.asc()).all()

    assert [row.action for row in rows] == ["auth_login", "auth_logout"]
    assert rows[0].work_id == "admin1"


def test_admin_log_pages_render_for_admin(audit_app, audit_client, monkeypatch):
    _login_admin(audit_client)
    monkeypatch.setattr("app.blueprints.admin.routes.authz_service.user_is_admin", lambda _user: True)

    with audit_app.app_context():
        assert audit_service.record_audit(
            "job_retry",
            actor={"work_id": "admin1", "label": "Admin One"},
            detail={"retried": True},
            job_id="a" * 32,
        ) is True
        assert audit_service.record_system_error(
            "worker.loop",
            "Worker loop failure",
            detail={"worker_id": "worker-test"},
            job_id="b" * 32,
            level="ERROR",
        ) is True

    audit_resp = audit_client.get("/admin/audit-logs")
    error_resp = audit_client.get("/admin/system-error-logs")

    assert audit_resp.status_code == 200
    assert "操作紀錄" in audit_resp.get_data(as_text=True)
    assert "job_retry" in audit_resp.get_data(as_text=True)
    assert error_resp.status_code == 200
    assert "系統錯誤" in error_resp.get_data(as_text=True)
    assert "worker.loop" in error_resp.get_data(as_text=True)


def test_log_job_id_filters_match_displayed_prefix(audit_app):
    full_audit_job_id = "12345678abcdef12345678abcdefabcd"
    full_error_job_id = "87654321abcdef12345678abcdefabcd"
    with audit_app.app_context():
        assert audit_service.record_audit(
            "job_delete",
            actor={"work_id": "admin1"},
            detail={"deleted": True},
            job_id=full_audit_job_id,
        ) is True
        assert audit_service.record_system_error(
            "worker.loop",
            "Worker loop failure",
            detail={"worker_id": "worker-test"},
            job_id=full_error_job_id,
            level="ERROR",
        ) is True

    audit_rows, _ = audit_service.list_audit_logs(job_id=full_audit_job_id[:8])
    audit_q_rows, _ = audit_service.list_audit_logs(q=full_audit_job_id[:8])
    error_rows, _ = audit_service.list_system_error_logs(job_id=full_error_job_id[:8])
    error_q_rows, _ = audit_service.list_system_error_logs(q=full_error_job_id[:8])

    assert [row["job_id"] for row in audit_rows] == [full_audit_job_id]
    assert [row["job_id"] for row in audit_q_rows] == [full_audit_job_id]
    assert [row["job_id"] for row in error_rows] == [full_error_job_id]
    assert [row["job_id"] for row in error_q_rows] == [full_error_job_id]


def test_audit_cleanup_cli_removes_old_rows(audit_app):
    old_ts = job_store.utcnow() - timedelta(days=10)
    with job_store.session_scope() as session:
        session.add(
            job_store.AuditLogRecord(
                created_at=old_ts,
                action="old_audit",
                work_id="admin1",
                detail_json="{}",
                job_id=None,
                request_path=None,
                remote_addr=None,
            )
        )
        session.add(
            job_store.SystemErrorLogRecord(
                created_at=old_ts,
                level="ERROR",
                component="worker.loop",
                message="old error",
                error_type=None,
                detail_json="{}",
                job_id=None,
                request_path=None,
                remote_addr=None,
            )
        )

    runner = audit_app.test_cli_runner()
    audit_result = runner.invoke(args=["audit-cleanup", "--days", "1"])
    error_result = runner.invoke(args=["system-error-cleanup", "--days", "1"])

    assert audit_result.exit_code == 0
    assert "deleted=1" in audit_result.output
    assert error_result.exit_code == 0
    assert "deleted=1" in error_result.output

    with job_store.session_scope() as session:
        audit_count = session.query(job_store.AuditLogRecord).count()
        error_count = session.query(job_store.SystemErrorLogRecord).count()

    assert audit_count == 0
    assert error_count == 0


def test_record_system_error_sends_teams_alert_and_persists_row(audit_app, monkeypatch):
    calls = []
    _enable_teams_alerts(
        audit_app,
        TEAMS_ALERT_TIMEOUT_SECONDS=2.0,
        TEAMS_ALERT_DEDUP_SECONDS=900.0,
        TEAMS_ALERT_HOST="test-host",
    )

    def fake_post(url, *, json, timeout):
        calls.append({"url": url, "json": json, "timeout": timeout})
        return type("Response", (), {"status_code": 204, "text": ""})()

    monkeypatch.setattr(alerts.requests, "post", fake_post)

    with audit_app.app_context():
        assert audit_service.record_system_error(
            "worker.loop",
            "Worker loop failure",
            detail={"worker_id": "worker-test", "stage": "failed"},
            exc=RuntimeError("boom"),
            job_id="c" * 32,
            level="ERROR",
        ) is True

    with job_store.session_scope() as session:
        rows = session.query(job_store.SystemErrorLogRecord).all()

    assert len(rows) == 1
    assert rows[0].component == "worker.loop"
    assert rows[0].message == "Worker loop failure"
    assert len(calls) == 1
    assert calls[0]["url"] == "https://teams.example/webhook"
    assert calls[0]["timeout"] == 2.0
    assert calls[0]["json"]["source"] == "worker.loop"
    assert calls[0]["json"]["message"] == "Worker loop failure"
    assert calls[0]["json"]["exception_type"] == "RuntimeError"
    assert calls[0]["json"]["job_id"] == "c" * 32
    assert calls[0]["json"]["worker_id"] == "worker-test"
    assert calls[0]["json"]["stage"] == "failed"


def test_record_system_error_persists_row_when_teams_alert_fails(audit_app, monkeypatch):
    _enable_teams_alerts(audit_app)

    def fail_post(*args, **kwargs):
        raise alerts.requests.exceptions.RequestException("connection failed")

    monkeypatch.setattr(alerts.requests, "post", fail_post)

    with audit_app.app_context():
        assert audit_service.record_system_error(
            "pipeline.ocr",
            "OCR pipeline failed",
            detail={"stage": "ocr"},
            job_id="d" * 32,
            level="ERROR",
        ) is True

    with job_store.session_scope() as session:
        rows = session.query(job_store.SystemErrorLogRecord).all()

    assert len(rows) == 1
    assert rows[0].component == "pipeline.ocr"
    assert rows[0].message == "OCR pipeline failed"


def test_record_system_error_below_persistence_threshold_does_not_send_teams_alert(
    audit_app, monkeypatch
):
    calls = []
    _enable_teams_alerts(audit_app)
    monkeypatch.setattr(
        alerts.requests,
        "post",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with audit_app.app_context():
        assert audit_service.record_system_error(
            "worker.loop",
            "Worker warning",
            level="WARNING",
        ) is False

    with job_store.session_scope() as session:
        error_count = session.query(job_store.SystemErrorLogRecord).count()

    assert error_count == 0
    assert calls == []
