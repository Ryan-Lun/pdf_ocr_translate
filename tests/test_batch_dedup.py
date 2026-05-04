from __future__ import annotations

import json
import time

from app.services.batch import build_batch_items, build_edits_payload_from_translations
from app.services import state, translation_memory


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
    assert key_map == {
        "p0000-c0000": {
            "source_text": "表格段落",
            "source_normalized": "表格段落",
        }
    }
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


def test_table_merged_cells_win_over_overlapping_paragraph_blocks():
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
                    "block_content": "重疊段落",
                    "block_bbox": [0, 0, 200, 20],
                    "should_translate": True,
                    "block_label": "text",
                }
            ],
            "table_res_list": [
                {
                    "cell_box_list": [[150, 0, 250, 20]],
                    "merged_cells": [
                        {
                            "cell_box": [150, 0, 250, 20],
                            "merged_text": "表格內容",
                            "should_translate": True,
                        }
                    ],
                }
            ],
        }
    }

    items, _, key_map, _ = build_batch_items(
        ocr_pages,
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[],
        pp_pages=pp_pages,
    )

    assert [item["custom_id"] for item in items] == ["p0000-c0000"]
    assert key_map == {
        "p0000-c0000": {
            "source_text": "表格內容",
            "source_normalized": "表格內容",
        }
    }


def test_form_mode_prefers_merged_cells_over_paragraph_blocks_and_ocr_lines():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["表格 OCR 行"],
            "rec_polys": [
                [[10, 10], [90, 10], [90, 30], [10, 30]],
            ],
        }
    ]
    pp_pages = {
        0: {
            "parsing_res_list": [
                {
                    "block_content": "段落區塊",
                    "block_bbox": [0, 0, 120, 40],
                    "should_translate": True,
                    "block_label": "text",
                }
            ],
            "table_res_list": [
                {
                    "cell_box_list": [[0, 0, 120, 40]],
                    "merged_cells": [
                        {
                            "cell_box": [10, 10, 90, 30],
                            "merged_text": "表格合併儲存格",
                            "should_translate": True,
                        }
                    ],
                }
            ],
        }
    }

    items, _, key_map, _ = build_batch_items(
        ocr_pages,
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[],
        pp_pages=pp_pages,
        document_mode="form",
    )

    assert [item["custom_id"] for item in items] == ["p0000-c0000"]
    assert key_map == {
        "p0000-c0000": {
            "source_text": "表格合併儲存格",
            "source_normalized": "表格合併儲存格",
        }
    }


def test_form_mode_payload_prefers_merged_cells_over_paragraph_blocks_and_ocr_lines():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["表格 OCR 行"],
            "rec_polys": [
                [[10, 10], [90, 10], [90, 30], [10, 30]],
            ],
        }
    ]
    pp_pages = {
        0: {
            "parsing_res_list": [
                {
                    "block_content": "段落區塊",
                    "block_bbox": [0, 0, 120, 40],
                    "should_translate": True,
                    "block_label": "text",
                }
            ],
            "table_res_list": [
                {
                    "cell_box_list": [[0, 0, 120, 40]],
                    "merged_cells": [
                        {
                            "cell_box": [10, 10, 90, 30],
                            "merged_text": "表格合併儲存格",
                            "should_translate": True,
                        }
                    ],
                }
            ],
        }
    }
    translations = {
        "p0000-l0000": "translated line",
        "p0000-b0000": "translated block",
        "p0000-c0000": "translated cell",
    }

    payload = build_edits_payload_from_translations(
        ocr_pages,
        translations,
        pp_pages=pp_pages,
        document_mode="form",
    )

    boxes = payload["pages"][0]["boxes"]
    assert len(boxes) == 1
    assert boxes[0]["id"] == 100000
    assert boxes[0]["text"] == "translated cell"


