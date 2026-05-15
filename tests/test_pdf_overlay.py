from __future__ import annotations

import json
from pathlib import Path

import fitz

from app.services import ocr
from ocr_pipeline.pipeline import get_rotated_textbox_rect, insert_paragraph_autowrap_shrink


def test_insert_paragraph_autowrap_shrink_commits_only_successful_fit():
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    rect = fitz.Rect(20, 20, 90, 60)
    text = "repeat me once only"

    info = insert_paragraph_autowrap_shrink(
        page=page,
        rect=rect,
        text=text,
        fontfile=None,
        max_fs=30,
        min_fs=8,
    )

    blocks = page.get_text("blocks")
    extracted = blocks[0][4]

    assert info["ok"] is True
    assert len(blocks) == 1
    assert extracted == "repeat me\nonce only\n"


def test_insert_paragraph_autowrap_shrink_clip_ellipsis_does_not_duplicate():
    doc = fitz.open()
    page = doc.new_page(width=200, height=200)
    rect = fitz.Rect(20, 20, 75, 45)
    text = "one two three four five six seven eight nine ten"

    info = insert_paragraph_autowrap_shrink(
        page=page,
        rect=rect,
        text=text,
        fontfile=None,
        max_fs=18,
        min_fs=8,
        clip_ellipsis=True,
    )

    blocks = page.get_text("blocks")
    extracted = blocks[0][4]

    assert info["ok"] is True
    assert info["clipped"] is True
    assert len(blocks) == 1
    assert extracted == "one two three\nfour five six...\n"


def test_get_rotated_textbox_rect_swaps_dimensions_and_stays_in_page():
    page_rect = fitz.Rect(0, 0, 200, 200)
    rect = fitz.Rect(20, 20, 120, 60)

    rotated = get_rotated_textbox_rect(rect, page_rect, 90)

    assert rotated.width == rect.height
    assert rotated.height == rect.width
    assert rotated.x0 >= page_rect.x0
    assert rotated.y0 >= page_rect.y0
    assert rotated.x1 <= page_rect.x1
    assert rotated.y1 <= page_rect.y1


def test_apply_edits_to_pdf_keeps_font_size_and_makes_overflow_visible(tmp_path: Path):
    job_id = "job-visible-text"
    job_dir = tmp_path / job_id
    ocr_json_dir = job_dir / "ocr_json"
    ocr_json_dir.mkdir(parents=True)

    doc = fitz.open()
    doc.new_page(width=200, height=500)
    doc.save((job_dir / f"{job_id}.pdf").as_posix())
    doc.close()

    (ocr_json_dir / "0001_res_with_pdf_coords.json").write_text(
        json.dumps(
            {
                "page_index_0based": 0,
                "coord_transform": {
                    "image_size_px": [200, 500],
                    "pdf_page_size_pt": [200, 500],
                    "page_rotation": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    edited_pdf = ocr.apply_edits_to_pdf(
        job_id,
        job_dir,
        {
            "pages": [
                {
                    "page_index_0based": 0,
                    "boxes": [
                        {
                            "bbox": {"x": 20, "y": 20, "w": 70, "h": 20},
                            "text": "one two three four five six seven eight",
                            "font_size": 24,
                            "color": "#0000ff",
                            "text_align": "left",
                            "rotation": 0,
                            "no_clip": False,
                        }
                    ],
                }
            ]
        },
    )

    out_doc = fitz.open(edited_pdf.as_posix())
    page = out_doc[0]
    blocks = page.get_text("blocks")
    text_dict = page.get_text("dict")
    out_doc.close()

    assert blocks
    extracted_text = "".join(block[4] for block in blocks)
    for token in ["one", "two", "three", "four", "five", "six", "seven", "eight"]:
        assert token in extracted_text
    span_sizes = [
        span["size"]
        for block in text_dict["blocks"]
        for line in block.get("lines", [])
        for span in line.get("spans", [])
    ]
    assert span_sizes
    assert any(abs(size - 24.0) < 0.2 for size in span_sizes)


def test_apply_edits_to_pdf_uses_tight_line_height_for_multiline_text(tmp_path: Path):
    job_id = "job-multiline-spacing"
    job_dir = tmp_path / job_id
    ocr_json_dir = job_dir / "ocr_json"
    ocr_json_dir.mkdir(parents=True)

    doc = fitz.open()
    doc.new_page(width=200, height=300)
    doc.save((job_dir / f"{job_id}.pdf").as_posix())
    doc.close()

    (ocr_json_dir / "0001_res_with_pdf_coords.json").write_text(
        json.dumps(
            {
                "page_index_0based": 0,
                "coord_transform": {
                    "image_size_px": [200, 300],
                    "pdf_page_size_pt": [200, 300],
                    "page_rotation": 0,
                },
            }
        ),
        encoding="utf-8",
    )

    edited_pdf = ocr.apply_edits_to_pdf(
        job_id,
        job_dir,
        {
            "pages": [
                {
                    "page_index_0based": 0,
                    "boxes": [
                        {
                            "bbox": {"x": 20, "y": 20, "w": 100, "h": 60},
                            "text": "first line\nsecond line",
                            "font_size": 24,
                            "color": "#000000",
                            "text_align": "left",
                            "rotation": 0,
                            "no_clip": False,
                        }
                    ],
                }
            ]
        },
    )

    out_doc = fitz.open(edited_pdf.as_posix())
    page = out_doc[0]
    text_dict = page.get_text("dict")
    out_doc.close()

    lines = [
        line
        for block in text_dict["blocks"]
        for line in block.get("lines", [])
        if "".join(span.get("text", "") for span in line.get("spans", [])).strip()
    ]
    assert len(lines) >= 2
    first_y = lines[0]["bbox"][1]
    second_y = lines[1]["bbox"][1]
    assert 20.0 <= (second_y - first_y) <= 23.0
