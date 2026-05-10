from __future__ import annotations

import io
import json
from pathlib import Path

from app.services import jobs, state


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
