from __future__ import annotations

import importlib.util
from pathlib import Path


def _load_merge_logic_module():
    path = Path(__file__).resolve().parents[1] / "ocr_pipeline" / "merge_logic.py"
    spec = importlib.util.spec_from_file_location("merge_logic_local", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def test_merge_keep_original_json_falls_back_without_layoutblock(monkeypatch):
    module = _load_merge_logic_module()

    def _raise_layoutblock():
        raise ModuleNotFoundError("colorlog")

    monkeypatch.setattr(module, "_get_layout_block_class", _raise_layoutblock)

    data = {
        "layout_det_res": {
            "boxes": [
                {"label": "text", "coordinate": [0, 0, 200, 120]},
            ]
        },
        "overall_ocr_res": {
            "rec_polys": [
                [[0, 0], [90, 0], [90, 20], [0, 20]],
                [[0, 30], [120, 30], [120, 50], [0, 50]],
                [[0, 60], [80, 60], [80, 80], [0, 80]],
            ],
            "rec_texts": [
                "這是第一行",
                "第二行內容",
                "Third line",
            ],
        },
        "table_res_list": [],
        "width": 1000,
        "height": 1000,
    }

    merged = module.merge_keep_original_json(data)

    assert "parsing_res_list" in merged
    assert len(merged["parsing_res_list"]) == 1
    assert merged["parsing_res_list"][0]["block_label"] == "text"
    assert merged["parsing_res_list"][0]["block_content"] == "這是第一行第二行內容 Third line"


def test_merge_keep_original_json_skips_low_score_rec_texts(monkeypatch):
    module = _load_merge_logic_module()

    def _raise_layoutblock():
        raise ModuleNotFoundError("colorlog")

    monkeypatch.setattr(module, "_get_layout_block_class", _raise_layoutblock)
    monkeypatch.setattr(module, "DEFAULT_OCR_MIN_LINE_SCORE", 0.5)

    data = {
        "layout_det_res": {
            "boxes": [
                {"label": "text", "coordinate": [0, 0, 200, 120]},
            ]
        },
        "overall_ocr_res": {
            "rec_polys": [
                [[0, 0], [90, 0], [90, 20], [0, 20]],
                [[0, 30], [120, 30], [120, 50], [0, 50]],
            ],
            "rec_texts": [
                "keep line",
                "drop line",
            ],
            "rec_scores": [0.9, 0.2],
        },
        "table_res_list": [],
        "width": 1000,
        "height": 1000,
    }

    merged = module.merge_keep_original_json(data)

    assert "parsing_res_list" in merged
    assert len(merged["parsing_res_list"]) == 1
    assert merged["parsing_res_list"][0]["block_content"] == "keep line"
