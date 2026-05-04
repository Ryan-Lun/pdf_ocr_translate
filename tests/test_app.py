from __future__ import annotations

import json
from pathlib import Path

from app.services import state


def test_index_ok(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type


def test_upload_missing_pdf(client):
    resp = client.post("/upload", data={})
    assert resp.status_code == 400


def test_invalid_job_routes(client):
    resp = client.get("/job/not-a-valid-job")
    assert resp.status_code == 404

    resp = client.get("/api/job/not-a-valid-job")
    assert resp.status_code == 404

    resp = client.get("/jobs/not-a-valid-job/file.pdf")
    assert resp.status_code == 404


def test_api_jobs_returns_json(client):
    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert isinstance(payload, dict)
    assert "jobs" in payload


def test_glossary_get(client):
    resp = client.get("/api/glossary")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert isinstance(payload, dict)
    assert payload.get("ok") is True


def test_save_job_writes_form_tm_from_editor_edits(client, tmp_path, monkeypatch):
    job_id = "a" * 32
    job_dir = tmp_path / "jobs" / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_PATH", tmp_path / "translation_memory.json")

    (job_dir / "batch_config.json").write_text(
        json.dumps({"document_mode": "form", "target_lang": "en"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    payload = {
        "pages": [
            {
                "page_index_0based": 0,
                "boxes": [
                    {
                        "id": 100000,
                        "deleted": False,
                        "bbox": {"x": 0, "y": 0, "w": 100, "h": 20},
                        "text": "Corrected translation",
                        "font_size": 16,
                        "no_clip": False,
                        "color": "#0000ff",
                        "auto_generated": True,
                        "tm_source_text": "表格內容",
                        "tm_source_normalized": "表格內容",
                        "tm_target_lang": "en",
                        "tm_document_mode": "form",
                    }
                ],
            }
        ]
    }

    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.apply_edits_to_pdf",
        lambda current_job_id, current_job_dir, edits: Path(current_job_dir) / "edited.pdf",
    )

    resp = client.post(f"/api/job/{job_id}/save", json=payload)
    assert resp.status_code == 200

    memory = json.loads(state.TRANSLATION_MEMORY_PATH.read_text(encoding="utf-8"))
    entry = memory["form|en|表格內容"]
    assert entry["source_text"] == "表格內容"
    assert entry["target_text"] == "Corrected translation"
    assert entry["target_lang"] == "en"
    assert entry["document_mode"] == "form"
    assert entry["source"] == "editor"
