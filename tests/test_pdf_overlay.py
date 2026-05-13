from __future__ import annotations

import fitz

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