def test_general_document_mode_skips_bilingual_merged_cells_for_batch_items():
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
                    "block_content": "表格內容",
                    "block_bbox": [10, 10, 90, 90],
                    "should_translate": False,
                    "block_label": "table",
                }
            ],
            "table_res_list": [
                {
                    "cell_box_list": [[0, 0, 100, 100]],
                    "merged_cells": [
                        {
                            "cell_box": [10, 10, 90, 90],
                            "merged_text": "表格內容 mixed",
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
        document_mode="general",
    )

    assert items == []
    assert alias_map == {}
    assert key_map == {}
    assert prefilled == {}


def test_general_document_mode_keeps_chinese_only_merged_cells_for_batch_items():
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
                    "block_content": "表格內容",
                    "block_bbox": [10, 10, 90, 90],
                    "should_translate": False,
                    "block_label": "table",
                }
            ],
            "table_res_list": [
                {
                    "cell_box_list": [[0, 0, 100, 100]],
                    "merged_cells": [
                        {
                            "cell_box": [10, 10, 90, 90],
                            "merged_text": "表格內容",
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
        document_mode="general",
    )

    assert [item["custom_id"] for item in items] == ["p0000-c0000"]
    assert alias_map == {}
    assert key_map == {
        "p0000-c0000": {
            "source_text": "表格內容",
            "source_normalized": "表格內容",
        }
    }
    assert prefilled == {}


def test_general_document_mode_skips_bilingual_merged_cells_for_edits_payload():
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
                    "block_content": "表格內容",
                    "block_bbox": [10, 10, 90, 90],
                    "should_translate": False,
                    "block_label": "table",
                }
            ],
            "table_res_list": [
                {
                    "cell_box_list": [[0, 0, 100, 100]],
                    "merged_cells": [
                        {
                            "cell_box": [10, 10, 90, 90],
                            "merged_text": "表格內容 mixed",
                            "should_translate": True,
                        }
                    ],
                }
            ],
        }
    }
    translations = {
        "p0000-c0000": "translated cell",
    }

    payload = build_edits_payload_from_translations(
        ocr_pages,
        translations,
        pp_pages=pp_pages,
        document_mode="general",
    )

    assert payload["pages"][0]["boxes"] == []


def test_general_document_mode_keeps_chinese_only_merged_cells_for_edits_payload():
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
                    "block_content": "表格內容",
                    "block_bbox": [10, 10, 90, 90],
                    "should_translate": False,
                    "block_label": "table",
                }
            ],
            "table_res_list": [
                {
                    "cell_box_list": [[0, 0, 100, 100]],
                    "merged_cells": [
                        {
                            "cell_box": [10, 10, 90, 90],
                            "merged_text": "表格內容",
                            "should_translate": True,
                        }
                    ],
                }
            ],
        }
    }
    translations = {
        "p0000-c0000": "translated cell",
    }

    payload = build_edits_payload_from_translations(
        ocr_pages,
        translations,
        pp_pages=pp_pages,
        document_mode="general",
    )

    boxes = payload["pages"][0]["boxes"]
    assert len(boxes) == 1
    assert boxes[0]["id"] == 100000
    assert boxes[0]["text"] == "translated cell"


