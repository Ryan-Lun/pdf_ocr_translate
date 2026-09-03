from __future__ import annotations

from pathlib import Path

import tomllib


def _project_version() -> str:
    data = tomllib.loads(Path("pyproject.toml").read_text(encoding="utf-8"))
    return str(data["project"]["version"])


def test_app_version_comes_from_project_metadata():
    from app.version import APP_VERSION

    assert APP_VERSION == _project_version()


def test_index_displays_app_version(client):
    from app.version import APP_VERSION_LABEL

    resp = client.get("/")

    assert resp.status_code == 200
    assert APP_VERSION_LABEL.encode() in resp.data


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
