from __future__ import annotations

import fitz

from ocr_pipeline.pipeline import insert_paragraph_autowrap_shrink


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
