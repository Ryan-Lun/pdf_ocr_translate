from __future__ import annotations

from pathlib import Path

import tomllib
from sqlalchemy import text

from app import create_app
from app.config import TestingConfig
from app.services import job_store
from tests.db_safety import configure_test_database


def _project_version() -> str:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def _authenticated_client(monkeypatch):
    engine = configure_test_database(monkeypatch)
    schema = job_store.current_database_schema()
    with engine.begin() as conn:
        conn.execute(
            text(
                f"IF OBJECT_ID(N'{schema}.document_templates', N'U') IS NOT NULL "
                f"DROP TABLE {job_store.qualified_table_name('document_templates', engine)};"
            )
        )
    job_store.Base.metadata.create_all(
        engine,
        tables=[job_store.DocumentTemplateRecord.__table__],
        checkfirst=True,
    )
    monkeypatch.setattr(TestingConfig, "AUTH_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "AUTH_STUB_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "SECRET_KEY", "test-secret")
    app = create_app("testing")
    client = app.test_client()
    client.post(
        "/auth/login",
        data={"username": "tester", "display_name": "Test User"},
        follow_redirects=False,
    )
    return client


def test_app_version_comes_from_project_metadata():
    from app.version import APP_VERSION

    assert APP_VERSION == _project_version()


def test_authenticated_index_displays_app_version_without_nav_height_change(monkeypatch):
    from app.version import APP_VERSION_LABEL

    client = _authenticated_client(monkeypatch)
    resp = client.get("/")

    assert resp.status_code == 200
    assert APP_VERSION_LABEL.encode() in resp.data
    assert b"app-version" in resp.data
    assert b"app-navbar__version" not in resp.data


def test_version_management_docs_and_changelog_exist():
    changelog = Path("CHANGELOG.md").read_text(encoding="utf-8")
    version_docs = Path("docs/system-description/21-版本號與Changelog管理.md").read_text(encoding="utf-8")
    index = Path("docs/system-description/README.md").read_text(encoding="utf-8")

    assert f"{_project_version()} - 2026-09-03" in changelog
    assert "Semantic Versioning" in changelog
    assert "MAJOR.MINOR.PATCH" in version_docs
    assert "pyproject.toml" in version_docs
    assert "CHANGELOG.md" in version_docs
    assert "21-版本號與Changelog管理.md" in index
