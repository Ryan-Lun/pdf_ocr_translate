from __future__ import annotations

import json
import time

from app.services.batch import (
    build_batch_items,
    build_edits_payload_from_translations,
    resolve_batch_prompt,
    translate_texts_for_region,
)
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


def test_general_document_mode_merged_cells_ignore_explicit_source_language():
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
                            "cell_box": [10, 10, 90, 90],
                            "merged_text": "English only",
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
        target_lang="zh",
        source_lang="en",
        document_mode="general",
    )

    assert items == []
    assert alias_map == {}
    assert key_map == {}
    assert prefilled == {}


def test_other_document_mode_merged_cells_use_explicit_source_language():
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
                            "cell_box": [10, 10, 90, 90],
                            "merged_text": "English only",
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
        target_lang="zh",
        source_lang="en",
        document_mode="other",
    )

    assert [item["custom_id"] for item in items] == ["p0000-c0000"]
    assert alias_map == {}
    assert key_map == {
        "p0000-c0000": {
            "source_text": "English only",
            "source_normalized": "English only",
        }
    }
    assert prefilled == {}


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


def test_general_document_mode_skips_ocr_lines_inside_bilingual_structured_blocks():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["中文段落"],
            "rec_polys": [
                [[10, 10], [90, 10], [90, 30], [10, 30]],
            ],
        }
    ]
    pp_pages = {
        0: {
            "parsing_res_list": [
                {
                    "block_content": "中文段落 English paragraph",
                    "block_bbox": [0, 0, 120, 40],
                    "should_translate": False,
                    "block_label": "text",
                }
            ],
            "table_res_list": [],
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


def test_general_document_mode_payload_skips_ocr_lines_inside_bilingual_structured_blocks():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["中文段落"],
            "rec_polys": [
                [[10, 10], [90, 10], [90, 30], [10, 30]],
            ],
        }
    ]
    pp_pages = {
        0: {
            "parsing_res_list": [
                {
                    "block_content": "中文段落 English paragraph",
                    "block_bbox": [0, 0, 120, 40],
                    "should_translate": False,
                    "block_label": "text",
                }
            ],
            "table_res_list": [],
        }
    }

    payload = build_edits_payload_from_translations(
        ocr_pages,
        {"p0000-l0000": "Translated line"},
        pp_pages=pp_pages,
        document_mode="general",
    )

    assert payload["pages"][0]["boxes"] == []


def test_general_document_mode_skips_mixed_structured_blocks_for_batch_items():
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
                    "block_content": "骨科植入物 Orthopedic Implants",
                    "block_bbox": [0, 0, 120, 40],
                    "should_translate": True,
                    "block_label": "text",
                }
            ],
            "table_res_list": [],
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


def test_general_document_mode_payload_skips_mixed_structured_blocks():
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
                    "block_content": "骨科植入物 Orthopedic Implants",
                    "block_bbox": [0, 0, 120, 40],
                    "should_translate": True,
                    "block_label": "text",
                }
            ],
            "table_res_list": [],
        }
    }

    payload = build_edits_payload_from_translations(
        ocr_pages,
        {"p0000-b0000": "Translated bilingual block"},
        pp_pages=pp_pages,
        document_mode="general",
    )

    assert payload["pages"][0]["boxes"] == []


