from __future__ import annotations

import json
import logging
import os
import re
import base64
from pathlib import Path
from typing import Any

import fitz
import requests

from . import state
from ocr_pipeline.pipeline import filter_ppstructure_data_by_score

try:
    import cv2
except Exception:  # pragma: no cover - optional runtime dependency in tests
    cv2 = None

logger = logging.getLogger(__name__)

TEXT_ALIGN_LEFT = "left"
TEXT_ALIGN_CENTER = "center"
TEXT_ALIGN_RIGHT = "right"
FITZ_TEXT_ALIGN = {
    TEXT_ALIGN_LEFT: 0,
    TEXT_ALIGN_CENTER: 1,
    TEXT_ALIGN_RIGHT: 2,
}
PDF_TEXT_LINEHEIGHT = 1.0

def normalize_box_rotation(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 0
    normalized = parsed % 360
    return normalized if normalized in {0, 90, 180, 270} else 0


def get_rotated_textbox_rect(rect: fitz.Rect, page_rect: fitz.Rect, rotate: int) -> fitz.Rect:
    rot = normalize_box_rotation(rotate)
    if rot not in (90, 270):
        return fitz.Rect(rect)

    width = max(0.0, float(rect.width))
    height = max(0.0, float(rect.height))
    if width == 0.0 or height == 0.0:
        return fitz.Rect(rect)

    cx = (rect.x0 + rect.x1) * 0.5
    cy = (rect.y0 + rect.y1) * 0.5
    rotated = fitz.Rect(
        cx - height * 0.5,
        cy - width * 0.5,
        cx + height * 0.5,
        cy + width * 0.5,
    )

    dx = 0.0
    dy = 0.0
    if rotated.x0 < page_rect.x0:
        dx = page_rect.x0 - rotated.x0
    elif rotated.x1 > page_rect.x1:
        dx = page_rect.x1 - rotated.x1
    if rotated.y0 < page_rect.y0:
        dy = page_rect.y0 - rotated.y0
    elif rotated.y1 > page_rect.y1:
        dy = page_rect.y1 - rotated.y1
    if dx or dy:
        rotated = fitz.Rect(
            rotated.x0 + dx,
            rotated.y0 + dy,
            rotated.x1 + dx,
            rotated.y1 + dy,
        )
    return rotated


def update_pp_json_should_translate(job_dir: Path) -> None:
    pp_dir = job_dir / "pp_json"
    if not pp_dir.exists():
        return
    try:
        import paragraph_extract  # type: ignore
    except Exception as exc:
        logger.warning("paragraph_extract import failed: %s", exc)
        return
    align_fn = getattr(paragraph_extract, "align_and_update_json", None)
    if not callable(align_fn):
        logger.warning("paragraph_extract.align_and_update_json unavailable")
        return
    for path in sorted(pp_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            updated = align_fn(data)
            path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            logger.warning("paragraph_extract update failed for %s: %s", path.name, exc)


def bbox_to_poly(
    bbox: dict[str, Any] | list[float] | tuple[float, float, float, float],
) -> list[list[float]]:
    if isinstance(bbox, dict):
        x = float(bbox.get("x", 0.0))
        y = float(bbox.get("y", 0.0))
        w = float(bbox.get("w", 0.0))
        h = float(bbox.get("h", 0.0))
    elif isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        x, y, w, h = [float(v) for v in bbox]
    else:
        return []
    return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]


def _dedupe_box_signature(box: dict[str, Any]) -> tuple[Any, ...] | None:
    if not bool(box.get("auto_generated", True)):
        return None
    bbox = box.get("bbox")
    text = str(box.get("text", "")).strip()
    deleted = bool(box.get("deleted"))
    if isinstance(bbox, dict):
        try:
            coords = (
                round(float(bbox.get("x", 0.0)), 1),
                round(float(bbox.get("y", 0.0)), 1),
                round(float(bbox.get("w", 0.0)), 1),
                round(float(bbox.get("h", 0.0)), 1),
            )
        except (TypeError, ValueError):
            return None
    elif isinstance(bbox, (list, tuple)) and len(bbox) == 4:
        try:
            coords = tuple(round(float(v), 1) for v in bbox)
        except (TypeError, ValueError):
            return None
    else:
        return None
    return coords + (
        text,
        deleted,
        normalize_text_align(box.get("text_align")),
        normalize_box_rotation(box.get("rotation")),
    )


def normalize_text_align(value: Any) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in FITZ_TEXT_ALIGN:
            return normalized
    return TEXT_ALIGN_LEFT


def _filter_page_payload_by_score(data: dict[str, Any], min_score: float) -> dict[str, Any]:
    if min_score <= 0:
        return dict(data)

    rec_polys = list(data.get("rec_polys", []) or [])
    rec_texts = list(data.get("rec_texts", []) or [])
    edit_texts = list(data.get("edit_texts", []) or [])
    rec_scores = list(data.get("rec_scores", []) or [])
    count = len(rec_polys)
    if count == 0:
        return dict(data)

    if not edit_texts:
        edit_texts = list(rec_texts)

    keep_indexes: list[int] = []
    filtered_scores: list[float] = []
    for idx in range(count):
        score = float(rec_scores[idx]) if idx < len(rec_scores) else 1.0
        if score < min_score:
            continue
        keep_indexes.append(idx)
        filtered_scores.append(score)

    if len(keep_indexes) == count:
        filtered = dict(data)
        filtered["edit_texts"] = edit_texts
        filtered["rec_scores"] = filtered_scores
        return filtered

    def _filter_list(values: Any) -> list[Any]:
        if not isinstance(values, list):
            return []
        return [values[idx] for idx in keep_indexes if idx < len(values)]

    filtered = dict(data)
    filtered["rec_polys"] = _filter_list(rec_polys)
    filtered["rec_texts"] = _filter_list(rec_texts)
    filtered["edit_texts"] = _filter_list(edit_texts)
    filtered["rec_scores"] = filtered_scores
    return filtered


def load_page_data(
    page_json_path: Path,
    edits_boxes: list[dict[str, Any]] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if data is None:
        data = json.loads(page_json_path.read_text(encoding="utf-8"))
    if edits_boxes is None:
        data = _filter_page_payload_by_score(data, state.OCR_MIN_LINE_SCORE)
    if edits_boxes is not None:
        rec_polys: list[list[list[float]]] = []
        rec_texts: list[str] = []
        edit_texts: list[str] = []
        rec_scores: list[float] = []
        font_sizes: list[float] = []
        colors: list[str] = []
        alignments: list[str] = []
        rotations: list[int] = []
        box_ids: list[int] = []
        no_clips: list[bool] = []
        auto_generated_flags: list[bool] = []
        tm_source_texts: list[str] = []
        tm_source_normalizeds: list[str] = []
        tm_target_langs: list[str] = []
        tm_document_modes: list[str] = []
        seen_signatures: set[tuple[Any, ...]] = set()
        for box in edits_boxes:
            if not isinstance(box, dict):
                continue
            signature = _dedupe_box_signature(box)
            if signature is not None:
                if signature in seen_signatures:
                    continue
                seen_signatures.add(signature)
            if box.get("deleted"):
                continue
            poly = bbox_to_poly(box.get("bbox"))
            if not poly:
                continue
            text = str(box.get("text", ""))
            rec_polys.append(poly)
            rec_texts.append(text)
            edit_texts.append(text)
            rec_scores.append(1.0)
            font_sizes.append(float(box.get("font_size") or 0.0))
            colors.append(str(box.get("color") or state.DEFAULT_TEXT_COLOR))
            alignments.append(normalize_text_align(box.get("text_align")))
            rotations.append(normalize_box_rotation(box.get("rotation")))
            box_ids.append(int(box.get("id") or len(box_ids)))
            no_clips.append(bool(box.get("no_clip")))
            auto_generated_flags.append(bool(box.get("auto_generated", True)))
            tm_source_texts.append(str(box.get("tm_source_text") or ""))
            tm_source_normalizeds.append(str(box.get("tm_source_normalized") or ""))
            tm_target_langs.append(str(box.get("tm_target_lang") or ""))
            tm_document_modes.append(str(box.get("tm_document_mode") or ""))
        count = len(rec_polys)
    else:
        rec_polys = data.get("rec_polys", []) or []
        rec_texts = data.get("rec_texts", []) or []
        edit_texts = data.get("edit_texts", []) or []
        rec_scores = data.get("rec_scores", []) or []
        font_sizes = []
        colors = []
        alignments = []
        rotations = []
        box_ids = []
        no_clips = []
        auto_generated_flags = []
        tm_source_texts = []
        tm_source_normalizeds = []
        tm_target_langs = []
        tm_document_modes = []
        count = len(rec_polys)

    if not edit_texts:
        edit_texts = list(rec_texts)
    if len(edit_texts) < count:
        edit_texts = list(edit_texts) + list(rec_texts[len(edit_texts) : count])
    if len(rec_scores) < count:
        rec_scores = list(rec_scores) + [0.0] * (count - len(rec_scores))

    image_size = data.get("coord_transform", {}).get("image_size_px", None)
    return {
        "page_index_0based": int(data.get("page_index_0based", 0)),
        "input_image": Path(data.get("input_path", "")).name,
        "image_size_px": image_size,
        "rec_polys": rec_polys,
        "rec_texts": rec_texts,
        "edit_texts": edit_texts,
        "rec_scores": rec_scores,
        "font_sizes": font_sizes,
        "colors": colors,
        "alignments": alignments,
        "rotations": rotations,
        "box_ids": box_ids,
        "no_clips": no_clips,
        "auto_generated_flags": auto_generated_flags,
        "tm_source_texts": tm_source_texts,
        "tm_source_normalizeds": tm_source_normalizeds,
        "tm_target_langs": tm_target_langs,
        "tm_document_modes": tm_document_modes,
    }


def hex_to_rgb(
    value: str | None, default: tuple[float, float, float] = (0.0, 0.0, 1.0)
) -> tuple[float, float, float]:
    if not value:
        return default
    value = value.strip().lstrip("#")
    if len(value) == 3:
        value = "".join(ch * 2 for ch in value)
    if len(value) != 6:
        return default
    try:
        r = int(value[0:2], 16) / 255.0
        g = int(value[2:4], 16) / 255.0
        b = int(value[4:6], 16) / 255.0
        return (r, g, b)
    except ValueError:
        return default


def resolve_fontfile() -> str | None:
    for candidate in state.FONT_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    return None

# 換行
def wrap_text_lines(text: str, max_width: float, font: fitz.Font, font_size: float) -> list[str]:
    if not text: return []
    lines = []
    for raw_line in str(text).splitlines():
        if raw_line == "":
            lines.append("")
            continue
            
        current = ""
        for word in re.split(r'( )', raw_line):
            candidate = current + word
            if current and font.text_length(candidate, font_size) > max_width:
                lines.append(current.rstrip())
                current = word.lstrip()
            else:
                current = candidate
        if current:
            lines.append(current.rstrip())
            
    return lines


def insert_textbox_overflow_visible(
    page: fitz.Page,
    rect: fitz.Rect,
    text: str,
    *,
    fontfile: str | None,
    fontname: str | None,
    fontsize: float,
    color: tuple[float, float, float],
    align: int,
    rotate: int,
) -> dict[str, Any]:
    rect = fitz.Rect(rect)
    base_kwargs: dict[str, Any] = {
        "fontsize": float(fontsize),
        "lineheight": PDF_TEXT_LINEHEIGHT,
        "color": color,
        "align": align,
        "rotate": rotate,
    }
    if fontname:
        base_kwargs["fontname"] = fontname
    elif fontfile:
        base_kwargs["fontfile"] = fontfile
    else:
        base_kwargs["fontname"] = "helv"

    shape = page.new_shape()
    rc = shape.insert_textbox(rect, text, **base_kwargs)
    if rc >= 0:
        shape.commit()
        return {
            "ok": True,
            "fontsize": float(fontsize),
            "rect": rect,
            "rc": rc,
            "expanded": False,
        }

    target_rect = fitz.Rect(rect)
    deficit = abs(float(rc))
    if rotate == 0:
        target_rect.y1 += deficit
    elif rotate == 90:
        target_rect.x1 += deficit
    elif rotate == 180:
        target_rect.y0 -= deficit
    elif rotate == 270:
        target_rect.x0 -= deficit

    shape = page.new_shape()
    rc = shape.insert_textbox(target_rect, text, **base_kwargs)
    shape.commit()
    return {
        "ok": rc >= 0,
        "fontsize": float(fontsize),
        "rect": target_rect,
        "rc": rc,
        "expanded": target_rect != rect,
    }

def load_ocr_pages(job_dir: Path) -> list[dict[str, Any]]:
    json_dir = job_dir / "ocr_json"
    if not json_dir.exists():
        raise FileNotFoundError(f"Missing OCR JSON directory: {json_dir}")
    page_paths = sorted(json_dir.glob("*_res_with_pdf_coords.json"))
    if not page_paths:
        raise RuntimeError("No OCR JSON pages found.")
    pages: list[dict[str, Any]] = []
    for path in page_paths:
        raw = json.loads(path.read_text(encoding="utf-8"))
        pages.append(_filter_page_payload_by_score(raw, state.OCR_MIN_LINE_SCORE))
    return pages


def infer_page_index_from_name(name: str) -> int | None:
    match = re.search(r"_p(\d+)", name)
    if not match:
        return None
    try:
        return max(0, int(match.group(1)) - 1)
    except ValueError:
        return None


def load_pp_pages(job_dir: Path) -> dict[int, dict[str, Any]]:
    pp_dir = job_dir / "pp_json"
    if not pp_dir.exists():
        return {}
    pages: dict[int, dict[str, Any]] = {}
    for path in sorted(pp_dir.glob("*.json")):
        page_idx = infer_page_index_from_name(path.name)
        if page_idx is None:
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            pages[page_idx] = filter_ppstructure_data_by_score(raw, state.OCR_MIN_LINE_SCORE)
        except json.JSONDecodeError:
            continue
    return pages


def has_paragraph_translate_flags(pp_page: dict[str, Any] | None) -> bool:
    if not pp_page:
        return False
    for block in pp_page.get("parsing_res_list", []) or []:
        if isinstance(block, dict) and "should_translate" in block:
            return True
    return False


def iter_paragraph_blocks(pp_page: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not pp_page:
        return []
    blocks = pp_page.get("parsing_res_list", []) or []
    out: list[dict[str, Any]] = []
    for idx, block in enumerate(blocks):
        if not isinstance(block, dict):
            continue
        text = str(block.get("block_content") or "").strip()
        if not text:
            continue
        bbox = block.get("block_bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4):
            continue
        out.append(
            {
                "block_index": idx,
                "text": text,
                "bbox": [float(v) for v in bbox],
                "should_translate": bool(block.get("should_translate")),
                "label": block.get("block_label"),
            }
        )
    return out


def collect_table_bboxes(pp_page: dict[str, Any] | None) -> list[list[float]]:
    if not pp_page:
        return []
    table_bboxes: list[list[float]] = []
    for table in pp_page.get("table_res_list", []) or []:
        cell_boxes = table.get("cell_box_list") or []
        xs: list[float] = []
        ys: list[float] = []
        for box in cell_boxes:
            if not (isinstance(box, list) and len(box) == 4):
                continue
            xs.extend([float(box[0]), float(box[2])])
            ys.extend([float(box[1]), float(box[3])])
        if xs and ys:
            table_bboxes.append([min(xs), min(ys), max(xs), max(ys)])
    return table_bboxes


def bbox_intersects(
    bbox_a: dict[str, Any] | None,
    bbox_b: dict[str, Any] | None,
    *,
    min_overlap_ratio: float = 0.05,
) -> bool:
    if not isinstance(bbox_a, dict) or not isinstance(bbox_b, dict):
        return False
    try:
        ax1 = float(bbox_a.get("x", 0.0))
        ay1 = float(bbox_a.get("y", 0.0))
        ax2 = ax1 + float(bbox_a.get("w", 0.0))
        ay2 = ay1 + float(bbox_a.get("h", 0.0))
        bx1 = float(bbox_b.get("x", 0.0))
        by1 = float(bbox_b.get("y", 0.0))
        bx2 = bx1 + float(bbox_b.get("w", 0.0))
        by2 = by1 + float(bbox_b.get("h", 0.0))
    except (TypeError, ValueError):
        return False
    area_a = max(0.0, ax2 - ax1) * max(0.0, ay2 - ay1)
    if area_a <= 0:
        return False
    ix1 = max(ax1, bx1)
    iy1 = max(ay1, by1)
    ix2 = min(ax2, bx2)
    iy2 = min(ay2, by2)
    if ix2 <= ix1 or iy2 <= iy1:
        return False
    overlap_area = (ix2 - ix1) * (iy2 - iy1)
    return overlap_area / area_a >= min_overlap_ratio


def iter_merged_cells(pp_page: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not pp_page:
        return []
    cells: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for table in pp_page.get("table_res_list", []) or []:
        for cell in table.get("merged_cells", []) or []:
            if not isinstance(cell, dict):
                continue
            box = cell.get("cell_box")
            if not (isinstance(box, list) and len(box) == 4):
                continue
            text = str(cell.get("merged_text") or "").strip()
            # print("[iter_merged_cells]", text)
            if not text:
                continue
            original_components = cell.get("original_ocr_components") or []
            is_missing_individual = False
            if len(original_components) == 1:
                component = original_components[0]
                comp_box = component.get("box") or component.get("ocr_box")
                if isinstance(comp_box, list) and len(comp_box) == 4:
                    try:
                        is_missing_individual = all(
                            abs(float(a) - float(b)) <= 0.1 for a, b in zip(box, comp_box)
                        )
                    except (TypeError, ValueError):
                        is_missing_individual = False
            signature = tuple(round(float(v), 1) for v in box) + (text,)
            if signature in seen:
                continue
            seen.add(signature)
            cells.append(
                {
                    "cell_box": [float(v) for v in box],
                    "merged_text": text,
                    "should_translate": bool(cell.get("should_translate")),
                    "is_missing_individual": is_missing_individual,
                }
            )
    return cells


def load_page_json_data(job_dir: Path, page_idx: int) -> dict[str, Any]:
    json_dir = job_dir / "ocr_json"
    if not json_dir.exists():
        raise FileNotFoundError(f"Missing OCR JSON directory: {json_dir}")
    for path in sorted(json_dir.glob("*_res_with_pdf_coords.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if int(data.get("page_index_0based", -1)) == int(page_idx):
            return data
    raise FileNotFoundError(f"OCR page JSON not found for page {page_idx}")


def resolve_page_image_path(job_dir: Path, page_data: dict[str, Any]) -> Path:
    input_path = Path(str(page_data.get("input_path") or ""))
    candidates = []
    if input_path:
        candidates.append(input_path)
        candidates.append(job_dir / "images" / input_path.name)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    raise FileNotFoundError(f"Page image not found for {input_path.name or 'unknown image'}")


def clamp_bbox_to_image(
    bbox: dict[str, Any],
    image_width: int,
    image_height: int,
) -> dict[str, int]:
    x = max(0, int(round(float(bbox.get("x", 0.0)))))
    y = max(0, int(round(float(bbox.get("y", 0.0)))))
    w = max(1, int(round(float(bbox.get("w", 0.0)))))
    h = max(1, int(round(float(bbox.get("h", 0.0)))))
    x2 = min(image_width, x + w)
    y2 = min(image_height, y + h)
    x = min(x, max(0, image_width - 1))
    y = min(y, max(0, image_height - 1))
    return {"x": x, "y": y, "w": max(1, x2 - x), "h": max(1, y2 - y)}


def build_region_rows(
    rec_polys: list[list[list[float]]],
    rec_texts: list[str],
) -> list[str]:
    items: list[tuple[float, float, float, float, str]] = []
    for poly, text in zip(rec_polys, rec_texts):
        text_value = str(text or "").strip()
        if not text_value:
            continue
        if not isinstance(poly, list) or len(poly) < 4:
            items.append((float(len(items)), float(len(items)), 0.0, 0.0, text_value))
            continue
        xs: list[float] = []
        ys: list[float] = []
        for point in poly[:4]:
            if not isinstance(point, (list, tuple)) or len(point) < 2:
                continue
            xs.append(float(point[0]))
            ys.append(float(point[1]))
        if not xs or not ys:
            items.append((float(len(items)), float(len(items)), 0.0, 0.0, text_value))
            continue
        items.append((min(ys), min(xs), max(xs) - min(xs), max(ys) - min(ys), text_value))

    if not items:
        return []

    row_threshold = max(
        12.0,
        min((item[3] for item in items if item[3] > 0.0), default=12.0) * 0.8,
    )
    items.sort(key=lambda item: (round(item[0], 1), round(item[1], 1)))

    rows: list[list[tuple[float, float, float, float, str]]] = []
    for item in items:
        if not rows:
            rows.append([item])
            continue
        last_row = rows[-1]
        row_y = sum(entry[0] for entry in last_row) / len(last_row)
        if abs(item[0] - row_y) <= row_threshold:
            last_row.append(item)
        else:
            rows.append([item])

    output: list[str] = []
    for row in rows:
        row.sort(key=lambda item: (round(item[1], 1), round(item[0], 1)))
        output.append("".join(item[4] for item in row))
    return output


def run_region_ocr(
    job_dir: Path,
    page_idx: int,
    bbox: dict[str, Any],
) -> dict[str, Any]:
    if cv2 is None:
        raise RuntimeError("opencv-python is required for region OCR.")
    page_data = load_page_json_data(job_dir, page_idx)
    image_path = resolve_page_image_path(job_dir, page_data)
    image = cv2.imread(image_path.as_posix())
    if image is None:
        raise RuntimeError(f"Failed to load page image: {image_path}")
    image_height, image_width = image.shape[:2]
    region_bbox = clamp_bbox_to_image(bbox, image_width, image_height)
    crop = image[
        region_bbox["y"] : region_bbox["y"] + region_bbox["h"],
        region_bbox["x"] : region_bbox["x"] + region_bbox["w"],
    ]
    if crop.size == 0:
        raise RuntimeError("Selected region is empty.")
    ok, encoded = cv2.imencode(".png", crop)
    if not ok:
        raise RuntimeError("Failed to encode selected region image.")
    image_data_url = f"data:image/png;base64,{base64.b64encode(encoded.tobytes()).decode('ascii')}"

    payload = {
        "file": base64.b64encode(encoded.tobytes()).decode("ascii"),
        "fileType": 1,
        "useDocOrientationClassify": False,
        "useTableOrientationClassify": False,
    }
    response = requests.post(state.TRITON_URL, json=payload, timeout=120)
    if response.status_code != 200:
        raise RuntimeError(f"Region OCR request failed: HTTP {response.status_code}")
    output = response.json()
    if output.get("errorCode", -1) != 0:
        raise RuntimeError(str(output.get("errorMsg") or "Region OCR failed."))
    try:
        pruned = output["result"]["tableRecResults"][0]["prunedResult"]
    except Exception as exc:
        raise RuntimeError("Unexpected region OCR response.") from exc
    pruned = dict(pruned)
    pruned["width"] = region_bbox["w"]
    pruned["height"] = region_bbox["h"]
    pruned.setdefault("input_path", str(image_path))

    from ocr_pipeline.pipeline import extract_rec_entries_from_ppstructure

    rec_polys, rec_texts, rec_scores = extract_rec_entries_from_ppstructure(
        pruned,
        skip_text_inside_table=True,
        min_line_score=state.OCR_MIN_LINE_SCORE,
        table_fallback_layout=True,
    )
    offset_polys: list[list[list[float]]] = []
    for poly in rec_polys:
        shifted: list[list[float]] = []
        for point in poly:
            shifted.append(
                [
                    float(point[0]) + float(region_bbox["x"]),
                    float(point[1]) + float(region_bbox["y"]),
                ]
            )
        offset_polys.append(shifted)
    merged_bbox: dict[str, float] | dict[str, int] = region_bbox
    if offset_polys:
        xs: list[float] = []
        ys: list[float] = []
        for poly in offset_polys:
            for point in poly[:4]:
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    xs.append(float(point[0]))
                    ys.append(float(point[1]))
        if xs and ys:
            merged_bbox = {
                "x": min(xs),
                "y": min(ys),
                "w": max(xs) - min(xs),
                "h": max(ys) - min(ys),
            }
    return {
        "page_index_0based": int(page_idx),
        "region_bbox": region_bbox,
        "merged_bbox": merged_bbox,
        "image_data_url": image_data_url,
        "rec_polys": offset_polys,
        "rec_texts": rec_texts,
        "rec_scores": rec_scores,
    }


def load_page_transforms(job_dir: Path) -> dict[int, dict[str, Any]]:
    json_dir = job_dir / "ocr_json"
    mapping: dict[int, dict[str, Any]] = {}
    for path in json_dir.glob("*_res_with_pdf_coords.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        page_idx = int(data.get("page_index_0based", 0))
        transform = data.get("coord_transform", {})
        img_size = transform.get("image_size_px") or []
        pdf_size = transform.get("pdf_page_size_pt") or []
        rotation = transform.get("page_rotation")
        # print(rotation)
        if len(img_size) == 2 and len(pdf_size) == 2:
            mapping[page_idx] = {
                "img_w": float(img_size[0]),
                "img_h": float(img_size[1]),
                "page_w": float(pdf_size[0]),
                "page_h": float(pdf_size[1]),
                "rotation": int(rotation) if rotation is not None else 0,
            }
    return mapping


def apply_edits_to_pdf(job_id: str, job_dir: Path, edits: dict[str, Any]) -> Path:
    from pipeline_ocr_overlay import px_point_to_pdf_pt

    pdf_path = job_dir / f"{job_id}.pdf"
    if not pdf_path.exists():
        raise FileNotFoundError(f"Missing PDF: {pdf_path}")

    page_transforms = load_page_transforms(job_dir)
    if not page_transforms:
        raise RuntimeError("Missing OCR coord transform data.")

    pages_by_index = {
        int(p.get("page_index_0based", 0)): p
        for p in edits.get("pages", [])
        if isinstance(p, dict)
    }

    fontfile = resolve_fontfile()
    if not fontfile:
        logger.warning("No CJK font file found for edited PDF output; falling back to helv.")
    debug_boxes = os.getenv("DEBUG_EDIT_BOXES") == "1"
    doc = fitz.open(pdf_path)
    for page_idx in range(doc.page_count):
        page = doc.load_page(page_idx)
        page_edits = pages_by_index.get(page_idx)
        if not page_edits:
            continue
        transform = page_transforms.get(page_idx)
        if not transform:
            continue
        img_w = float(transform.get("img_w", 0.0))
        img_h = float(transform.get("img_h", 0.0))
        page_w = float(transform.get("page_w", 0.0))
        page_h = float(transform.get("page_h", 0.0))
        rotation = int(transform.get("rotation", 0))
        if img_w <= 0 or img_h <= 0:
            continue
        sx = page_w / img_w
        sy = page_h / img_h
        page_fontname: str | None = None
        if fontfile:
            try:
                page.insert_font(fontname="NotoSansTC", fontfile=fontfile)
                page_fontname = "NotoSansTC"
            except RuntimeError as exc:
                logger.warning("Failed to register PDF edit font %s: %s", fontfile, exc)
                page_fontname = None

        dbg_shape = page.new_shape() if debug_boxes else None
        for box in page_edits.get("boxes", []):
            if not isinstance(box, dict) or box.get("deleted"):
                continue
            bbox = box.get("bbox")
            if isinstance(bbox, dict):
                x = float(bbox.get("x", 0.0))
                y = float(bbox.get("y", 0.0))
                w = float(bbox.get("w", 0.0))
                h = float(bbox.get("h", 0.0))
            elif isinstance(bbox, (list, tuple)) and len(bbox) == 4:
                x, y, w, h = [float(v) for v in bbox]
            else:
                continue
            text = str(box.get("text", "")).strip()
            if not text:
                continue

            p1 = px_point_to_pdf_pt(x, y, img_w, img_h, page_w, page_h, rotation)
            p2 = px_point_to_pdf_pt(x + w, y, img_w, img_h, page_w, page_h, rotation)
            p3 = px_point_to_pdf_pt(x + w, y + h, img_w, img_h, page_w, page_h, rotation)
            p4 = px_point_to_pdf_pt(x, y + h, img_w, img_h, page_w, page_h, rotation)
            xs = [p1[0], p2[0], p3[0], p4[0]]
            ys = [p1[1], p2[1], p3[1], p4[1]]
            rect = fitz.Rect(min(xs), min(ys), max(xs), max(ys))
            if rect.is_empty:
                continue
            if dbg_shape is not None:
                dbg_shape.draw_rect(rect)
                dbg_shape.finish(color=(1, 0, 0), width=0.6)

            font_size_px = float(box.get("font_size") or 0.0)
            if font_size_px <= 0:
                font_size_px = state.DEFAULT_FONT_SIZE_PX
            font_size_pt = font_size_px * (page_h / img_h)
            color = hex_to_rgb(box.get("color"))
            rotate = normalize_box_rotation(box.get("rotation"))
            pdf_rotate = (rotation + ((360 - rotate) % 360)) % 360
            text_align = normalize_text_align(box.get("text_align"))
            # Editor-side rotation already updates the stored bbox geometry.
            # Use the saved rectangle directly so the generated PDF matches
            # the on-screen editor position and size.
            textbox_rect = fitz.Rect(rect)
            insert_textbox_overflow_visible(
                page,
                textbox_rect,
                text,
                fontfile=fontfile,
                fontname=page_fontname,
                fontsize=font_size_pt,
                color=color,
                align=FITZ_TEXT_ALIGN[text_align],
                rotate=pdf_rotate,
            )
        if dbg_shape is not None:
            dbg_shape.commit()

    out_path = job_dir / "edited.pdf"
    doc.save(out_path.as_posix())
    doc.close()
    return out_path
