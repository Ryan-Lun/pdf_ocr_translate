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
            "document_mode": "general_force",
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

    def fake_enqueue(source_path, display_name, target_lang, retain_terms_raw=None):
        captured.append(
            {
                "source_name": Path(source_path).name,
                "display_name": display_name,
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
            "target_lang": "en",
            "docx": (io.BytesIO(b"legacy doc"), "legacy.doc"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 302
    assert len(captured) == 1
    assert Path(captured[0]["source_name"]).suffix == ".doc"
    assert captured[0]["display_name"] == "legacy"
    assert captured[0]["target_lang"] == "en"


def test_upload_word_workspace_preserves_chinese_display_name(client, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(state, "UPLOAD_ROOT", tmp_path / "uploads")
    captured: list[dict[str, str]] = []

    def fake_enqueue(source_path, display_name, target_lang, retain_terms_raw=None):
        captured.append(
            {
                "source_name": Path(source_path).name,
                "display_name": display_name,
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
            "target_lang": "en",
            "docx": (io.BytesIO(b"docx"), "中文檔名.docx"),
        },
        content_type="multipart/form-data",
    )

    assert resp.status_code == 302
    assert len(captured) == 1
    assert Path(captured[0]["source_name"]).suffix == ".docx"
    assert captured[0]["display_name"] == "中文檔名"
    assert captured[0]["target_lang"] == "en"


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
    assert boxes[2]["source"] == "manual_region_retranslate"
    assert boxes[2]["tm_source_text"] == "補翻來源第一行\n補翻來源第二行"


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
    assert payload["ocr_lines"] == ["第一行", "第二行"]
    assert payload["source_text"] == "第一行\n第二行"
    assert payload["image_data_url"] == "data:image/png;base64,AAA"
    assert payload["ocr_items"][0]["text"] == "第一行"
