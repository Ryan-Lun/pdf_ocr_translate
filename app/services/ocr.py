from __future__ import annotations

import json
import logging
import os
import re
from pathlib import Path
from typing import Any

import fitz

from pipeline_ocr_overlay import px_point_to_pdf_pt

from . import state

logger = logging.getLogger(__name__)


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
    return coords + (text, deleted)


def load_page_data(
    page_json_path: Path,
    edits_boxes: list[dict[str, Any]] | None = None,
    data: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if data is None:
        data = json.loads(page_json_path.read_text(encoding="utf-8"))
    if edits_boxes is not None:
        rec_polys: list[list[list[float]]] = []
        rec_texts: list[str] = []
        edit_texts: list[str] = []
        rec_scores: list[float] = []
        font_sizes: list[float] = []
        colors: list[str] = []
        box_ids: list[int] = []
        no_clips: list[bool] = []
        auto_generated_flags: list[bool] = []
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
            box_ids.append(int(box.get("id") or len(box_ids)))
            no_clips.append(bool(box.get("no_clip")))
            auto_generated_flags.append(bool(box.get("auto_generated", True)))
        count = len(rec_polys)
    else:
        rec_polys = data.get("rec_polys", []) or []
        rec_texts = data.get("rec_texts", []) or []
        edit_texts = data.get("edit_texts", []) or []
        rec_scores = data.get("rec_scores", []) or []
        font_sizes = []
        colors = []
        box_ids = []
        no_clips = []
        auto_generated_flags = []
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
        "box_ids": box_ids,
        "no_clips": no_clips,
        "auto_generated_flags": auto_generated_flags,
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

def load_ocr_pages(job_dir: Path) -> list[dict[str, Any]]:
    json_dir = job_dir / "ocr_json"
    if not json_dir.exists():
        raise FileNotFoundError(f"Missing OCR JSON directory: {json_dir}")
    page_paths = sorted(json_dir.glob("*_res_with_pdf_coords.json"))
    if not page_paths:
        raise RuntimeError("No OCR JSON pages found.")
    return [json.loads(path.read_text(encoding="utf-8")) for path in page_paths]


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
            pages[page_idx] = json.loads(path.read_text(encoding="utf-8"))
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
            print("[iter_merged_cells]", text)
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
        print(rotation)
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
    try:
        font_obj = fitz.Font(fontfile=fontfile) if fontfile else fitz.Font("helv")
    except RuntimeError:
        font_obj = fitz.Font("helv")
        fontfile = None
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

        shape = page.new_shape()
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
            rotate = rotation if rotation else 0
            no_clip = bool(box.get("no_clip"))

            sx = page_w / img_w
            sy = page_h / img_h
            v_w = w * sx 
            v_h = h * sy 
            v_y = y * sy 

            lines = wrap_text_lines(text, v_w, font_obj, font_size_pt)
            if not lines:
                lines = [text]
                
            line_height = max(1.0, font_size_pt * 1.2)

            cursor_v_y = v_y + line_height
            max_lines_in_box = max(1, int(v_h // line_height))
            allow_overflow = no_clip or len(lines) > max_lines_in_box
            max_v_y = v_y + v_h if not allow_overflow else page_h - line_height * 0.2
            
            for idx, line in enumerate(lines):
                overflow = cursor_v_y > max_v_y
                if overflow and idx != 0:
                    break

                y_cursor_px = cursor_v_y / sy
                pt_unrot = px_point_to_pdf_pt(x, y_cursor_px, img_w, img_h, page_w, page_h, rotation)
                baseline = fitz.Point(pt_unrot[0], pt_unrot[1])
                
                if fontfile:
                    shape.insert_text(
                        baseline,
                        line,
                        fontfile=fontfile,
                        fontsize=font_size_pt,
                        color=color,
                        rotate=rotate,
                    )
                else:
                    shape.insert_text(
                        baseline,
                        line,
                        fontname="helv",
                        fontsize=font_size_pt,
                        color=color,
                        rotate=rotate,
                    )
                if overflow:
                    break
                cursor_v_y += line_height

        shape.commit()
        if dbg_shape is not None:
            dbg_shape.commit()

    out_path = job_dir / "edited.pdf"
    doc.save(out_path.as_posix())
    doc.close()
    return out_path
