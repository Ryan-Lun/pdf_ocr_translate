from __future__ import annotations

import os
import json
import re
import time
from pathlib import Path
from typing import Any

_LAYOUT_BLOCK = None
_LAYOUT_BLOCK_ERROR: Exception | None = None
DEFAULT_OCR_MIN_LINE_SCORE = max(
    0.0,
    min(1.0, float(os.getenv("OCR_MIN_LINE_SCORE", "0.8"))),
)


def _poly_to_box(poly):
    xs = [p[0] for p in poly]
    ys = [p[1] for p in poly]
    return [min(xs), min(ys), max(xs), max(ys)]


def _is_inside(box, block):
    return not (
        box[2] < block[0]
        or box[0] > block[2]
        or box[3] < block[1]
        or box[1] > block[3]
    )


def _inside_table(box, table_boxes):
    for t in table_boxes:
        if box[0] >= t[0] and box[1] >= t[1] and box[2] <= t[2] and box[3] <= t[3]:
            return True
    return False


def _sort_text_boxes(boxes, texts):
    items = []
    for box, text in zip(boxes, texts):
        if not text:
            continue
        try:
            x1, y1, x2, y2 = [float(v) for v in box]
        except (TypeError, ValueError):
            continue
        items.append(
            {
                "box": [x1, y1, x2, y2],
                "text": str(text).strip(),
                "cy": (y1 + y2) * 0.5,
                "height": max(0.0, y2 - y1),
            }
        )
    items.sort(key=lambda item: (round(item["cy"], 1), item["box"][0]))
    return items


def _needs_space_between(prev_text: str, next_text: str) -> bool:
    if not prev_text or not next_text:
        return False
    if re.search(r"[\u4e00-\u9fff\u3040-\u30ff]$", prev_text) and re.search(r"^[\u4e00-\u9fff\u3040-\u30ff]", next_text):
        return False
    if prev_text.endswith(("(", "[", "{", "/", "-")):
        return False
    if next_text.startswith((")", "]", "}", ",", ".", ";", ":", "!", "?", "/", "%")):
        return False
    return True


def _append_text(parts: list[str], text: str) -> None:
    text = str(text or "").strip()
    if not text:
        return
    if not parts:
        parts.append(text)
        return
    sep = " " if _needs_space_between(parts[-1], text) else ""
    parts.append(f"{sep}{text}")


def _compose_fallback_block_content(boxes, texts) -> str:
    items = _sort_text_boxes(boxes, texts)
    if not items:
        return ""

    merged_parts: list[str] = []
    current_row: list[dict[str, Any]] = []
    current_cy = None
    current_height = 0.0

    def flush_row() -> None:
        if not current_row:
            return
        current_row.sort(key=lambda item: item["box"][0])
        row_parts: list[str] = []
        for item in current_row:
            _append_text(row_parts, item["text"])
        row_text = "".join(row_parts).strip()
        if row_text:
            _append_text(merged_parts, row_text)

    for item in items:
        if current_cy is None:
            current_row = [item]
            current_cy = item["cy"]
            current_height = item["height"]
            continue

        same_row_threshold = max(10.0, current_height * 0.6, item["height"] * 0.6)
        if abs(item["cy"] - current_cy) <= same_row_threshold:
            current_row.append(item)
            current_cy = (current_cy * (len(current_row) - 1) + item["cy"]) / len(current_row)
            current_height = max(current_height, item["height"])
            continue

        flush_row()
        current_row = [item]
        current_cy = item["cy"]
        current_height = item["height"]

    flush_row()
    return "".join(merged_parts).strip()


def _insert_pruned_result(data: dict[str, Any], pruned_result, after_key: str | None = None):
    if after_key is None:
        data["parsing_res_list"] = pruned_result
        return data

    new_data = {}
    inserted = False
    for k, v in data.items():
        new_data[k] = v
        if k == after_key:
            new_data["parsing_res_list"] = pruned_result
            inserted = True

    if not inserted:
        new_data["parsing_res_list"] = pruned_result

    return new_data