def test_general_document_mode_keeps_ocr_lines_when_mixed_structured_block_is_skipped():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["骨科植入物"],
            "rec_polys": [
                [[10, 10], [90, 10], [90, 30], [10, 30]],
            ],
        }
    ]
    pp_pages = {
        0: {
            "parsing_res_list": [
                {
                    "block_content": "骨科植入物 Orthopedic Implants",
                    "block_bbox": [0, 0, 120, 40],
                    "should_translate": True,
                    "block_label": "text",
                }
            ],
            "table_res_list": [],
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

    assert [item["custom_id"] for item in items] == ["p0000-l0000"]
    assert alias_map == {}
    assert key_map == {
        "p0000-l0000": {
            "source_text": "骨科植入物",
            "source_normalized": "骨科植入物",
        }
    }
    assert prefilled == {}


def test_general_document_mode_payload_keeps_ocr_lines_when_mixed_structured_block_is_skipped():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["骨科植入物"],
            "rec_polys": [
                [[10, 10], [90, 10], [90, 30], [10, 30]],
            ],
        }
    ]
    pp_pages = {
        0: {
            "parsing_res_list": [
                {
                    "block_content": "骨科植入物 Orthopedic Implants",
                    "block_bbox": [0, 0, 120, 40],
                    "should_translate": True,
                    "block_label": "text",
                }
            ],
            "table_res_list": [],
        }
    }

    payload = build_edits_payload_from_translations(
        ocr_pages,
        {"p0000-l0000": "Orthopedic Implants"},
        pp_pages=pp_pages,
        document_mode="general",
    )

    boxes = payload["pages"][0]["boxes"]
    assert len(boxes) == 1
    assert boxes[0]["id"] == 0
    assert boxes[0]["text"] == "Orthopedic Implants"


def test_general_force_translate_mode_keeps_bilingual_structured_blocks_for_batch_items():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["中文段落"],
            "rec_polys": [
                [[10, 10], [90, 10], [90, 30], [10, 30]],
            ],
        }
    ]
    pp_pages = {
        0: {
            "parsing_res_list": [
                {
                    "block_content": "中文段落 English paragraph",
                    "block_bbox": [0, 0, 120, 40],
                    "should_translate": False,
                    "block_label": "text",
                }
            ],
            "table_res_list": [],
        }
    }

    items, alias_map, key_map, prefilled = build_batch_items(
        ocr_pages,
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[],
        pp_pages=pp_pages,
        document_mode="general_force",
    )

    assert [item["custom_id"] for item in items] == ["p0000-b0000"]
    assert alias_map == {}
    assert key_map == {
        "p0000-b0000": {
            "source_text": "中文段落 English paragraph",
            "source_normalized": "中文段落 English paragraph",
        }
    }
    assert prefilled == {}


def test_general_force_translate_mode_keeps_bilingual_structured_blocks_for_payload():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["中文段落"],
            "rec_polys": [
                [[10, 10], [90, 10], [90, 30], [10, 30]],
            ],
        }
    ]
    pp_pages = {
        0: {
            "parsing_res_list": [
                {
                    "block_content": "中文段落 English paragraph",
                    "block_bbox": [0, 0, 120, 40],
                    "should_translate": False,
                    "block_label": "text",
                }
            ],
            "table_res_list": [],
        }
    }

    payload = build_edits_payload_from_translations(
        ocr_pages,
        {"p0000-b0000": "Translated bilingual block"},
        pp_pages=pp_pages,
        document_mode="general_force",
    )

    boxes = payload["pages"][0]["boxes"]
    assert len(boxes) == 1
    assert boxes[0]["id"] == 200000
    assert boxes[0]["text"] == "Translated bilingual block"


def test_general_force_translate_mode_skips_overlapping_header_ocr_line_for_batch_items():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["UnitedOrthopedicCorporation聯合骨科器材股份有限公司", "聯合骨科器材股份有限公司"],
            "rec_polys": [
                [[206, 131], [1011, 131], [1011, 176], [206, 176]],
                [[559, 342], [1087, 342], [1087, 386], [559, 386]],
            ],
        }
    ]
    pp_pages = {
        0: {
            "parsing_res_list": [
                {
                    "block_content": "UnitedOrthopedicCorporation聯合骨科器材股份有限公司",
                    "block_bbox": [209.8, 137.1, 1006.4, 169.3],
                    "should_translate": False,
                    "block_label": "header",
                }
            ],
            "table_res_list": [],
        }
    }

    items, _, key_map, _ = build_batch_items(
        ocr_pages,
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[],
        pp_pages=pp_pages,
        document_mode="general_force",
    )

    assert [item["custom_id"] for item in items] == ["p0000-b0000", "p0000-l0001"]
    assert "p0000-l0000" not in key_map


