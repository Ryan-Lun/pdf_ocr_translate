from __future__ import annotations

import io
import json
import threading
from pathlib import Path

from app.services import jobs, pipeline, state, translation_memory


def test_index_ok(client):
    resp = client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type


def test_overlay_templates_page_ok(client):
    resp = client.get("/workspace/pdf-overlay/templates")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type


def test_upload_template_source_creates_draft(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(state, "TEMPLATE_JOB_ROOT", tmp_path / "templates" / "jobs")
    monkeypatch.setattr(state, "UPLOAD_ROOT", tmp_path / "uploads")
    captured: list[dict[str, object]] = []

    def fake_enqueue(
        source_pdf,
        display_name,
        dpi,
        start_page,
        end_page,
        translate_source_lang,
        translate_target_lang,
        translate_model,
        translate_mode,
        keep_lang,
        enable_translate,
        document_mode,
        creator_name="",
        job_root=None,
        job_type="ocr_overlay",
    ):
        captured.append(
            {
                "display_name": display_name,
                "enable_translate": enable_translate,
                "document_mode": document_mode,
                "start_page": start_page,
                "end_page": end_page,
                "job_root": job_root,
                "job_type": job_type,
            }
        )
        return "9" * 32

    monkeypatch.setattr(
        "app.blueprints.main.routes.pipeline.enqueue_job_from_upload",
        fake_enqueue,
    )

    resp = client.post(
        "/upload-template-source",
        data={"pdf": (io.BytesIO(b"%PDF-1.4"), "template-source.pdf"), "page": "3"},
        content_type="multipart/form-data",
    )

    assert resp.status_code == 302
    assert captured == [
        {
            "display_name": "template-source",
            "enable_translate": False,
            "document_mode": "scanned",
            "start_page": 3,
            "end_page": 3,
            "job_root": tmp_path / "templates" / "jobs",
            "job_type": "template_source",
        }
    ]
    templates = client.get("/api/document-templates").get_json()["templates"]
    assert len(templates) == 1
    assert templates[0]["status"] == "draft"
    assert templates[0]["source_job_id"] == "9" * 32


def test_api_jobs_excludes_template_source_jobs(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(state, "TEMPLATE_JOB_ROOT", tmp_path / "templates" / "jobs")
    job_id = "4" * 32
    job_dir = tmp_path / "templates" / "jobs" / job_id
    job_dir.mkdir(parents=True)
    jobs.write_job_meta(
        job_dir,
        {
            "job_name": "template-source",
            "job_type": "template_source",
            "document_mode": "scanned",
        },
    )
    class Record:
        def __init__(self, current_job_type):
            self.job_id = job_id
            self.job_type = current_job_type
            self.status = "queued"
            self.stage = "queued"
            self.progress = 0.0
            self.target_lang = None
            self.document_mode = "scanned"

    monkeypatch.setattr(
        jobs.job_store,
        "list_jobs",
        lambda job_type=None: [Record(job_type)] if job_type == "template_source" else [],
    )

    resp = client.get("/api/jobs")
    assert resp.status_code == 200
    assert resp.get_json()["jobs"] == []

    template_resp = client.get("/api/template-jobs")
    assert template_resp.status_code == 200
    assert len(template_resp.get_json()["jobs"]) == 1


def test_template_editor_page_ok(client, tmp_path, monkeypatch):
    job_id = "1" * 32
    job_dir = tmp_path / "jobs" / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")

    resp = client.get(f"/workspace/pdf-overlay/templates/{job_id}")
    assert resp.status_code == 200
    assert "text/html" in resp.content_type
    body = resp.get_data(as_text=True)
    assert 'id="saveBtn"' not in body
    assert "batchRestoreBtn" not in body
    assert "sidebarConsistencySection" not in body
    assert "glossaryPromptBtn" not in body
    assert "batchTranslateBtn" not in body
    assert "contextRetranslateBtn" not in body
    assert "translateSelectedBoxesBtn" in body


def test_editor_page_shows_template_entry(client, tmp_path, monkeypatch):
    job_id = "3" * 32
    job_dir = tmp_path / "jobs" / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")

    resp = client.get(f"/job/{job_id}")
    assert resp.status_code == 200
    body = resp.get_data(as_text=True)
    assert "templateManagerBtn" in body
    assert "templateManagerModal" in body


def test_apply_document_template_to_job(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    job_id = "2" * 32
    job_dir = tmp_path / "jobs" / job_id
    ocr_dir = job_dir / "ocr_json"
    ocr_dir.mkdir(parents=True)

    (ocr_dir / "page_0001_res_with_pdf_coords.json").write_text(
        json.dumps(
            {
                "page_index_0based": 0,
                "input_path": "page1.png",
                "coord_transform": {"image_size_px": [1000, 2000]},
                "rec_polys": [[[10, 20], [110, 20], [110, 60], [10, 60]]],
                "rec_texts": ["原始框"],
                "edit_texts": ["原始框"],
                "rec_scores": [0.99],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    client.post(
        "/api/document-templates",
        json={
            "name": "表單模板",
            "pages": [
                {
                    "page_index_0based": 0,
                    "boxes": [
                        {
                            "x_ratio": 0.2,
                            "y_ratio": 0.3,
                            "w_ratio": 0.2,
                            "h_ratio": 0.05,
                            "text": "Template Text",
                            "font_size": 18,
                            "color": "#123456",
                            "text_align": "center",
                            "rotation": 0,
                            "no_clip": False,
                        }
                    ],
                }
            ],
        },
    )
    template_id = client.get("/api/document-templates").get_json()["templates"][0]["id"]

    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.apply_edits_to_pdf",
        lambda current_job_id, current_job_dir, edits: Path(current_job_dir) / "edited.pdf",
    )

    resp = client.post(
        f"/api/document-templates/{template_id}/apply",
        json={"job_id": job_id},
    )
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["created_count"] == 1

    saved = json.loads((job_dir / "edits.json").read_text(encoding="utf-8"))
    boxes = saved["pages"][0]["boxes"]
    assert len(boxes) == 2
    assert boxes[1]["text"] == "Template Text"
    assert boxes[1]["bbox"] == {"x": 200.0, "y": 600.0, "w": 200.0, "h": 100.0}


def test_upload_missing_pdf(client):
    resp = client.post("/upload", data={})
    assert resp.status_code == 400


def test_upload_pdf_overlay_accepts_realtime_mode(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(state, "UPLOAD_ROOT", tmp_path / "uploads")
    captured: list[dict[str, str]] = []

    def fake_enqueue(
        source_pdf,
        display_name,
        dpi,
        start_page,
        end_page,
        translate_source_lang,
        translate_target_lang,
        translate_model,
        translate_mode,
        keep_lang,
        enable_translate,
        document_mode,
        creator_name="",
    ):
        captured.append(
            {
                "display_name": display_name,
                "translate_source_lang": translate_source_lang,
                "translate_target_lang": translate_target_lang,
                "translate_model": translate_model,
                "translate_mode": translate_mode,
                "keep_lang": keep_lang,
                "enable_translate": str(enable_translate),
                "document_mode": document_mode,
            }
        )
        return "a" * 32

    monkeypatch.setattr(
        "app.blueprints.main.routes.pipeline.enqueue_job_from_upload",
        fake_enqueue,
    )

    resp = client.post(
        "/upload",
        data={
            "translate": "on",
            "translate_mode": "realtime",
            "source_lang": "auto",
            "target_lang": "en",
            "model": "quick-model",
            "document_mode": "general",
            "pdf": (io.BytesIO(b"%PDF-1.4"), "sample.pdf"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 302
    assert captured == [
        {
            "display_name": "sample",
            "translate_source_lang": "auto",
            "translate_target_lang": "en",
            "translate_model": "quick-model",
            "translate_mode": "realtime",
            "keep_lang": "all",
            "enable_translate": "True",
            "document_mode": "general",
        }
    ]


def test_upload_pdf_overlay_accepts_general_force_translate_mode(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(state, "UPLOAD_ROOT", tmp_path / "uploads")
    captured: list[dict[str, str]] = []

    def fake_enqueue(
        source_pdf,
        display_name,
        dpi,
        start_page,
        end_page,
        translate_source_lang,
        translate_target_lang,
        translate_model,
        translate_mode,
        keep_lang,
        enable_translate,
        document_mode,
        creator_name="",
    ):
        captured.append(
            {
                "display_name": display_name,
                "source_lang": translate_source_lang,
                "document_mode": document_mode,
            }
        )
        return "b" * 32

    monkeypatch.setattr(
        "app.blueprints.main.routes.pipeline.enqueue_job_from_upload",
        fake_enqueue,
    )

    resp = client.post(
        "/upload",
        data={
            "translate": "on",
            "translate_mode": "batch",
            "source_lang": "auto",
            "target_lang": "en",
            "model": "batch-model",
            "document_mode": "general_force",
            "pdf": (io.BytesIO(b"%PDF-1.4"), "sample.pdf"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 302
    assert captured == [
        {
            "display_name": "sample",
            "source_lang": "auto",
            "document_mode": "general_force",
        }
    ]


def test_upload_pdf_overlay_only_other_mode_keeps_explicit_source_lang(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(state, "UPLOAD_ROOT", tmp_path / "uploads")
    captured: list[dict[str, str]] = []

    def fake_enqueue(
        source_pdf,
        display_name,
        dpi,
        start_page,
        end_page,
        translate_source_lang,
        translate_target_lang,
        translate_model,
        translate_mode,
        keep_lang,
        enable_translate,
        document_mode,
        creator_name="",
    ):
        captured.append(
            {
                "display_name": display_name,
                "source_lang": translate_source_lang,
                "document_mode": document_mode,
            }
        )
        return "c" * 32

    monkeypatch.setattr(
        "app.blueprints.main.routes.pipeline.enqueue_job_from_upload",
        fake_enqueue,
    )

    resp = client.post(
        "/upload",
        data={
            "translate": "on",
            "translate_mode": "batch",
            "source_lang": "en",
            "target_lang": "zh",
            "model": "batch-model",
            "document_mode": "other",
            "pdf": (io.BytesIO(b"%PDF-1.4"), "sample.pdf"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 302
    assert captured == [
        {
            "display_name": "sample",
            "source_lang": "en",
            "document_mode": "other",
        }
    ]


def test_upload_pdf_overlay_non_other_mode_forces_auto_source_lang(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(state, "UPLOAD_ROOT", tmp_path / "uploads")
    captured: list[dict[str, str]] = []

    def fake_enqueue(
        source_pdf,
        display_name,
        dpi,
        start_page,
        end_page,
        translate_source_lang,
        translate_target_lang,
        translate_model,
        translate_mode,
        keep_lang,
        enable_translate,
        document_mode,
        creator_name="",
    ):
        captured.append(
            {
                "display_name": display_name,
                "source_lang": translate_source_lang,
                "document_mode": document_mode,
            }
        )
        return "d" * 32

    monkeypatch.setattr(
        "app.blueprints.main.routes.pipeline.enqueue_job_from_upload",
        fake_enqueue,
    )

    resp = client.post(
        "/upload",
        data={
            "translate": "on",
            "translate_mode": "batch",
            "source_lang": "en",
            "target_lang": "zh",
            "model": "batch-model",
            "document_mode": "general",
            "pdf": (io.BytesIO(b"%PDF-1.4"), "sample.pdf"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 302
    assert captured == [
        {
            "display_name": "sample",
            "source_lang": "auto",
            "document_mode": "general",
        }
    ]


def test_upload_rejects_when_submit_quota_exceeded(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(state, "UPLOAD_ROOT", tmp_path / "uploads")
    monkeypatch.setattr(
        "app.blueprints.main.routes.submit_quota.check_and_record_submission",
        lambda creator_name, remote_addr: (False, 3, 12.0),
    )

    resp = client.post(
        "/upload",
        data={
            "translate": "on",
            "translate_mode": "realtime",
            "target_lang": "en",
            "model": "quick-model",
            "document_mode": "general",
            "creator_name": "alice",
            "pdf": (io.BytesIO(b"%PDF-1.4"), "sample.pdf"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 429


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


def test_run_ocr_pipeline_job_skips_paragraph_align_for_general_force(tmp_path, monkeypatch):
    job_id = "d" * 32
    job_dir = tmp_path / "jobs" / job_id
    job_dir.mkdir(parents=True)
    pdf_path = job_dir / f"{job_id}.pdf"
    pdf_path.write_bytes(b"%PDF-1.4")

    monkeypatch.setattr(pipeline.jobs, "set_active_upload", lambda payload: None)
    monkeypatch.setattr(pipeline.jobs, "clear_active_upload", lambda current_job_id: None)
    monkeypatch.setattr(pipeline.jobs, "set_job_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline.jobs, "write_batch_config", lambda *args, **kwargs: None)
    monkeypatch.setattr(pipeline.jobs, "write_batch_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        pipeline.jobs.job_store,
        "get_job",
        lambda current_job_id: None,
    )
    monkeypatch.setattr(
        pipeline.jobs.job_store,
        "deserialize_payload",
        lambda record: {},
    )
    monkeypatch.setattr(
        pipeline.jobs.job_store,
        "update_job",
        lambda *args, **kwargs: None,
    )

    captured_modes: list[str] = []
    monkeypatch.setattr(
        pipeline,
        "run_pipeline",
        lambda **kwargs: captured_modes.append(str(kwargs.get("document_mode") or "")),
    )

    called_align: list[Path] = []
    monkeypatch.setattr(
        pipeline.ocr,
        "update_pp_json_should_translate",
        lambda current_job_dir: called_align.append(Path(current_job_dir)),
    )

    pipeline.run_ocr_pipeline_job(
        job_id=job_id,
        job_dir=job_dir,
        pdf_path=pdf_path,
        dpi=200,
        start_page=1,
        end_page=None,
        translate_source_lang="auto",
        translate_target_lang="en",
        translate_model="dummy-model",
        translate_mode="batch",
        keep_lang="all",
        enable_translate=False,
        document_mode="general_force",
        cancel_event=threading.Event(),
    )

    assert captured_modes == ["general_force"]
    assert called_align == []


def test_glossary_get(client):
    resp = client.get("/api/glossary")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert isinstance(payload, dict)
    assert payload.get("ok") is True


def test_document_templates_crud(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "TEMPLATE_JOB_ROOT", tmp_path / "templates" / "jobs")

    resp = client.get("/api/document-templates")
    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["templates"] == []

    create_resp = client.post(
        "/api/document-templates",
        json={
            "name": "表單 A",
            "pages": [
                {
                    "page_index_0based": 0,
                    "boxes": [
                        {
                            "x_ratio": 0.1,
                            "y_ratio": 0.2,
                            "w_ratio": 0.3,
                            "h_ratio": 0.04,
                            "text": "Inspection Frequency",
                            "font_size": 18,
                            "color": "#112233",
                            "text_align": "center",
                            "rotation": 90,
                            "no_clip": True,
                        }
                    ],
                }
            ],
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.get_json()["template"]
    assert created["name"] == "表單 A"
    assert created["status"] == "saved"
    assert created["pages"][0]["boxes"][0]["rotation"] == 90
    assert created["pages"][0]["boxes"][0]["text_align"] == "center"

    stored = client.get("/api/document-templates").get_json()["templates"]
    assert stored[0]["pages"][0]["boxes"][0]["x_ratio"] == 0.1

    list_resp = client.get("/api/document-templates")
    assert list_resp.status_code == 200
    listed = list_resp.get_json()["templates"]
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]

    delete_resp = client.delete(f"/api/document-templates/{created['id']}")
    assert delete_resp.status_code == 200
    assert delete_resp.get_json()["deleted"] is True

    final_resp = client.get("/api/document-templates")
    assert final_resp.get_json()["templates"] == []


def test_delete_document_template_removes_source_job_dir(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "TEMPLATE_JOB_ROOT", tmp_path / "templates" / "jobs")
    template_job_id = "7" * 32
    template_job_dir = state.TEMPLATE_JOB_ROOT / template_job_id
    template_job_dir.mkdir(parents=True)
    jobs.write_job_meta(
        template_job_dir,
        {
            "job_name": "template-source",
            "job_type": "template_source",
            "document_mode": "scanned",
        },
    )

    create_resp = client.post(
        "/api/document-templates",
        json={
            "name": "表單 A",
            "source_job_id": template_job_id,
            "pages": [
                {
                    "page_index_0based": 0,
                    "boxes": [
                        {
                            "x_ratio": 0.1,
                            "y_ratio": 0.2,
                            "w_ratio": 0.3,
                            "h_ratio": 0.04,
                            "text": "Inspection Frequency",
                        }
                    ],
                }
            ],
        },
    )
    template_id = create_resp.get_json()["template"]["id"]

    delete_resp = client.delete(f"/api/document-templates/{template_id}")
    assert delete_resp.status_code == 200
    assert delete_resp.get_json()["deleted"] is True
    assert not template_job_dir.exists()


def test_update_merge_notice_status(client, tmp_path, monkeypatch):
    job_id = "c" * 32
    job_dir = tmp_path / "jobs" / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    jobs.write_merge_notices(
        job_dir,
        [
            {
                "notice_id": "p0001-l0001__p0001-l0002",
                "status": "pending",
                "primary_custom_id": "p0001-l0001",
                "secondary_custom_id": "p0001-l0002",
            }
        ],
    )

    resp = client.post(
        f"/api/job/{job_id}/merge-notices/p0001-l0001__p0001-l0002",
        json={"status": "accepted"},
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["notice"]["status"] == "accepted"
    assert jobs.load_merge_notices(job_dir)[0]["status"] == "accepted"


def test_batch_restore_uses_realtime_debug_translations_when_output_missing(client, tmp_path, monkeypatch):
    job_id = "e" * 32
    job_dir = tmp_path / "jobs" / job_id
    (job_dir / "realtime_debug" / "chunks" / "chunk_0001").mkdir(parents=True)
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")

    (job_dir / "batch_config.json").write_text(
        json.dumps({"document_mode": "general_force", "target_lang": "en"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (job_dir / "realtime_debug" / "chunks" / "chunk_0001" / "parsed_translations.json").write_text(
        json.dumps({"p0000-b0001": "Recovered header"}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.load_ocr_pages",
        lambda current_job_dir: [{"page_index_0based": 0, "rec_texts": [], "rec_polys": []}],
    )
    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.load_pp_pages",
        lambda current_job_dir: {},
    )
    monkeypatch.setattr(
        "app.blueprints.api.routes.batch.build_edits_payload_from_translations",
        lambda ocr_pages, translations, **kwargs: {
            "pages": [
                {
                    "page_index_0based": 0,
                    "boxes": [{"id": 200001, "text": translations.get("p0000-b0001", "")}],
                }
            ]
        },
    )
    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.apply_edits_to_pdf",
        lambda current_job_id, current_job_dir, edits: Path(current_job_dir) / "edited.pdf",
    )

    resp = client.post(f"/api/job/{job_id}/batch-restore")

    assert resp.status_code == 200
    saved = json.loads((job_dir / "edits.json").read_text(encoding="utf-8"))
    assert saved["pages"][0]["boxes"][0]["text"] == "Recovered header"


def test_save_job_writes_form_tm_from_editor_edits(client, tmp_path, monkeypatch):
    job_id = "a" * 32
    job_dir = tmp_path / "jobs" / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_PATH", tmp_path / "translation_memory.json")
    monkeypatch.setattr(state, "PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY", True)

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
                        "text_align": "right",
                        "rotation": 90,
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
    saved = json.loads((job_dir / "edits.json").read_text(encoding="utf-8"))
    assert saved["pages"][0]["boxes"][0]["text_align"] == "right"
    assert saved["pages"][0]["boxes"][0]["rotation"] == 90

    memory = json.loads(state.TRANSLATION_MEMORY_PATH.read_text(encoding="utf-8"))
    entry = memory["form|en|表格內容"]
    assert entry["source_text"] == "表格內容"
    assert entry["target_text"] == "Corrected translation"
    assert entry["target_lang"] == "en"
    assert entry["document_mode"] == "form"
    assert entry["source"] == "editor"


def test_upload_word_workspace_accepts_doc(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(state, "UPLOAD_ROOT", tmp_path / "uploads")
    captured: list[dict[str, str]] = []

    def fake_enqueue(source_path, display_name, source_lang, target_lang, retain_terms_raw=None):
        captured.append(
            {
                "source_name": Path(source_path).name,
                "display_name": display_name,
                "source_lang": source_lang,
                "target_lang": target_lang,
            }
        )
        return "b" * 32

    monkeypatch.setattr(
        "app.blueprints.main.routes.word_translate.enqueue_word_job_from_upload",
        fake_enqueue,
    )

    resp = client.post(
        "/upload-word-workspace",
        data={
            "source_lang": "auto",
            "target_lang": "en",
            "docx": (io.BytesIO(b"legacy doc"), "legacy.doc"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 302
    assert len(captured) == 1
    assert Path(captured[0]["source_name"]).suffix == ".doc"
    assert captured[0]["display_name"] == "legacy"
    assert captured[0]["source_lang"] == "auto"
    assert captured[0]["target_lang"] == "en"


def test_upload_word_workspace_preserves_chinese_display_name(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(state, "UPLOAD_ROOT", tmp_path / "uploads")
    captured: list[dict[str, str]] = []

    def fake_enqueue(source_path, display_name, source_lang, target_lang, retain_terms_raw=None):
        captured.append(
            {
                "source_name": Path(source_path).name,
                "display_name": display_name,
                "source_lang": source_lang,
                "target_lang": target_lang,
            }
        )
        return "b" * 32

    monkeypatch.setattr(
        "app.blueprints.main.routes.word_translate.enqueue_word_job_from_upload",
        fake_enqueue,
    )

    resp = client.post(
        "/upload-word-workspace",
        data={
            "source_lang": "auto",
            "target_lang": "en",
            "docx": (io.BytesIO(b"docx"), "中文檔名.docx"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 302
    assert len(captured) == 1
    assert Path(captured[0]["source_name"]).suffix == ".docx"
    assert captured[0]["display_name"] == "中文檔名"
    assert captured[0]["source_lang"] == "auto"
    assert captured[0]["target_lang"] == "en"


def test_upload_doc_workspace_passes_source_language(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(state, "UPLOAD_ROOT", tmp_path / "uploads")
    captured: list[dict[str, str]] = []

    def fake_enqueue(source_path, display_name, source_lang, target_lang):
        captured.append(
            {
                "source_name": Path(source_path).name,
                "display_name": display_name,
                "source_lang": source_lang,
                "target_lang": target_lang,
            }
        )
        return "c" * 32

    monkeypatch.setattr(
        "app.blueprints.main.routes.doc_workspace.enqueue_doc_job_from_upload",
        fake_enqueue,
    )

    resp = client.post(
        "/upload-doc-workspace",
        data={
            "source_lang": "en",
            "target_lang": "zh",
            "pdf": (io.BytesIO(b"%PDF-1.4"), "source.pdf"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 302
    assert captured == [
        {
            "source_name": captured[0]["source_name"],
            "display_name": "source",
            "source_lang": "en",
            "target_lang": "zh",
        }
    ]


def test_build_download_name_preserves_chinese_job_name():
    assert jobs.build_download_name("a" * 32, "中文檔名", ext="pdf", suffix="translate") == "中文檔名_translate.pdf"
    assert jobs.build_docx_name("a" * 32, "中文檔名") == "中文檔名_translated.docx"


def test_retranslate_region_replaces_overlapping_auto_boxes_only(client, tmp_path, monkeypatch):
    job_id = "b" * 32
    job_dir = tmp_path / "jobs" / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")

    (job_dir / "batch_config.json").write_text(
        json.dumps(
            {
                "document_mode": "form",
                "target_lang": "en",
                "model": "fake-model",
                "system_prompt": "translate",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (job_dir / "edits.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_index_0based": 0,
                        "boxes": [
                            {
                                "id": 100000,
                                "deleted": False,
                                "bbox": {"x": 10, "y": 10, "w": 80, "h": 20},
                                "text": "old auto",
                                "auto_generated": True,
                            },
                            {
                                "id": 5,
                                "deleted": False,
                                "bbox": {"x": 12, "y": 12, "w": 50, "h": 16},
                                "text": "manual keep",
                                "auto_generated": False,
                            },
                        ],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.run_region_ocr",
        lambda current_job_dir, page_idx, bbox: {
            "page_index_0based": page_idx,
            "region_bbox": bbox,
            "rec_polys": [
                [[15, 15], [65, 15], [65, 25], [15, 25]],
                [[15, 28], [90, 28], [90, 40], [15, 40]],
            ],
            "rec_texts": ["補翻來源第一行", "補翻來源第二行"],
            "rec_scores": [0.99, 0.99],
        },
    )
    monkeypatch.setattr(
        "app.blueprints.api.routes.batch.translate_texts_for_region",
        lambda texts, **kwargs: ["merged paragraph translation"],
    )
    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.apply_edits_to_pdf",
        lambda current_job_id, current_job_dir, edits: Path(current_job_dir) / "edited.pdf",
    )

    resp = client.post(
        f"/api/job/{job_id}/retranslate-region",
        json={
            "page_index_0based": 0,
            "bbox": {"x": 0, "y": 0, "w": 120, "h": 60},
            "replace_existing": True,
        },
    )
    assert resp.status_code == 200

    saved = json.loads((job_dir / "edits.json").read_text(encoding="utf-8"))
    boxes = saved["pages"][0]["boxes"]
    assert boxes[0]["deleted"] is True
    assert boxes[1]["deleted"] is False
    assert boxes[1]["text"] == "manual keep"
    assert boxes[2]["text"] == "merged paragraph translation"
    assert boxes[2]["auto_generated"] is True
    assert boxes[2]["no_clip"] is True
    assert boxes[2]["text_align"] == "left"
    assert boxes[2]["rotation"] == 0
    assert boxes[2]["source"] == "manual_region_retranslate"
    assert boxes[2]["tm_source_text"] == "補翻來源第一行\n補翻來源第二行"


def test_retranslate_region_uses_job_model_for_translation(client, tmp_path, monkeypatch):
    job_id = "e" * 32
    job_dir = tmp_path / "jobs" / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(state, "DOC_TRANSLATE_MODEL", "doc-model")
    monkeypatch.setattr(state, "PDF_REALTIME_TRANSLATE_MODEL", "realtime-model")

    (job_dir / "batch_config.json").write_text(
        json.dumps(
            {
                "document_mode": "general_force",
                "target_lang": "en",
                "model": "job-model",
                "system_prompt": "translate",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (job_dir / "edits.json").write_text(
        json.dumps({"pages": [{"page_index_0based": 0, "boxes": []}]}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.run_region_ocr",
        lambda current_job_dir, page_idx, bbox: {
            "page_index_0based": page_idx,
            "region_bbox": bbox,
            "rec_polys": [[[15, 15], [65, 15], [65, 25], [15, 25]]],
            "rec_texts": ["補翻來源"],
            "rec_scores": [0.99],
        },
    )

    captured: dict[str, object] = {}

    def fake_translate(texts, **kwargs):
        captured["texts"] = texts
        captured["model_name"] = kwargs.get("model_name")
        return ["translated"]

    monkeypatch.setattr(
        "app.blueprints.api.routes.batch.translate_texts_for_region",
        fake_translate,
    )
    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.apply_edits_to_pdf",
        lambda current_job_id, current_job_dir, edits: Path(current_job_dir) / "edited.pdf",
    )

    resp = client.post(
        f"/api/job/{job_id}/retranslate-region",
        json={
            "page_index_0based": 0,
            "bbox": {"x": 0, "y": 0, "w": 120, "h": 60},
            "replace_existing": False,
        },
    )

    assert resp.status_code == 200
    assert captured["texts"] == ["補翻來源"]
    assert captured["model_name"] == "job-model"


def test_region_ocr_preview_returns_image_and_ocr_text(client, tmp_path, monkeypatch):
    job_id = "c" * 32
    job_dir = tmp_path / "jobs" / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.run_region_ocr",
        lambda current_job_dir, page_idx, bbox: {
            "page_index_0based": page_idx,
            "region_bbox": bbox,
            "merged_bbox": {"x": 10, "y": 10, "w": 50, "h": 25},
            "image_data_url": "data:image/png;base64,AAA",
            "rec_polys": [
                [[10, 10], [20, 10], [20, 20], [10, 20]],
                [[30, 10], [40, 10], [40, 20], [30, 20]],
            ],
            "rec_texts": ["第一行", "第二行"],
            "rec_scores": [0.9, 0.9],
        },
    )

    resp = client.post(
        f"/api/job/{job_id}/region-ocr-preview",
        json={
            "page_index_0based": 0,
            "bbox": {"x": 0, "y": 0, "w": 120, "h": 60},
        },
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["ocr_lines"] == ["第一行第二行"]
    assert payload["source_text"] == "第一行第二行"
    assert payload["image_data_url"] == "data:image/png;base64,AAA"
    assert payload["ocr_items"][0]["text"] == "第一行"


def test_retranslate_box_updates_only_target_box(client, tmp_path, monkeypatch):
    job_id = "f" * 32
    job_dir = tmp_path / "jobs" / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")

    (job_dir / "batch_config.json").write_text(
        json.dumps(
            {
                "document_mode": "general_force",
                "target_lang": "en",
                "model": "fake-model",
                "system_prompt": "translate",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (job_dir / "edits.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_index_0based": 0,
                        "boxes": [
                            {
                                "id": 200001,
                                "deleted": False,
                                "bbox": {"x": 10, "y": 10, "w": 80, "h": 20},
                                "text": "Old translation",
                                "auto_generated": True,
                                "tm_source_text": "舊原文",
                            },
                            {
                                "id": 200002,
                                "deleted": False,
                                "bbox": {"x": 10, "y": 40, "w": 80, "h": 20},
                                "text": "Keep me",
                                "auto_generated": True,
                                "tm_source_text": "另一段",
                            },
                        ],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.blueprints.api.routes.batch.translate_texts_for_region",
        lambda texts, **kwargs: ["Updated translation"],
    )
    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.apply_edits_to_pdf",
        lambda current_job_id, current_job_dir, edits: Path(current_job_dir) / "edited.pdf",
    )

    resp = client.post(
        f"/api/job/{job_id}/retranslate-box",
        json={
            "page_index_0based": 0,
            "box_id": 200001,
            "source_text": "修正後原文",
        },
    )

    assert resp.status_code == 200
    saved = json.loads((job_dir / "edits.json").read_text(encoding="utf-8"))
    boxes = saved["pages"][0]["boxes"]
    assert boxes[0]["text"] == "Updated translation"
    assert boxes[0]["tm_source_text"] == "修正後原文"
    assert boxes[0]["source"] == "manual_box_retranslate"
    assert boxes[1]["text"] == "Keep me"


def test_retranslate_boxes_updates_multiple_targets(client, tmp_path, monkeypatch):
    job_id = "9" * 32
    job_dir = tmp_path / "jobs" / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")

    (job_dir / "batch_config.json").write_text(
        json.dumps(
            {
                "document_mode": "general_force",
                "target_lang": "en",
                "model": "fake-model",
                "system_prompt": "translate",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (job_dir / "edits.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_index_0based": 0,
                        "boxes": [
                            {
                                "id": 200001,
                                "deleted": False,
                                "bbox": {"x": 10, "y": 10, "w": 80, "h": 20},
                                "text": "Box one",
                                "auto_generated": False,
                            },
                            {
                                "id": 200002,
                                "deleted": False,
                                "bbox": {"x": 10, "y": 40, "w": 80, "h": 20},
                                "text": "Box two",
                                "auto_generated": False,
                            },
                        ],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.blueprints.api.routes.batch.translate_texts_for_region",
        lambda texts, **kwargs: [f"Translated::{text}" for text in texts],
    )
    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.apply_edits_to_pdf",
        lambda current_job_id, current_job_dir, edits: Path(current_job_dir) / "edited.pdf",
    )

    resp = client.post(
        f"/api/job/{job_id}/retranslate-boxes",
        json={
            "targets": [
                {
                    "page_index_0based": 0,
                    "box_id": 200001,
                    "source_text": "第一段",
                },
                {
                    "page_index_0based": 0,
                    "box_id": 200002,
                    "source_text": "第二段",
                },
            ]
        },
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["updated_count"] == 2
    assert len(payload["items"]) == 2
    saved = json.loads((job_dir / "edits.json").read_text(encoding="utf-8"))
    boxes = saved["pages"][0]["boxes"]
    assert boxes[0]["text"] == "Translated::第一段"
    assert boxes[0]["tm_source_text"] == "第一段"
    assert boxes[1]["text"] == "Translated::第二段"
    assert boxes[1]["tm_source_text"] == "第二段"


def test_glossary_retranslate_updates_matching_boxes_only_text(client, tmp_path, monkeypatch):
    job_id = "f" * 32
    job_dir = tmp_path / "jobs" / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")

    (job_dir / "batch_config.json").write_text(
        json.dumps(
            {
                "document_mode": "general_force",
                "target_lang": "en",
                "model": "fake-model",
                "system_prompt": "translate",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    (job_dir / "edits.json").write_text(
        json.dumps(
            {
                "pages": [
                    {
                        "page_index_0based": 0,
                        "boxes": [
                            {
                                "id": 200001,
                                "deleted": False,
                                "bbox": {"x": 10, "y": 10, "w": 80, "h": 20},
                                "text": "Old translation",
                                "auto_generated": True,
                                "font_size": 19,
                                "color": "#112233",
                                "align": "center",
                                "tm_source_text": "這段有髖臼杯",
                                "tm_source_normalized": "這段有髖臼杯",
                            },
                            {
                                "id": 200003,
                                "deleted": False,
                                "bbox": {"x": 10, "y": 25, "w": 80, "h": 20},
                                "text": "Another old translation",
                                "auto_generated": True,
                                "font_size": 21,
                                "color": "#445566",
                                "align": "right",
                                "tm_source_text": "另一段也有髖臼杯",
                                "tm_source_normalized": "另一段也有髖臼杯",
                            },
                            {
                                "id": 200002,
                                "deleted": False,
                                "bbox": {"x": 10, "y": 40, "w": 80, "h": 20},
                                "text": "Keep me",
                                "auto_generated": True,
                                "font_size": 17,
                                "color": "#778899",
                                "align": "left",
                                "tm_source_text": "另一段",
                                "tm_source_normalized": "另一段",
                            },
                        ],
                    }
                ]
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.blueprints.api.routes.glossary.load_combined_glossary",
        lambda: [("髖臼杯", "acetabular cup")],
    )
    monkeypatch.setattr(
        "app.blueprints.api.routes.batch.translate_texts_for_region",
        lambda texts, **kwargs: [f"Retranslated::{texts[0]}"],
    )
    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.apply_edits_to_pdf",
        lambda current_job_id, current_job_dir, edits: Path(current_job_dir) / "edited.pdf",
    )

    resp = client.post(
        f"/api/job/{job_id}/glossary-retranslate",
        json={"cn": "髖臼杯"},
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["updated_count"] == 2
    saved = json.loads((job_dir / "edits.json").read_text(encoding="utf-8"))
    boxes = saved["pages"][0]["boxes"]
    assert boxes[0]["text"] == "Retranslated::這段有髖臼杯"
    assert boxes[0]["bbox"] == {"x": 10, "y": 10, "w": 80, "h": 20}
    assert boxes[0]["font_size"] == 19
    assert boxes[0]["color"] == "#112233"
    assert boxes[0]["align"] == "center"
    assert boxes[0]["tm_source_text"] == "這段有髖臼杯"
    assert boxes[1]["text"] == "Retranslated::另一段也有髖臼杯"
    assert boxes[1]["bbox"] == {"x": 10, "y": 25, "w": 80, "h": 20}
    assert boxes[1]["font_size"] == 21
    assert boxes[1]["color"] == "#445566"
    assert boxes[1]["align"] == "right"
    assert boxes[2]["text"] == "Keep me"
