from __future__ import annotations

import json
from pathlib import Path

from app.services import state, translation_memory


def test_apply_paragraph_term_updates_matching_boxes_and_tm(client, tmp_path, monkeypatch):
    job_id = "e" * 32
    job_dir = tmp_path / "jobs" / job_id
    job_dir.mkdir(parents=True)
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_PATH", tmp_path / "translation_memory.json")

    (job_dir / "batch_config.json").write_text(
        json.dumps({"document_mode": "form", "target_lang": "en"}, ensure_ascii=False, indent=2),
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
                        "bbox": {"x": 0, "y": 0, "w": 200, "h": 60},
                        "text": "Please verify the check frequency before release.",
                        "font_size": 16,
                        "no_clip": False,
                        "color": "#0000ff",
                        "text_align": "left",
                        "auto_generated": True,
                        "tm_source_text": "出貨前請確認檢查頻率是否正確。",
                        "tm_source_normalized": "出貨前請確認檢查頻率是否正確。",
                        "tm_target_lang": "en",
                        "tm_document_mode": "form",
                    },
                    {
                        "id": 2,
                        "deleted": False,
                        "bbox": {"x": 0, "y": 80, "w": 200, "h": 60},
                        "text": "The check frequency must be recorded weekly.",
                        "font_size": 16,
                        "no_clip": False,
                        "color": "#0000ff",
                        "text_align": "left",
                        "auto_generated": True,
                        "tm_source_text": "每週都要記錄檢查頻率。",
                        "tm_source_normalized": "每週都要記錄檢查頻率。",
                        "tm_target_lang": "en",
                        "tm_document_mode": "form",
                    },
                    {
                        "id": 3,
                        "deleted": False,
                        "bbox": {"x": 0, "y": 160, "w": 200, "h": 60},
                        "text": "This paragraph is unrelated.",
                        "font_size": 16,
                        "no_clip": False,
                        "color": "#0000ff",
                        "text_align": "left",
                        "auto_generated": True,
                        "tm_source_text": "這段和其他術語無關。",
                        "tm_source_normalized": "這段和其他術語無關。",
                        "tm_target_lang": "en",
                        "tm_document_mode": "form",
                    },
                ],
            }
        ],
        "source_term": "檢查頻率",
        "replace_from": "check frequency",
        "replace_to": "inspection frequency",
        "sync_to_tm": True,
    }

    resp = client.post(f"/api/job/{job_id}/paragraph-term/apply", json=payload)
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["ok"] is True
    assert body["updated_count"] == 2

    saved = json.loads((job_dir / "edits.json").read_text(encoding="utf-8"))
    boxes = saved["pages"][0]["boxes"]
    assert boxes[0]["text"] == "Please verify the inspection frequency before release."
    assert boxes[1]["text"] == "The inspection frequency must be recorded weekly."
    assert boxes[2]["text"] == "This paragraph is unrelated."

    memory = translation_memory.load_translation_memory()
    entry = memory[translation_memory.make_tm_key("檢查頻率", "en", "form")]
    assert entry["target_text"] == "inspection frequency"
    assert entry["source"] == "editor_paragraph_term"