def test_general_force_translate_mode_skips_overlapping_header_ocr_line_for_payload():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["UnitedOrthopedicCorporation聯合骨科器材股份有限公司", "聯合骨科器材股份有限公司"],
            "rec_polys": [
                [[206, 131], [1011, 131], [1011, 176], [206, 176]],
                [[559, 342], [1087, 342], [1087, 386], [559, 386]],
            ],
        }
    ]
    pp_pages = {
        0: {
            "parsing_res_list": [
                {
                    "block_content": "UnitedOrthopedicCorporation聯合骨科器材股份有限公司",
                    "block_bbox": [209.8, 137.1, 1006.4, 169.3],
                    "should_translate": False,
                    "block_label": "header",
                }
            ],
            "table_res_list": [],
        }
    }

    payload = build_edits_payload_from_translations(
        ocr_pages,
        {
            "p0000-b0000": "United Orthopedic Corporation",
            "p0000-l0000": "United Orthopedic Corporation",
            "p0000-l0001": "United Orthopedic Corporation",
        },
        pp_pages=pp_pages,
        document_mode="general_force",
    )

    boxes = payload["pages"][0]["boxes"]
    assert [box["id"] for box in boxes] == [1, 200000]


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
    monkeypatch.setattr(state, "PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY", True)
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


def test_overlay_can_disable_translation_memory_prefill(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_PATH", tmp_path / "translation_memory.json")
    monkeypatch.setattr(state, "PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY", False)
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


def test_scanned_document_mode_collects_english_ocr_lines_for_chinese_target():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["Inspection item", "中文說明"],
            "rec_polys": [
                [[0, 0], [10, 0], [10, 10], [0, 10]],
                [[20, 0], [30, 0], [30, 10], [20, 10]],
            ],
        }
    ]

    items, alias_map, key_map, prefilled = build_batch_items(
        ocr_pages,
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[],
        target_lang="zh",
        document_mode="scanned",
    )

    assert [item["custom_id"] for item in items] == ["p0000-l0000"]
    assert alias_map == {}
    assert key_map == {
        "p0000-l0000": {
            "source_text": "Inspection item",
            "source_normalized": "Inspection item",
        }
    }
    assert prefilled == {}


def test_scanned_document_mode_writes_back_english_source_for_chinese_target():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["Inspection item"],
            "rec_polys": [
                [[0, 0], [10, 0], [10, 10], [0, 10]],
            ],
        }
    ]

    payload = build_edits_payload_from_translations(
        ocr_pages,
        {"p0000-l0000": "檢查項目"},
        pp_pages={},
        target_lang="zh",
        document_mode="scanned",
    )

    boxes = payload["pages"][0]["boxes"]
    assert len(boxes) == 1
    assert boxes[0]["id"] == 0
    assert boxes[0]["text"] == "檢查項目"
    assert boxes[0]["tm_source_text"] == "Inspection item"
    assert boxes[0]["tm_target_lang"] == "zh"


def test_zh_target_prompt_requires_traditional_chinese():
    prompt = resolve_batch_prompt("zh")
    assert "Traditional Chinese" in prompt
    assert "Never use Simplified Chinese characters" in prompt


def test_general_mode_chart_blocks_fall_back_to_ocr_lines_for_batch_items():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["圖表標題", "X軸標籤", "Y軸標籤"],
            "rec_polys": [
                [[0, 0], [100, 0], [100, 20], [0, 20]],
                [[0, 30], [100, 30], [100, 50], [0, 50]],
                [[0, 60], [100, 60], [100, 80], [0, 80]],
            ],
        }
    ]
    pp_pages = {
        0: {
            "parsing_res_list": [
                {
                    "block_content": "圖表標題\nX軸標籤\nY軸標籤",
                    "block_bbox": [0, 0, 120, 100],
                    "should_translate": True,
                    "block_label": "chart",
                }
            ],
            "table_res_list": [],
        }
    }

    items, _, key_map, _ = build_batch_items(
        ocr_pages,
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[],
        pp_pages=pp_pages,
        document_mode="general",
    )

    assert [item["custom_id"] for item in items] == [
        "p0000-l0000",
        "p0000-l0001",
        "p0000-l0002",
    ]
    assert key_map == {
        "p0000-l0000": {
            "source_text": "圖表標題",
            "source_normalized": "圖表標題",
        },
        "p0000-l0001": {
            "source_text": "X軸標籤",
            "source_normalized": "X軸標籤",
        },
        "p0000-l0002": {
            "source_text": "Y軸標籤",
            "source_normalized": "Y軸標籤",
        },
    }


