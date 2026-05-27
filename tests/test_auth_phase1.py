from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text

from app import create_app
from app.config import TestingConfig
from app.services import job_store, state


@pytest.fixture
def auth_app(monkeypatch):
    engine = create_engine(state.DATABASE_URL, future=True, pool_pre_ping=True)
    with engine.begin() as conn:
        conn.execute(text("IF OBJECT_ID(N'dbo.document_templates', N'U') IS NOT NULL DROP TABLE dbo.document_templates;"))
    job_store.Base.metadata.create_all(
        engine,
        tables=[job_store.DocumentTemplateRecord.__table__],
        checkfirst=True,
    )
    monkeypatch.setattr(TestingConfig, "AUTH_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "AUTH_STUB_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "SECRET_KEY", "test-secret")
    app = create_app("testing")
    return app


@pytest.fixture
def app(auth_app):
    return auth_app


@pytest.fixture
def auth_client(auth_app):
    return auth_app.test_client()


def test_workspace_redirects_to_login_when_auth_enabled(auth_client):
    resp = auth_client.get("/workspace/pdf-overlay")

    assert resp.status_code == 302
    assert resp.headers["Location"].startswith("/auth/login?next=")
    assert "/workspace/pdf-overlay" in resp.headers["Location"]


def test_stub_login_redirects_to_requested_page(auth_client):
    resp = auth_client.post(
        "/auth/login?next=/workspace/pdf-overlay",
        data={"username": "tester", "display_name": "Test User"},
        follow_redirects=False,
    )

    assert resp.status_code == 302
    assert resp.headers["Location"].endswith("/workspace/pdf-overlay")


def test_logged_in_user_can_access_workspace(auth_client):
    auth_client.post(
        "/auth/login",
        data={"username": "tester", "display_name": "Test User"},
        follow_redirects=False,
    )

    resp = auth_client.get("/workspace/pdf-overlay")

    assert resp.status_code == 200


def test_api_requires_auth_when_auth_enabled(auth_client):
    resp = auth_client.get("/api/jobs")

    assert resp.status_code == 401
    assert resp.get_json() == {"ok": False, "error": "Authentication required."}


def test_logout_clears_session(auth_client):
    auth_client.post("/auth/login", data={"username": "tester"}, follow_redirects=False)

    logout_resp = auth_client.get("/auth/logout", follow_redirects=False)
    after_resp = auth_client.get("/workspace/pdf-overlay", follow_redirects=False)

    assert logout_resp.status_code == 302
    assert logout_resp.headers["Location"].endswith("/auth/login")
    assert after_resp.status_code == 302
