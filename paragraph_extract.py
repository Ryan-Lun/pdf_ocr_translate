from __future__ import annotations

from ocr_pipeline.paragraph_align import (
    align_and_update_json,
    bbox_vertical_match,
    is_chinese,
    is_english,
    main,
)

__all__ = [
    "align_and_update_json",
    "bbox_vertical_match",
    "is_chinese",
    "is_english",
    "main",
]


if __name__ == "__main__":
    main()
