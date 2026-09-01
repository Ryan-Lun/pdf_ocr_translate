from __future__ import annotations

import json
from pathlib import Path

from app.services import job_store, state, translation_memory


def test_apply_consistency_updates_matching_boxes_and_tm(client, tmp_path, monkeypatch):
    job_id = "d" * 32
    job_dir = tmp_path / "jobs" / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_PATH", tmp_path / "translation_memory.json")
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_ENABLED", True)
    monkeypatch.setattr(state, "PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY", True)
    with job_store.session_scope() as session:
        session.query(job_store.TranslationMemoryEntryRecord).delete()

    (job_dir / "batch_config.json").write_text(
        json.dumps(
            {"document_mode": "form", "source_lang": "zh-tw", "target_lang": "en"},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.apply_edits_to_pdf",
        lambda current_job_id, current_job_dir, edits: Path(current_job_dir) / "edited.pdf",
    )

    payload = {
        "pages": [
            {
                "page_index_0based": 0,
                "boxes": [
                    {
                        "id": 1,
                        "deleted": False,
                        "bbox": {"x": 0, "y": 0, "w": 100, "h": 20},
                        "text": "Alpha",
                        "font_size": 16,
                        "no_clip": False,
                        "color": "#0000ff",
                        "text_align": "left",
                        "auto_generated": True,
                        "tm_source_text": "檢查頻率",
                        "tm_source_normalized": "檢查頻率",
                        "tm_target_lang": "en",
                        "tm_document_mode": "form",
                    },
                    {
                        "id": 2,
                        "deleted": False,
                        "bbox": {"x": 0, "y": 30, "w": 100, "h": 20},
                        "text": "Beta",
                        "font_size": 16,
                        "no_clip": False,
                        "color": "#0000ff",
                        "text_align": "left",
                        "auto_generated": True,
                        "tm_source_text": "檢查頻率",
                        "tm_source_normalized": "檢查頻率",
                        "tm_target_lang": "en",
                        "tm_document_mode": "form",
                    },
                    {
                        "id": 3,
                        "deleted": False,
                        "bbox": {"x": 0, "y": 60, "w": 100, "h": 20},
                        "text": "Gamma",
                        "font_size": 16,
                        "no_clip": False,
                        "color": "#0000ff",
                        "text_align": "left",
                        "auto_generated": True,
                        "tm_source_text": "其他詞",
                        "tm_source_normalized": "其他詞",
                        "tm_target_lang": "en",
                        "tm_document_mode": "form",
                    },
                ],
            }
        ],
        "source_normalized": "檢查頻率",
        "target_text": "Inspection frequency",
        "sync_to_tm": True,
    }

    resp = client.post(f"/api/job/{job_id}/consistency/apply", json=payload)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["updated_count"] == 2

    saved = json.loads((job_dir / "edits.json").read_text(encoding="utf-8"))
    boxes = saved["pages"][0]["boxes"]
    assert boxes[0]["text"] == "Inspection frequency"
    assert boxes[1]["text"] == "Inspection frequency"
    assert boxes[2]["text"] == "Gamma"

    entry = translation_memory.find_sql_entry(
        "檢查頻率",
        source_lang="zh-tw",
        target_lang="en",
        document_mode="form",
    )
    assert entry is not None
    assert entry.target_text == "Inspection frequency"
    assert entry.source == "editor_consistency"
    assert entry.source_job_id == job_id
    assert entry.source_metadata == {"updated_count": 2}
    assert not state.TRANSLATION_MEMORY_PATH.exists()
