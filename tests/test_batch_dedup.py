from __future__ import annotations

from app.services.batch import build_batch_items, build_edits_payload_from_translations


def test_table_paragraph_blocks_are_skipped_when_merged_cells_exist():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": [],
            "rec_polys": [],
        }
    ]
    pp_pages = {
        0: {
            "parsing_res_list": [
                {
                    "block_content": "表格段落",
                    "block_bbox": [10, 10, 90, 90],
                    "should_translate": True,
                    "block_label": "text",
                }
            ],
            "table_res_list": [
                {
                    "cell_box_list": [[0, 0, 100, 100]],
                    "merged_cells": [
                        {
                            "cell_box": [10, 10, 90, 90],
                            "merged_text": "表格段落",
                            "should_translate": True,
                        }
                    ],
                }
            ],
        }
    }

    items, alias_map, key_map, prefilled = build_batch_items(
        ocr_pages,
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[],
        pp_pages=pp_pages,
    )

    assert [item["custom_id"] for item in items] == ["p0000-c0000"]
    assert alias_map == {}
    assert key_map == {"p0000-c0000": "表格段落"}
    assert prefilled == {}


def test_edits_payload_does_not_duplicate_table_paragraph_blocks():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": [],
            "rec_polys": [],
        }
    ]
    pp_pages = {
        0: {
            "parsing_res_list": [
                {
                    "block_content": "表格段落",
                    "block_bbox": [10, 10, 90, 90],
                    "should_translate": True,
                    "block_label": "text",
                }
            ],
            "table_res_list": [
                {
                    "cell_box_list": [[0, 0, 100, 100]],
                    "merged_cells": [
                        {
                            "cell_box": [10, 10, 90, 90],
                            "merged_text": "表格段落",
                            "should_translate": True,
                        }
                    ],
                }
            ],
        }
    }
    translations = {
        "p0000-b0000": "translated paragraph",
        "p0000-c0000": "translated cell",
    }

    payload = build_edits_payload_from_translations(
        ocr_pages,
        translations,
        pp_pages=pp_pages,
    )

    boxes = payload["pages"][0]["boxes"]
    assert len(boxes) == 1
    assert boxes[0]["id"] == 100000
    assert boxes[0]["text"] == "translated cell"
    assert boxes[0]["auto_generated"] is True