def test_general_document_mode_keeps_chinese_missing_text_added_individually_cells():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": [],
            "rec_polys": [],
        }
    ]
    pp_pages = {
        0: {
            "parsing_res_list": [],
            "table_res_list": [
                {
                    "cell_box_list": [[0, 0, 100, 100]],
                    "merged_cells": [
                        {
                            "cell_box": [20, 20, 80, 40],
                            "merged_text": "補漏文字",
                            "should_translate": True,
                            "original_ocr_components": [
                                {
                                    "text": "補漏文字",
                                    "box": [20, 20, 80, 40],
                                }
                            ],
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
        document_mode="general",
    )

    assert [item["custom_id"] for item in items] == ["p0000-c0000"]
    assert alias_map == {}
    assert key_map == {
        "p0000-c0000": {
            "source_text": "補漏文字",
            "source_normalized": "補漏文字",
        }
    }
    assert prefilled == {}

    payload = build_edits_payload_from_translations(
        ocr_pages,
        {"p0000-c0000": "translated cell"},
        pp_pages=pp_pages,
        document_mode="general",
    )

    boxes = payload["pages"][0]["boxes"]
    assert len(boxes) == 1
    assert boxes[0]["id"] == 100000
    assert boxes[0]["text"] == "translated cell"


def test_scanned_document_mode_uses_ocr_lines_for_batch_items():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["掃描文字", "Scan text"],
            "rec_polys": [
                [[0, 0], [10, 0], [10, 10], [0, 10]],
                [[20, 0], [30, 0], [30, 10], [20, 10]],
            ],
        }
    ]
    pp_pages = {
        0: {
            "parsing_res_list": [
                {
                    "block_content": "不應使用的段落",
                    "block_bbox": [0, 0, 100, 20],
                    "should_translate": True,
                    "block_label": "text",
                }
            ]
        }
    }

    items, alias_map, key_map, prefilled = build_batch_items(
        ocr_pages,
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[],
        pp_pages=pp_pages,
        document_mode="scanned",
    )

    assert [item["custom_id"] for item in items] == ["p0000-l0000"]
    assert alias_map == {}
    assert key_map == {
        "p0000-l0000": {
            "source_text": "掃描文字",
            "source_normalized": "掃描文字",
        }
    }
    assert prefilled == {}


def test_form_mode_uses_target_lang_scoped_translation_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_PATH", tmp_path / "translation_memory.json")
    now_ts = time.time()
    memory = {
        translation_memory.make_tm_key("表格內容", "en", "form"): {
            "source_text": "表格內容",
            "source_normalized": "表格內容",
            "target_text": "table content",
            "target_lang": "en",
            "document_mode": "form",
            "created_at": now_ts,
            "last_used": now_ts,
            "source": "batch",
            "count": 1,
        }
    }
    state.TRANSLATION_MEMORY_PATH.write_text(
        json.dumps(memory, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    ocr_pages = [{"page_index_0based": 0, "rec_texts": ["表格內容"], "rec_polys": []}]
    items, alias_map, key_map, prefilled = build_batch_items(
        ocr_pages,
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[],
        target_lang="en",
        document_mode="form",
    )

    assert items == []
    assert alias_map == {}
    assert key_map == {}
    assert prefilled == {"p0000-l0000": "table content"}

    items, alias_map, key_map, prefilled = build_batch_items(
        ocr_pages,
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[],
        target_lang="ja",
        document_mode="form",
    )

    assert [item["custom_id"] for item in items] == ["p0000-l0000"]
    assert alias_map == {}
    assert key_map == {
        "p0000-l0000": {
            "source_text": "表格內容",
            "source_normalized": "表格內容",
        }
    }
    assert prefilled == {}


def test_form_mode_edits_payload_includes_tm_metadata():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": [],
            "rec_polys": [],
        }
    ]
    pp_pages = {
        0: {
            "table_res_list": [
                {
                    "cell_box_list": [[0, 0, 100, 100]],
                    "merged_cells": [
                        {
                            "cell_box": [10, 10, 90, 90],
                            "merged_text": "表格內容",
                            "should_translate": True,
                        }
                    ],
                }
            ],
        }
    }

    payload = build_edits_payload_from_translations(
        ocr_pages,
        {"p0000-c0000": "table content"},
        pp_pages=pp_pages,
        target_lang="en",
        document_mode="form",
    )

    box = payload["pages"][0]["boxes"][0]
    assert box["tm_source_text"] == "表格內容"
    assert box["tm_source_normalized"] == "表格內容"
    assert box["tm_target_lang"] == "en"
    assert box["tm_document_mode"] == "form"


def test_scanned_document_mode_writes_back_to_ocr_boxes():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["掃描文字"],
            "rec_polys": [
                [[0, 0], [10, 0], [10, 10], [0, 10]],
            ],
        }
    ]

    payload = build_edits_payload_from_translations(
        ocr_pages,
        {"p0000-l0000": "translated scan"},
        pp_pages={},
        document_mode="scanned",
    )

    boxes = payload["pages"][0]["boxes"]
    assert len(boxes) == 1
    assert boxes[0]["id"] == 0
    assert boxes[0]["text"] == "translated scan"
