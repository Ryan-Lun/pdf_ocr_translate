from __future__ import annotations

from pathlib import Path

from app.services.ocr import iter_merged_cells, load_page_data


def test_iter_merged_cells_dedupes_same_cell_across_tables():
    pp_page = {
        "table_res_list": [
            {
                "merged_cells": [
                    {
                        "cell_box": [10, 20, 30, 40],
                        "merged_text": "重複內容",
                        "should_translate": True,
                    }
                ]
            },
            {
                "merged_cells": [
                    {
                        "cell_box": [10, 20, 30, 40],
                        "merged_text": "重複內容",
                        "should_translate": True,
                    }
                ]
            },
        ]
    }

    cells = iter_merged_cells(pp_page)

    assert len(cells) == 1
    assert cells[0]["merged_text"] == "重複內容"


def test_load_page_data_dedupes_duplicate_edit_boxes(tmp_path: Path):
    page_json_path = tmp_path / "page.json"
    page_json_path.write_text("{}", encoding="utf-8")
    data = {
        "page_index_0based": 0,
        "input_path": "page.png",
        "coord_transform": {"image_size_px": [100, 200]},
    }
    duplicate_box = {
        "id": 100011,
        "bbox": {"x": 370, "y": 1105, "w": 570, "h": 48},
        "text": "Report Number: UOC-PQR-16013",
        "deleted": False,
        "auto_generated": True,
        "font_size": 25,
        "color": "#0000ff",
        "text_align": "center",
        "no_clip": False,
    }

    page = load_page_data(
        page_json_path,
        edits_boxes=[duplicate_box, {**duplicate_box, "id": 100014}],
        data=data,
    )

    assert len(page["rec_polys"]) == 1
    assert len(page["edit_texts"]) == 1
    assert page["edit_texts"][0] == "Report Number: UOC-PQR-16013"
    assert page["alignments"] == ["center"]


def test_load_page_data_keeps_duplicate_manual_boxes(tmp_path: Path):
    page_json_path = tmp_path / "page.json"
    page_json_path.write_text("{}", encoding="utf-8")
    data = {
        "page_index_0based": 0,
        "input_path": "page.png",
        "coord_transform": {"image_size_px": [100, 200]},
    }
    manual_box = {
        "id": 1,
        "bbox": {"x": 10, "y": 20, "w": 30, "h": 40},
        "text": "Same manual text",
        "deleted": False,
        "auto_generated": False,
        "font_size": 18,
        "color": "#ff0000",
        "text_align": "right",
        "no_clip": False,
    }

    page = load_page_data(
        page_json_path,
        edits_boxes=[manual_box, {**manual_box, "id": 2}],
        data=data,
    )

    assert len(page["rec_polys"]) == 2
    assert page["box_ids"] == [1, 2]
    assert page["alignments"] == ["right", "right"]
