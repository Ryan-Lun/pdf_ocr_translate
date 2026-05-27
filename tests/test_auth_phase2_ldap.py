from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from app import create_app
from app.config import TestingConfig
from app.services import auth_service, job_store, state


@pytest.fixture
def ldap_app(monkeypatch):
    engine = create_engine(state.DATABASE_URL, future=True, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("IF OBJECT_ID(N'dbo.document_templates', N'U') IS NOT NULL DROP TABLE dbo.document_templates;"))
    job_store.Base.metadata.create_all(
        engine,
        tables=[job_store.DocumentTemplateRecord.__table__],
        checkfirst=True,
    )
    monkeypatch.setattr(TestingConfig, "AUTH_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "AUTH_STUB_ENABLED", False)
    monkeypatch.setattr(TestingConfig, "SECRET_KEY", "test-secret")
    app = create_app("testing")
    return app


@pytest.fixture
def app(ldap_app):
    return ldap_app


@pytest.fixture
def ldap_client(ldap_app):
    return ldap_app.test_client()


def test_ldap_login_requires_password(ldap_client):
    resp = ldap_client.post(
        "/auth/login",
        data={"username": "tester", "password": ""},
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert "請輸入密碼。" in resp.get_data(as_text=True)


def test_ldap_login_redirects_to_requested_page(ldap_client, monkeypatch):
    def fake_authenticate(config, *, username, password):
        assert username == "tester"
        assert password == "secret"
        return auth_service.AuthUser(work_id="tester", display_name="LDAP User")

    monkeypatch.setattr(auth_service, "authenticate_ldap_user", fake_authenticate)

    resp = ldap_client.post(
        "/auth/login?next=/workspace/pdf-overlay",
        data={"username": "tester", "password": "secret"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/workspace/pdf-overlay")


def test_ldap_login_error_from_service(ldap_client, monkeypatch):
    def fake_authenticate(config, *, username, password):
        raise auth_service.AuthenticationError("帳號或密碼錯誤。")

    monkeypatch.setattr(auth_service, "authenticate_ldap_user", fake_authenticate)

    resp = ldap_client.post(
        "/auth/login",
        data={"username": "tester", "password": "wrong"},
        follow_redirects=True,
    )

    assert resp.status_code == 200
    assert "帳號或密碼錯誤。" in resp.get_data(as_text=True)


def test_ldap_login_persists_session(ldap_client, monkeypatch):
    def fake_authenticate(config, *, username, password):
        return auth_service.AuthUser(work_id="tester", display_name="LDAP User")

    monkeypatch.setattr(auth_service, "authenticate_ldap_user", fake_authenticate)

    ldap_client.post(
        "/auth/login",
        data={"username": "tester", "password": "secret"},
        follow_redirects=False,
    )

    resp = ldap_client.get("/workspace/pdf-overlay")

    assert resp.status_code == 200