def test_general_mode_chart_blocks_fall_back_to_ocr_lines_for_edits_payload():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["圖表標題", "X軸標籤"],
            "rec_polys": [
                [[0, 0], [100, 0], [100, 20], [0, 20]],
                [[0, 30], [100, 30], [100, 50], [0, 50]],
            ],
        }
    ]
    pp_pages = {
        0: {
            "parsing_res_list": [
                {
                    "block_content": "圖表標題\nX軸標籤",
                    "block_bbox": [0, 0, 120, 60],
                    "should_translate": True,
                    "block_label": "chart",
                }
            ],
            "table_res_list": [],
        }
    }

    payload = build_edits_payload_from_translations(
        ocr_pages,
        {
            "p0000-l0000": "chart title",
            "p0000-l0001": "x axis",
            "p0000-b0000": "should not be used",
        },
        pp_pages=pp_pages,
        document_mode="general",
    )

    boxes = payload["pages"][0]["boxes"]
    assert len(boxes) == 2
    assert [box["id"] for box in boxes] == [0, 1]
    assert [box["text"] for box in boxes] == ["chart title", "x axis"]


def test_document_terms_dedupe_short_labels_with_trailing_colon():
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
                    "cell_box_list": [[0, 0, 120, 60]],
                    "merged_cells": [
                        {
                            "cell_box": [0, 0, 60, 20],
                            "merged_text": "檢查頻率：",
                            "should_translate": True,
                        },
                        {
                            "cell_box": [0, 20, 60, 40],
                            "merged_text": "檢查頻率",
                            "should_translate": True,
                        },
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
        document_mode="form",
    )

    assert [item["custom_id"] for item in items] == ["p0000-c0000"]
    assert alias_map == {"p0000-c0001": "p0000-c0000"}
    assert key_map == {
        "p0000-c0000": {
            "source_text": "檢查頻率",
            "source_normalized": "檢查頻率",
        }
    }
    assert items[0]["body"]["messages"][1]["content"] == "檢查頻率"
    assert prefilled == {}


def test_document_terms_prefill_short_label_from_canonical_tm(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_PATH", tmp_path / "translation_memory.json")
    monkeypatch.setattr(state, "PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY", True)
    now_ts = time.time()
    memory = {
        translation_memory.make_tm_key(
            "檢查頻率",
            "en",
            "form",
            source_normalized="檢查頻率",
        ): {
            "source_text": "檢查頻率",
            "source_normalized": "檢查頻率",
            "target_text": "inspection frequency",
            "target_lang": "en",
            "document_mode": "form",
            "created_at": now_ts,
            "last_used": now_ts,
            "source": "editor",
            "count": 1,
        }
    }
    state.TRANSLATION_MEMORY_PATH.write_text(
        json.dumps(memory, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

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
                    "cell_box_list": [[0, 0, 120, 60]],
                    "merged_cells": [
                        {
                            "cell_box": [0, 0, 60, 20],
                            "merged_text": "檢查頻率：",
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
        document_mode="form",
    )

    assert items == []
    assert alias_map == {}
    assert key_map == {}
    assert prefilled == {"p0000-c0000": "inspection frequency"}


def test_document_terms_restore_trailing_colon_in_payload():
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
                    "cell_box_list": [[0, 0, 120, 60]],
                    "merged_cells": [
                        {
                            "cell_box": [0, 0, 60, 20],
                            "merged_text": "檢查頻率：",
                            "should_translate": True,
                        },
                        {
                            "cell_box": [0, 20, 60, 40],
                            "merged_text": "檢查頻率",
                            "should_translate": True,
                        },
                    ],
                }
            ],
        }
    }

    payload = build_edits_payload_from_translations(
        ocr_pages,
        {
            "p0000-c0000": "inspection frequency",
            "p0000-c0001": "inspection frequency",
        },
        pp_pages=pp_pages,
        document_mode="form",
    )

    boxes = payload["pages"][0]["boxes"]
    assert [box["text"] for box in boxes] == ["inspection frequency:", "inspection frequency"]
    assert [box["tm_source_normalized"] for box in boxes] == ["檢查頻率", "檢查頻率"]