def _get_layout_block_class():
    global _LAYOUT_BLOCK, _LAYOUT_BLOCK_ERROR
    if _LAYOUT_BLOCK is not None:
        return _LAYOUT_BLOCK
    if _LAYOUT_BLOCK_ERROR is not None:
        raise _LAYOUT_BLOCK_ERROR
    try:
        from PaddleX.paddlex.inference.pipelines.layout_parsing.layout_objects import LayoutBlock

        _LAYOUT_BLOCK = LayoutBlock
        return _LAYOUT_BLOCK
    except Exception as exc:
        _LAYOUT_BLOCK_ERROR = exc
        raise


def merge_keep_original_json(data: dict[str, Any]) -> dict[str, Any]:
    layout_blocks = data["layout_det_res"]["boxes"]
    ocr_res = data["overall_ocr_res"]
    tables = data["table_res_list"]

    rec_boxes = [_poly_to_box(p) for p in ocr_res["rec_polys"]]
    rec_texts = ocr_res["rec_texts"]
    rec_scores = ocr_res.get("rec_scores") or []

    table_boxes = [b["coordinate"] for b in layout_blocks if b["label"] == "table"]

    height = data.get("height")
    width = data.get("width")
    if not height or not width:
        input_path = data.get("input_path")
        if input_path:
            guess_name = Path(input_path).name
            m = __import__("re").search(r"_p(\d+)", guess_name)
            if m:
                page_no = int(m.group(1))
                candidate = Path("out/images") / f"{Path(guess_name).stem}.png"
                if candidate.exists():
                    try:
                        from PIL import Image

                        with Image.open(candidate) as im:
                            width, height = im.size
                    except Exception:
                        pass
    if not height or not width:
        height, width = 2480, 3508

    try:
        import numpy as np
    except Exception as exc:
        print(f"[WARN] merge_keep_original_json unavailable: {exc}")
        return data

    dummy_img = np.zeros((height, width, 3), dtype=np.uint8)

    pruned_result = []
    table_idx = 0

    try:
        LayoutBlock = _get_layout_block_class()
    except Exception as exc:
        print(f"[WARN] merge_keep_original_json LayoutBlock fallback: {exc}")
        LayoutBlock = None

    for block in layout_blocks:
        label = block["label"]
        bbox = block["coordinate"]

        if label == "table":
            html = tables[table_idx]["pred_html"]
            table_idx += 1

            pruned_result.append(
                {
                    "block_label": "table",
                    "block_content": html,
                    "block_bbox": bbox,
                }
            )
            continue

        boxes = []
        texts = []

        for idx, (box, text) in enumerate(zip(rec_boxes, rec_texts)):
            score = float(rec_scores[idx]) if idx < len(rec_scores) else 1.0
            if score < DEFAULT_OCR_MIN_LINE_SCORE:
                continue
            if _inside_table(box, table_boxes):
                continue

            if _is_inside(box, bbox):
                boxes.append(box)
                texts.append(text)

        if not boxes:
            continue

        ocr_rec_res = {
            "boxes": boxes,
            "rec_texts": texts,
            "rec_labels": ["text"] * len(boxes),
        }

        if LayoutBlock is not None:
            lb = LayoutBlock(label=label, bbox=bbox)
            lb.update_text_content(
                image=dummy_img,
                ocr_rec_res=ocr_rec_res,
                text_rec_model=None,
            )
            block_content = lb.content.strip()
        else:
            block_content = _compose_fallback_block_content(boxes, texts)

        pruned_result.append(
            {
                "block_label": label,
                "block_content": block_content,
                "block_bbox": bbox,
            }
        )

    pruned_result.sort(key=lambda x: (x["block_bbox"][1], x["block_bbox"][0]))

    data = _insert_pruned_result(data, pruned_result, after_key="doc_preprocessor_res")
    return data


__all__ = ["merge_keep_original_json"]
