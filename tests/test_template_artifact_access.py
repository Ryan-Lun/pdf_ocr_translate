from __future__ import annotations

import pytest

from app import create_app
from app.config import TestingConfig
from app.services import document_templates, job_store, jobs, state
from tests.db_safety import configure_test_database


def _job_id(prefix: str, tmp_path) -> str:
    suffix = f"{abs(hash(str(tmp_path))) & 0xFFFFFF:06x}"
    return (prefix + suffix).ljust(32, prefix)[:32]


@pytest.fixture
def template_auth_app(monkeypatch, tmp_path):
    engine = configure_test_database(monkeypatch)
    monkeypatch.setattr(TestingConfig, "AUTH_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "AUTH_STUB_ENABLED", True)
    monkeypatch.setattr(TestingConfig, "SECRET_KEY", "test-secret")
    monkeypatch.setattr(TestingConfig, "OWNER_ACCESS_ENABLED", True)
    monkeypatch.setattr(state, "TEMPLATE_JOB_ROOT", tmp_path / "templates" / "jobs")
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    app = create_app("testing")
    job_store.Base.metadata.create_all(bind=engine, checkfirst=True)
    return app


@pytest.fixture
def template_auth_client(template_auth_app):
    return template_auth_app.test_client()


def _login(client, work_id: str) -> None:
    resp = client.post(
        "/auth/login",
        data={"username": work_id, "display_name": work_id},
        follow_redirects=False,
    )
    assert resp.status_code == 302


def _create_template_source_job(app, job_id: str, *, owner_work_id: str):
    job_dir = state.TEMPLATE_JOB_ROOT / job_id
    job_dir.mkdir(parents=True)
    jobs.write_job_meta(
        job_dir,
        {
            "job_name": "template-source",
            "job_type": "template_source",
            "owner_work_id": owner_work_id,
            "document_mode": "scanned",
        },
    )
    (job_dir / f"{job_id}.pdf").write_bytes(b"source pdf")
    (job_dir / "overlay_debug.pdf").write_bytes(b"debug pdf")
    (job_dir / "edited.pdf").write_bytes(b"preview pdf")
    (job_dir / "images").mkdir()
    (job_dir / "images" / "editor_page_0001.png").write_bytes(b"page image")

    with app.app_context():
        job_store.create_job(
            job_id=job_id,
            job_type="template_source",
            stage="completed",
            status="completed",
            progress=1.0,
            job_name="template-source",
            owner_work_id=owner_work_id,
        )
        document_templates.save_document_template(
            {
                "name": "shared-template",
                "source_job_id": job_id,
                "pages": [
                    {
                        "page_index_0based": 0,
                        "boxes": [
                            {
                                "x_ratio": 0.1,
                                "y_ratio": 0.2,
                                "w_ratio": 0.3,
                                "h_ratio": 0.04,
                                "text": "Template Text",
                            }
                        ],
                    }
                ],
            },
            owner_work_id=owner_work_id,
        )
    return job_dir


def test_non_owner_cannot_download_template_source_pdf(
    template_auth_app, template_auth_client, tmp_path
):
    job_id = _job_id("1", tmp_path)
    _create_template_source_job(template_auth_app, job_id, owner_work_id="owner-a")
    _login(template_auth_client, "editor-b")

    resp = template_auth_client.get(f"/jobs/{job_id}/{job_id}.pdf?download=1")

    assert resp.status_code == 403


def test_non_owner_cannot_view_template_source_pdf(
    template_auth_app, template_auth_client, tmp_path
):
    job_id = _job_id("7", tmp_path)
    _create_template_source_job(template_auth_app, job_id, owner_work_id="owner-a")
    _login(template_auth_client, "editor-b")

    resp = template_auth_client.get(f"/jobs/{job_id}/{job_id}.pdf")

    assert resp.status_code == 403


def test_non_owner_cannot_download_template_debug_pdf(
    template_auth_app, template_auth_client, tmp_path
):
    job_id = _job_id("2", tmp_path)
    _create_template_source_job(template_auth_app, job_id, owner_work_id="owner-a")
    _login(template_auth_client, "editor-b")

    resp = template_auth_client.get(f"/jobs/{job_id}/overlay_debug.pdf?download=1")

    assert resp.status_code == 403


def test_non_owner_cannot_download_template_source_artifact_via_preview_path(
    template_auth_app, template_auth_client, tmp_path
):
    job_id = _job_id("8", tmp_path)
    _create_template_source_job(template_auth_app, job_id, owner_work_id="owner-a")
    _login(template_auth_client, "editor-b")

    resp = template_auth_client.get(f"/jobs/{job_id}/images/../overlay_debug.pdf?download=1")

    assert resp.status_code == 403


def test_non_owner_cannot_download_template_source_page_image_by_default(
    template_auth_app, template_auth_client, tmp_path
):
    job_id = _job_id("9", tmp_path)
    _create_template_source_job(template_auth_app, job_id, owner_work_id="owner-a")
    _login(template_auth_client, "editor-b")

    resp = template_auth_client.get(
        f"/jobs/{job_id}/images/editor_page_0001.png?download=1"
    )

    assert resp.status_code == 403


def test_owner_can_download_template_source_artifacts(
    template_auth_app, template_auth_client, tmp_path
):
    job_id = _job_id("3", tmp_path)
    _create_template_source_job(template_auth_app, job_id, owner_work_id="owner-a")
    _login(template_auth_client, "owner-a")

    source_resp = template_auth_client.get(f"/jobs/{job_id}/{job_id}.pdf?download=1")
    debug_resp = template_auth_client.get(f"/jobs/{job_id}/overlay_debug.pdf?download=1")

    assert source_resp.status_code == 200
    assert source_resp.data == b"source pdf"
    assert debug_resp.status_code == 200
    assert debug_resp.data == b"debug pdf"


def test_owner_cannot_traverse_to_another_template_source_artifact(
    template_auth_app, template_auth_client, tmp_path
):
    owner_job_id = _job_id("a", tmp_path)
    other_job_id = _job_id("b", tmp_path)
    _create_template_source_job(template_auth_app, owner_job_id, owner_work_id="owner-a")
    _create_template_source_job(template_auth_app, other_job_id, owner_work_id="owner-b")
    _login(template_auth_client, "owner-a")

    resp = template_auth_client.get(
        f"/jobs/{owner_job_id}/%2e%2e/{other_job_id}/{other_job_id}.pdf?download=1"
    )

    assert resp.status_code == 404


def test_admin_can_download_template_source_artifacts(
    template_auth_app, template_auth_client, monkeypatch, tmp_path
):
    job_id = _job_id("4", tmp_path)
    _create_template_source_job(template_auth_app, job_id, owner_work_id="owner-a")
    _login(template_auth_client, "admin-a")
    monkeypatch.setattr(
        "app.blueprints.jobs.routes.authz_service.user_is_admin",
        lambda _user: True,
    )

    source_resp = template_auth_client.get(f"/jobs/{job_id}/{job_id}.pdf?download=1")
    debug_resp = template_auth_client.get(f"/jobs/{job_id}/overlay_debug.pdf?download=1")

    assert source_resp.status_code == 200
    assert source_resp.data == b"source pdf"
    assert debug_resp.status_code == 200
    assert debug_resp.data == b"debug pdf"


def test_shared_template_payload_remains_accessible_to_non_owner(
    template_auth_app, template_auth_client, tmp_path
):
    job_id = _job_id("5", tmp_path)
    _create_template_source_job(template_auth_app, job_id, owner_work_id="owner-a")
    _login(template_auth_client, "editor-b")

    resp = template_auth_client.get("/api/document-templates")

    assert resp.status_code == 200
    body = resp.get_json()
    matching_templates = [
        item for item in body["templates"] if item.get("source_job_id") == job_id
    ]
    assert [item["name"] for item in matching_templates] == ["shared-template"]


def test_non_owner_can_download_explicitly_safe_template_preview_artifact(
    template_auth_app, template_auth_client, tmp_path
):
    job_id = _job_id("6", tmp_path)
    _create_template_source_job(template_auth_app, job_id, owner_work_id="owner-a")
    _login(template_auth_client, "editor-b")

    resp = template_auth_client.get(f"/jobs/{job_id}/edited.pdf?download=1")

    assert resp.status_code == 200
    assert resp.data == b"preview pdf"