def test_build_batch_items_orders_page_content_by_visual_flow_across_blocks_and_cells():
    ocr_pages = [
        {
            "page_index_0based": 7,
            "rec_texts": [],
            "rec_polys": [],
        }
    ]
    pp_pages = {
        7: {
            "parsing_res_list": [
                {
                    "block_content": "Table3各廠牌使用cage材質及Thickness比較",
                    "block_bbox": [0, 0, 300, 20],
                    "should_translate": True,
                    "block_label": "text",
                },
                {
                    "block_content": "2.1.4Cage材質:Cp Ti",
                    "block_bbox": [0, 120, 300, 150],
                    "should_translate": True,
                    "block_label": "text",
                },
            ],
            "table_res_list": [
                {
                    "cell_box_list": [[0, 30, 300, 110]],
                    "merged_cells": [
                        {
                            "cell_box": [0, 40, 80, 60],
                            "merged_text": "材質",
                            "should_translate": True,
                        },
                        {
                            "cell_box": [90, 40, 170, 60],
                            "merged_text": "品牌",
                            "should_translate": True,
                        },
                        {
                            "cell_box": [180, 40, 280, 60],
                            "merged_text": "產品名",
                            "should_translate": True,
                        },
                    ],
                }
            ],
        }
    }

    items, _, _, _ = build_batch_items(
        ocr_pages,
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[],
        pp_pages=pp_pages,
        document_mode="general_force",
    )

    assert [item["custom_id"] for item in items] == [
        "p0007-b0000",
        "p0007-c0000",
        "p0007-c0001",
        "p0007-c0002",
        "p0007-b0001",
    ]


def test_build_edits_payload_keeps_source_text_metadata_for_general_force():
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
                    "block_content": "原始段落內容",
                    "block_bbox": [0, 0, 120, 40],
                    "should_translate": True,
                    "block_label": "text",
                }
            ],
            "table_res_list": [],
        }
    }

    payload = build_edits_payload_from_translations(
        ocr_pages,
        {"p0000-b0000": "Translated paragraph"},
        pp_pages=pp_pages,
        target_lang="en",
        document_mode="general_force",
    )

    box = payload["pages"][0]["boxes"][0]
    assert box["tm_source_text"] == "原始段落內容"
    assert box["tm_target_lang"] == "en"
    assert box["tm_document_mode"] == "general_force"


def test_translate_texts_for_region_adds_glossary_and_protected_token_instructions(monkeypatch):
    captured: dict[str, str] = {}

    class FakeResponse:
        output_text = "translated"

    class FakeResponses:
        @staticmethod
        def create(*, model, instructions, input):
            captured["model"] = model
            captured["instructions"] = instructions
            captured["input"] = input
            return FakeResponse()

    class FakeClient:
        responses = FakeResponses()

    monkeypatch.setattr("app.services.batch.get_azure_client", lambda: FakeClient())

    outputs = translate_texts_for_region(
        ["品質系統規範"],
        target_lang="en",
        source_lang="zh",
        model_name="fake-model",
        system_prompt="translate",
        glossary_entries=[("品質系統規範", "Quality System Regulation")],
    )

    assert outputs == ["translated"]
    assert captured["model"] == "fake-model"
    assert "Use the following terminology when applicable:" in captured["instructions"]
    assert "品質系統規範 -> Quality System Regulation" in captured["instructions"]
    assert "[[[GLOSSARY_TERM_0001::TERM]]]" in captured["instructions"]
    assert "[[[GLOSSARY_TERM_" in captured["input"]
