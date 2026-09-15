from __future__ import annotations

import csv
import json
from pathlib import Path

from scripts import extract_numbered_heading_glossary_candidates as extractor


def _write_pp_json(path: Path, texts: list[str], polys: list[list[list[int]]] | None = None) -> None:
    if polys is None:
        polys = [
            [[10, index * 50], [100, index * 50], [100, index * 50 + 20], [10, index * 50 + 20]]
            for index in range(len(texts))
        ]
    path.write_text(
        json.dumps(
            {"overall_ocr_res": {"rec_texts": texts, "rec_polys": polys}},
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_extracts_same_line_numbered_headings(tmp_path):
    source = tmp_path / "job_p0002.json"
    _write_pp_json(
        source,
        [
            "3.1 專案計畫負責人(Project leader):",
            "4.定義(Definition):",
            "專案編碼管制。Management of project codes.",
        ],
    )

    candidates = extractor.extract_candidates_from_file(source)

    assert [(item.page, item.number, item.cn, item.en) for item in candidates] == [
        (2, "3.1", "專案計畫負責人", "Project leader"),
        (2, "4.", "定義", "Definition"),
    ]
    assert "專案編碼管制" not in {item.cn for item in candidates}


def test_extracts_split_number_and_heading_on_same_row(tmp_path):
    source = tmp_path / "job_p0002.json"
    _write_pp_json(
        source,
        ["1.", "目的(Purpose) :", "2.", "範圍(Scope) :"],
        [
            [[246, 333], [282, 333], [282, 369], [246, 369]],
            [[305, 334], [541, 334], [541, 371], [305, 371]],
            [[245, 547], [282, 547], [282, 583], [245, 583]],
            [[302, 548], [512, 548], [512, 586], [302, 586]],
        ],
    )

    candidates = extractor.extract_candidates_from_file(source)

    assert [(item.number, item.cn, item.en, item.raw_text) for item in candidates] == [
        ("1.", "目的", "Purpose", "1. 目的(Purpose) :"),
        ("2.", "範圍", "Scope", "2. 範圍(Scope) :"),
    ]
    assert candidates[0].x0 == 246
    assert candidates[0].x1 == 541


def test_page_exclusion_and_csv_output(tmp_path):
    pp_json = tmp_path / "pp_json"
    pp_json.mkdir()
    _write_pp_json(pp_json / "job_p0001.json", ["1. 應排除(Skip):"])
    _write_pp_json(pp_json / "job_p0002.json", ["4.1 產品開發案(Product development project)"])
    output = tmp_path / "candidates.csv"

    rc = extractor.main([str(pp_json), "--output", str(output), "--exclude-pages", "1"])

    assert rc == 0
    with output.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 1
    assert rows[0]["page"] == "2"
    assert rows[0]["number"] == "4.1"
    assert rows[0]["cn"] == "產品開發案"
    assert rows[0]["en"] == "Product development project"
    assert rows[0]["source_format"] == "paddleocr_pp_json"


def test_extracts_opendataloader_heading_prefixes_with_body_text(tmp_path):
    source = tmp_path / "opendataloader.json"
    source.write_text(
        json.dumps(
            {
                "file name": "sample.pdf",
                "kids": [
                    {
                        "type": "list item",
                        "page number": 2,
                        "bounding box": [89.904, 689.629, 457.7, 720.229],
                        "content": "1. 目的(Purpose)： 為使專案性計畫能達成既定要求。",
                    },
                    {
                        "type": "list item",
                        "page number": 2,
                        "bounding box": [109.7, 371.819, 417.67, 405.439],
                        "content": "4.1 產品開發案(Product development project)： 指新產品系列之開發計畫案。",
                    },
                    {
                        "type": "paragraph",
                        "page number": 2,
                        "content": "專案編碼管制。Management of project codes.",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    candidates = extractor.extract_candidates_from_file(source)

    assert [(item.page, item.number, item.cn, item.en) for item in candidates] == [
        (2, "1.", "目的", "Purpose"),
        (2, "4.1", "產品開發案", "Product development project"),
    ]
    assert candidates[0].raw_text == "1. 目的(Purpose)： 為使專案性計畫能達成既定要求。"
    assert candidates[0].source_format == "opendataloader_json"
    assert candidates[0].x0 == 90


def test_extracts_multiple_opendataloader_headings_from_one_content_item(tmp_path):
    source = tmp_path / "opendataloader.json"
    source.write_text(
        json.dumps(
            {
                "kids": [
                    {
                        "type": "list item",
                        "page number": 3,
                        "content": "6. 內容(Contents)： 6.1 專案計畫編碼(Project code)",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    candidates = extractor.extract_candidates_from_file(source)

    assert [(item.page, item.number, item.cn, item.en) for item in candidates] == [
        (3, "6.", "內容", "Contents"),
        (3, "6.1", "專案計畫編碼", "Project code"),
    ]


def test_does_not_extract_plain_year_as_numbered_heading(tmp_path):
    source = tmp_path / "opendataloader.json"
    source.write_text(
        json.dumps(
            {
                "kids": [
                    {
                        "type": "paragraph",
                        "page number": 3,
                        "content": "西元年代碼，例如: 07 表 2007 年 (Year code. For example 07 stands for 2007.)",
                    }
                ]
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    assert extractor.extract_candidates_from_file(source) == []
