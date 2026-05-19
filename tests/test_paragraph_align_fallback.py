from __future__ import annotations

from ocr_pipeline import paragraph_align


def test_align_and_update_json_skips_similarity_when_model_unavailable(monkeypatch):
    monkeypatch.setattr(paragraph_align, "_model", None)
    monkeypatch.setattr(paragraph_align, "_model_load_failed", True)

    payload = {
        "parsing_res_list": [
            {
                "block_label": "text",
                "block_content": "中文段落",
                "block_bbox": [0, 0, 100, 40],
            },
            {
                "block_label": "text",
                "block_content": "English paragraph",
                "block_bbox": [0, 60, 100, 100],
            },
        ]
    }

    updated = paragraph_align.align_and_update_json(payload)

    assert updated["bilingual_pairs"] == []
    assert updated["parsing_res_list"][0]["should_translate"] is True
    assert updated["parsing_res_list"][1]["should_translate"] is True
