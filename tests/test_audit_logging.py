from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import delete

from app import create_app
from app.config import TestingConfig
from app.services import audit_service, job_store
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
