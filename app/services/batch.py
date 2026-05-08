from __future__ import annotations

import datetime
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from . import glossary, jobs, ocr, openai_config, state, translation_memory

logger = logging.getLogger(__name__)
TERMINAL_BATCH_STATUSES = {"completed", "failed", "canceled", "cancelled"}


def _is_terminal_batch_status(status: Any) -> bool:
    return str(status or "").strip().lower() in TERMINAL_BATCH_STATUSES


def _build_batch_status_meta(
    job_id: str,
    target_lang: str,
    model_name: str,
    existing_status: dict[str, Any] | None = None,
) -> dict[str, Any]:
    existing_status = existing_status or {}
    started_at = existing_status.get("started_at")
    if started_at is None:
        started_at = time.time()
    return {
        "job_id": job_id,
        "started_at": started_at,
        "model": str(existing_status.get("model") or model_name),
        "target_lang": str(existing_status.get("target_lang") or target_lang),
    }


def _batch_key_map_path(job_dir: Path) -> Path:
    return job_dir / "batch_key_map.json"


def _write_batch_key_map(job_dir: Path, key_map: dict[str, dict[str, str]]) -> None:
    _batch_key_map_path(job_dir).write_text(
        json.dumps(key_map, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _load_batch_key_map(job_dir: Path) -> dict[str, dict[str, str]]:
    path = _batch_key_map_path(job_dir)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    result: dict[str, dict[str, str]] = {}
    for custom_id, item in data.items():
        if not isinstance(custom_id, str) or not isinstance(item, dict):
            continue
        result[custom_id] = {
            "source_text": str(item.get("source_text") or ""),
            "source_normalized": str(item.get("source_normalized") or ""),
        }
    return result


def resolve_document_mode(value: Any) -> str:
    return jobs.normalize_document_mode(value)


def use_merged_cells_for_mode(document_mode: str) -> bool:
    return resolve_document_mode(document_mode) in {"form", "general"}


def use_structured_blocks_for_mode(document_mode: str) -> bool:
    return resolve_document_mode(document_mode) in {"form", "general"}


def prefer_merged_cells_only(document_mode: str, merged_cells: list[dict[str, Any]]) -> bool:
    return resolve_document_mode(document_mode) == "form" and bool(merged_cells)


def _contains_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff\u3040-\u309F\u30A0-\u30FF]", text or ""))


def _contains_english(text: str) -> bool:
    return bool(re.search(r"[A-Za-z]", text or ""))


def should_translate_merged_cell(cell: dict[str, Any], document_mode: str) -> bool:
    if not cell.get("should_translate"):
        return False
    mode = resolve_document_mode(document_mode)
    if mode == "form":
        return True
    text = normalize_for_translation(str(cell.get("merged_text") or ""))
    return _contains_cjk(text) and not _contains_english(text)


def normalize_text(text: str) -> str:
    if not text: 
        return ""

    text = text.replace("\\n", "\n") 
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def normalize_for_translation(text: str) -> str:
    return translation_memory.normalize_source_text(text)


def is_numeric_only(text: str) -> bool:
    clean = re.sub(r"\s+", "", str(text or ""))
    if not clean:
        return False
    return bool(state.NUMERIC_ONLY_RE.fullmatch(clean))


def parse_batch_custom_id(custom_id: str) -> tuple[int, int] | None:
    m = re.match(r"p(\d+)-l(\d+)$", custom_id or "")
    if not m:
        return None
    return int(m.group(1)), int(m.group(2))


def extract_batch_translation(item: dict[str, Any]) -> str:
    body = item.get("response", {}).get("body", {}) or {}
    if "output_text" in body:
        return str(body.get("output_text") or "").strip()
    choices = body.get("choices", []) or []
    if choices:
        return str(choices[0].get("message", {}).get("content", "")).strip()
    return ""


def poly_to_bbox(poly: list[list[float]] | None) -> dict[str, float] | None:
    if not poly or len(poly) < 4:
        return None
    xs = [float(p[0]) for p in poly if isinstance(p, (list, tuple)) and len(p) >= 2]
    ys = [float(p[1]) for p in poly if isinstance(p, (list, tuple)) and len(p) >= 2]
    if not xs or not ys:
        return None
    x1, y1, x2, y2 = min(xs), min(ys), max(xs), max(ys)
    return {"x": x1, "y": y1, "w": x2 - x1, "h": y2 - y1}


def bbox_list_center_in_tables(
    bbox: list[float] | None,
    table_bboxes: list[list[float]],
) -> bool:
    if not bbox or len(bbox) != 4 or not table_bboxes:
        return False
    cx = (float(bbox[0]) + float(bbox[2])) * 0.5
    cy = (float(bbox[1]) + float(bbox[3])) * 0.5
    return any(tb[0] <= cx <= tb[2] and tb[1] <= cy <= tb[3] for tb in table_bboxes)


def bbox_list_overlaps_tables(
    bbox: list[float] | None,
    table_bboxes: list[list[float]],
    min_overlap_ratio: float = 0.15,
) -> bool:
    if not bbox or len(bbox) != 4 or not table_bboxes:
        return False
    x1, y1, x2, y2 = [float(v) for v in bbox]
    width = max(0.0, x2 - x1)
    height = max(0.0, y2 - y1)
    area = width * height
    if area <= 0:
        return False
    for tb in table_bboxes:
        ix1 = max(x1, float(tb[0]))
        iy1 = max(y1, float(tb[1]))
        ix2 = min(x2, float(tb[2]))
        iy2 = min(y2, float(tb[3]))
        if ix2 <= ix1 or iy2 <= iy1:
            continue
        overlap_area = (ix2 - ix1) * (iy2 - iy1)
        if overlap_area / area >= min_overlap_ratio:
            return True
    return False


def is_chart_block(block: dict[str, Any] | None) -> bool:
    return str((block or {}).get("label") or "").strip().lower() == "chart"


def _bbox_contains(
    outer: list[float] | None,
    inner: list[float] | None,
    *,
    tolerance: float = 2.0,
) -> bool:
    if not outer or not inner or len(outer) != 4 or len(inner) != 4:
        return False
    return (
        float(outer[0]) <= float(inner[0]) + tolerance
        and float(outer[1]) <= float(inner[1]) + tolerance
        and float(outer[2]) >= float(inner[2]) - tolerance
        and float(outer[3]) >= float(inner[3]) - tolerance
    )


def filter_structured_blocks_for_mode(
    paragraph_blocks: list[dict[str, Any]],
    *,
    document_mode: str,
) -> list[dict[str, Any]]:
    if resolve_document_mode(document_mode) != "form":
        return paragraph_blocks

    filtered: list[dict[str, Any]] = []
    for idx, block in enumerate(paragraph_blocks):
        label = str(block.get("label") or "").strip().lower()
        if label not in {"figure_title", "header"}:
            filtered.append(block)
            continue

        bbox = block.get("bbox")
        if not (isinstance(bbox, list) and len(bbox) == 4):
            filtered.append(block)
            continue

        is_union_block = False
        for other_idx, other in enumerate(paragraph_blocks):
            if idx == other_idx:
                continue
            other_label = str(other.get("label") or "").strip().lower()
            if other_label != label:
                continue
            other_bbox = other.get("bbox")
            if not _bbox_contains(bbox, other_bbox):
                continue
            block_area = max(0.0, float(bbox[2]) - float(bbox[0])) * max(0.0, float(bbox[3]) - float(bbox[1]))
            other_area = max(0.0, float(other_bbox[2]) - float(other_bbox[0])) * max(0.0, float(other_bbox[3]) - float(other_bbox[1]))
            if other_area <= 0 or block_area <= other_area:
                continue
            is_union_block = True
            break

        if not is_union_block:
            filtered.append(block)

    return filtered


def should_translate_structured_block(
    block: dict[str, Any] | None,
    *,
    document_mode: str,
    merged_only: bool,
) -> bool:
    if not block or not block.get("should_translate"):
        return False
    if is_chart_block(block):
        return False
    if not merged_only:
        return True
    if resolve_document_mode(document_mode) != "form":
        return False
    label = str(block.get("label") or "").strip().lower()
    return label in {"figure_title", "header"}


def should_skip_ocr_line_for_structured_blocks(
    bbox: list[float] | None,
    paragraph_blocks: list[dict[str, Any]],
) -> bool:
    if not bbox or len(bbox) != 4:
        return False
    for block in paragraph_blocks:
        if not block.get("should_translate"):
            continue
        if is_chart_block(block):
            continue
        if bbox_list_overlaps_tables(bbox, [block.get("bbox")], min_overlap_ratio=0.15):
            return True
    return False


def get_azure_client():
    return openai_config.create_sync_client()


def _build_inline_glossary_instructions(glossary_entries: list[tuple[str, str]] | None) -> str:
    if not glossary_entries:
        return ""
    lines = ["Use the following terminology when applicable:"]
    for src, dst in glossary_entries[:50]:
        src_text = str(src or "").strip()
        dst_text = str(dst or "").strip()
        if not src_text or not dst_text:
            continue
        lines.append(f"- {src_text} -> {dst_text}")
    return "\n".join(lines)


def translate_texts_for_region(
    texts: list[str],
    *,
    target_lang: str,
    model_name: str,
    system_prompt: str | None = None,
    glossary_entries: list[tuple[str, str]] | None = None,
) -> list[str]:
    if not texts:
        return []

    client = get_azure_client()
    prompt_parts = [resolve_batch_prompt(target_lang, system_prompt)]
    glossary_prompt = _build_inline_glossary_instructions(glossary_entries)
    if glossary_prompt:
        prompt_parts.append(glossary_prompt)
    prompt_parts.append("Return only the translated text for the current input.")
    final_prompt = "\n\n".join(part for part in prompt_parts if part).strip()

    outputs: list[str] = []
    for raw_text in texts:
        source_text = str(raw_text or "").strip()
        normalized_source = normalize_for_translation(source_text)
        if not normalized_source:
            outputs.append("")
            continue
        if is_numeric_only(normalized_source) or not _contains_cjk(normalized_source):
            outputs.append(source_text)
            continue
        response = client.responses.create(
            model=model_name,
            instructions=final_prompt,
            input=source_text,
        )
        translated = str(response.output_text or "").strip()
        outputs.append(normalize_text(translated) or source_text)
    return outputs



def resolve_batch_prompt(target_lang: str, override: str | None = None) -> str:
    if override:
        return override.strip()
    normalized = (target_lang or "").strip().lower()
    if normalized in {"en", "english", "en-us", "en-gb"}:
        return state.AZURE_BATCH_SYSTEM_PROMPT
    return "\n".join(
        [
            "You are a professional translator.",
            f"Translate the text to {target_lang} accurately and literally.",
            "Do NOT summarize, paraphrase, explain, or add content.",
            "Preserve all numbers, codes, references, and formatting.",
            "If the input is a standalone year, number, code, table number, figure number, symbol, unit, abbreviation, or non-sentence fragment, do not explain it. Return only the translated or preserved text. Examples: 2017年 -> 2017、2018年 -> 2018、N/A -> N/A",
            "CRITICAL FORMATTING RULE 1: You MUST insert a line break strictly before every numbered item (e.g., '2.', '3.', '4.').",
            "CRITICAL FORMATTING RULE 2: You MUST keep all text within the same numbered item as ONE continuous paragraph. Do NOT add line breaks inside a step.",
            "Strictly prohibit duplicate words or expressions with identical meanings; if they appear, you must remove the redundancy and keep only one.",
            "Output only the translated text."
        ]
    ).strip()

def build_batch_items(
    ocr_pages: list[dict[str, Any]],
    model_name: str,
    system_prompt: str,
    glossary_entries: list[tuple[str, str]] | None = None,
    pp_pages: dict[int, dict[str, Any]] | None = None,
    target_lang: str = "en",
    document_mode: str = "form",
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, dict[str, str]], dict[str, str]]:
    items: list[dict[str, Any]] = []
    alias_map: dict[str, str] = {}
    key_map: dict[str, dict[str, str]] = {}
    prefilled: dict[str, str] = {}
    seen: dict[str, str] = {}
    pp_pages = pp_pages or {}
    mode = resolve_document_mode(document_mode)
    translate_merged_cells = use_merged_cells_for_mode(document_mode)
    use_structured_blocks = use_structured_blocks_for_mode(document_mode)

    with state.TRANSLATION_MEMORY_LOCK:
        translation_memory_data = translation_memory.load_translation_memory()
        tm_dirty = False

    def _add_item(custom_id: str, raw_text: str) -> None:
        nonlocal tm_dirty
        source_text = str(raw_text or "")
        normalized_source = normalize_for_translation(source_text)
        if not normalized_source:
            return
        if not re.search(r"[\u4e00-\u9fff\u3040-\u309F\u30A0-\u30FF]", normalized_source):
            return
        tm_key, tm_entry = translation_memory.get_tm_entry(
            translation_memory_data,
            source_text,
            target_lang,
            document_mode,
            source_normalized=normalized_source,
        )
        if tm_key and tm_entry:
            translated_text = translation_memory.extract_target_text(tm_entry)
            if translated_text:
                prefilled[custom_id] = translated_text
                translation_memory.touch_entry(tm_entry)
                if tm_key != translation_memory.make_tm_key(
                    source_text,
                    target_lang,
                    document_mode,
                    source_normalized=normalized_source,
                ):
                    translation_memory.upsert_entry(
                        translation_memory_data,
                        source_text,
                        translated_text,
                        target_lang,
                        document_mode,
                        source_normalized=normalized_source,
                        source=str(tm_entry.get("source") or "batch"),
                    )
                tm_dirty = True
                return
        clean = glossary.apply_glossary(normalized_source, glossary_entries)
        if not clean:
            return
        dedupe_key = normalized_source
        if dedupe_key in seen:
            alias_map[custom_id] = seen[dedupe_key]
            return
        seen[dedupe_key] = custom_id
        key_map[custom_id] = {
            "source_text": source_text,
            "source_normalized": normalized_source,
        }
        items.append(
            {
                "custom_id": custom_id,
                "method": "POST",
                "url": "/v1/chat/completions",
                "body": {
                    "model": model_name,
                    "messages": [
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": clean},
                    ],
                },
            }
        )

    for page in ocr_pages:
        page_idx = int(page.get("page_index_0based", 0))
        pp_page = pp_pages.get(page_idx)
        texts = page.get("rec_texts", []) or []
        rec_polys = page.get("rec_polys", []) or []

        if mode == "scanned":
            for idx, text in enumerate(texts):
                custom_id = f"p{page_idx:04d}-l{idx:04d}"
                _add_item(custom_id, text)
            continue

        merged_cells = ocr.iter_merged_cells(pp_page) if translate_merged_cells else []
        merged_only = prefer_merged_cells_only(document_mode, merged_cells)
        table_bboxes = ocr.collect_table_bboxes(pp_page) if merged_cells else []
        skip_table_lines = bool(table_bboxes)
        has_paragraph_flags = use_structured_blocks and ocr.has_paragraph_translate_flags(pp_page)
        paragraph_blocks = ocr.iter_paragraph_blocks(pp_page) if use_structured_blocks else []
        paragraph_blocks = filter_structured_blocks_for_mode(
            paragraph_blocks,
            document_mode=document_mode,
        )
        if use_structured_blocks:
            for block in paragraph_blocks:
                if not should_translate_structured_block(
                    block,
                    document_mode=document_mode,
                    merged_only=merged_only,
                ):
                    continue
                if table_bboxes and bbox_list_overlaps_tables(block.get("bbox"), table_bboxes):
                    continue
                block_idx = int(block.get("block_index", 0))
                custom_id = f"p{page_idx:04d}-b{block_idx:04d}"
                _add_item(custom_id, block.get("text", ""))

        for cell_idx, cell in enumerate(merged_cells):
            if not should_translate_merged_cell(cell, document_mode):
                continue
            custom_id = f"p{page_idx:04d}-c{cell_idx:04d}"
            _add_item(custom_id, cell.get("merged_text", ""))

        for idx, text in enumerate(texts):
            if merged_only:
                continue
            if skip_table_lines and table_bboxes and idx < len(rec_polys):
                bbox = poly_to_bbox(rec_polys[idx])
                if bbox:
                    if bbox_list_overlaps_tables(
                        [
                            float(bbox["x"]),
                            float(bbox["y"]),
                            float(bbox["x"]) + float(bbox["w"]),
                            float(bbox["y"]) + float(bbox["h"]),
                        ],
                        table_bboxes,
                    ):
                        continue
                    if has_paragraph_flags and should_skip_ocr_line_for_structured_blocks(
                        [
                            float(bbox["x"]),
                            float(bbox["y"]),
                            float(bbox["x"]) + float(bbox["w"]),
                            float(bbox["y"]) + float(bbox["h"]),
                        ],
                        paragraph_blocks,
                    ):
                        continue
            elif has_paragraph_flags and idx < len(rec_polys):
                bbox = poly_to_bbox(rec_polys[idx])
                if bbox and should_skip_ocr_line_for_structured_blocks(
                    [
                        float(bbox["x"]),
                        float(bbox["y"]),
                        float(bbox["x"]) + float(bbox["w"]),
                        float(bbox["y"]) + float(bbox["h"]),
                    ],
                    paragraph_blocks,
                ):
                    continue
            custom_id = f"p{page_idx:04d}-l{idx:04d}"
            _add_item(custom_id, text)

    if tm_dirty:
        translation_memory.write_translation_memory(translation_memory_data)

    return items, alias_map, key_map, prefilled


def write_jsonl(path: Path, items: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as f:
        for item in items:
            f.write(json.dumps(item, ensure_ascii=False) + "\n")


def build_translations_from_jsonl_text(
    raw_text: str,
    alias_map: dict[str, str] | None = None,
    prefilled: dict[str, str] | None = None,
) -> dict[str, str]:
    translations: dict[str, str] = {}
    if prefilled:
        translations.update(prefilled)
    for line in raw_text.splitlines():
        if not line.strip():
            continue
        item = json.loads(line)
        custom_id = item.get("custom_id", "")
        translated = extract_batch_translation(item)
        if translated:
            translations[custom_id] = translated
    if alias_map:
        for alias_id, canonical_id in alias_map.items():
            if alias_id in translations:
                continue
            if canonical_id in translations:
                translations[alias_id] = translations[canonical_id]
    return translations


def build_edits_payload_from_translations(
    ocr_pages: list[dict[str, Any]],
    translations: dict[str, str],
    pp_pages: dict[int, dict[str, Any]] | None = None,
    target_lang: str = "en",
    document_mode: str = "form",
) -> dict[str, Any]:
    pages_payload: list[dict[str, Any]] = []
    pp_pages = pp_pages or {}
    mode = resolve_document_mode(document_mode)
    translate_merged_cells = use_merged_cells_for_mode(document_mode)
    use_structured_blocks = use_structured_blocks_for_mode(document_mode)

    def build_tm_meta(source_text: str) -> dict[str, Any]:
        if mode != "form":
            return {}
        normalized_source = normalize_for_translation(source_text)
        if not normalized_source:
            return {}
        return {
            "tm_source_text": str(source_text or ""),
            "tm_source_normalized": normalized_source,
            "tm_target_lang": str(target_lang or "en"),
            "tm_document_mode": mode,
        }
    
    for page in ocr_pages:
        page_idx = int(page.get("page_index_0based", 0))
        pp_page = pp_pages.get(page_idx)
        rec_polys = page.get("rec_polys", []) or []
        rec_texts = page.get("rec_texts", []) or []
        boxes: list[dict[str, Any]] = []

        if mode == "scanned":
            for idx, poly in enumerate(rec_polys):
                custom_id = f"p{page_idx:04d}-l{idx:04d}"
                text = translations.get(custom_id)
                if not text:
                    continue
                text = normalize_text(text)
                if not text or is_numeric_only(text):
                    continue
                bbox = poly_to_bbox(poly)
                if not bbox:
                    continue
                boxes.append(
                    {
                        "id": idx,
                        "bbox": bbox,
                        "text": text,
                        "deleted": False,
                        "auto_generated": True,
                        **build_tm_meta(rec_texts[idx] if idx < len(rec_texts) else ""),
                    }
                )
            pages_payload.append({"page_index_0based": page_idx, "boxes": boxes})
            continue

        merged_cells = ocr.iter_merged_cells(pp_page) if translate_merged_cells else []
        merged_only = prefer_merged_cells_only(document_mode, merged_cells)
        table_bboxes = ocr.collect_table_bboxes(pp_page) if merged_cells else []
        skip_table_lines = bool(table_bboxes)
        has_paragraph_flags = use_structured_blocks and ocr.has_paragraph_translate_flags(pp_page)
        paragraph_blocks = ocr.iter_paragraph_blocks(pp_page) if use_structured_blocks else []
        paragraph_blocks = filter_structured_blocks_for_mode(
            paragraph_blocks,
            document_mode=document_mode,
        )
        

        for idx, poly in enumerate(rec_polys):
            custom_id = f"p{page_idx:04d}-l{idx:04d}"
            text = translations.get(custom_id)
            if not text:
                continue
            
            text = normalize_text(text)
            if not text:
                continue
            if is_numeric_only(text):
                continue
            bbox = poly_to_bbox(poly)
            if not bbox:
                continue
            if merged_only:
                continue
            if skip_table_lines and table_bboxes:
                if bbox_list_overlaps_tables(
                    [
                        float(bbox["x"]),
                        float(bbox["y"]),
                        float(bbox["x"]) + float(bbox["w"]),
                        float(bbox["y"]) + float(bbox["h"]),
                    ],
                    table_bboxes,
                ):
                    continue
            if has_paragraph_flags and should_skip_ocr_line_for_structured_blocks(
                [
                    float(bbox["x"]),
                    float(bbox["y"]),
                    float(bbox["x"]) + float(bbox["w"]),
                    float(bbox["y"]) + float(bbox["h"]),
                ],
                paragraph_blocks,
            ):
                continue
            boxes.append(
                {
                    "id": idx,
                    "bbox": bbox,
                    "text": text,
                    "deleted": False,
                    "auto_generated": True,
                    **build_tm_meta(rec_texts[idx] if idx < len(rec_texts) else ""),
                }
            )

        if paragraph_blocks:
            base_id = 200000
            for block in paragraph_blocks:
                if not should_translate_structured_block(
                    block,
                    document_mode=document_mode,
                    merged_only=merged_only,
                ):
                    continue
                if table_bboxes and bbox_list_overlaps_tables(block.get("bbox"), table_bboxes):
                    continue
                block_idx = int(block.get("block_index", 0))
                custom_id = f"p{page_idx:04d}-b{block_idx:04d}"
   
                block_text = translations.get(custom_id)
                if not block_text:
                    continue
                
                block_text = normalize_text(block_text)
                if not block_text:
                    continue
                if is_numeric_only(block_text):
                    continue
                bbox_list = block.get("bbox")
                if not (isinstance(bbox_list, list) and len(bbox_list) == 4):
                    continue
                bbox = {
                    "x": float(bbox_list[0]),
                    "y": float(bbox_list[1]),
                    "w": float(bbox_list[2] - bbox_list[0]),
                    "h": float(bbox_list[3] - bbox_list[1]),
                }
                boxes.append(
                    {
                        "id": base_id + block_idx,
                        "bbox": bbox,
                        "text": block_text,
                        "deleted": False,
                        "no_clip": True,
                        "auto_generated": True,
                        **build_tm_meta(block.get("text", "")),
                    }
                )

        if merged_cells:
            base_id = 100000
            for cell_idx, cell in enumerate(merged_cells):
                if not should_translate_merged_cell(cell, document_mode):
                    continue
                custom_id = f"p{page_idx:04d}-c{cell_idx:04d}"
                
                cell_text = translations.get(custom_id)
                if not cell_text:
                    continue
                
                cell_text = normalize_text(cell_text)
                if not cell_text:
                    continue
                if is_numeric_only(cell_text):
                    continue
                box = cell.get("cell_box")
                if not (isinstance(box, list) and len(box) == 4):
                    continue
                bbox = {
                    "x": float(box[0]),
                    "y": float(box[1]),
                    "w": float(box[2] - box[0]),
                    "h": float(box[3] - box[1]),
                }
                boxes.append(
                    {
                        "id": base_id + cell_idx,
                        "bbox": bbox,
                        "text": cell_text,
                        "deleted": False,
                        "auto_generated": True,
                        **build_tm_meta(cell.get("merged_text", "")),
                    }
                )

        pages_payload.append({"page_index_0based": page_idx, "boxes": boxes})

    return {"pages": pages_payload}


def run_batch_translate_job(
    job_id: str,
    job_dir: Path,
    config: dict[str, Any] | None = None,
    *,
    poll_only: bool = False,
) -> bool:
    config = config or jobs.load_batch_config(job_dir) or {}
    document_mode = resolve_document_mode(
        config.get("document_mode") or (jobs.load_job_meta(job_dir) or {}).get("document_mode")
    )
    target_lang = str(config.get("target_lang") or "en")
    model_name = str(config.get("model") or state.AZURE_BATCH_MODEL)
    system_prompt = resolve_batch_prompt(target_lang, config.get("system_prompt"))
    existing_status = jobs.load_batch_status(job_dir) or {}
    batch_id = str(existing_status.get("batch_id") or "")
    status_meta = _build_batch_status_meta(job_id, target_lang, model_name, existing_status)

    if batch_id and batch_id != "prefill_only" and not _is_terminal_batch_status(existing_status.get("status")):
        try:
            return _poll_batch_translate_job(
                job_id=job_id,
                job_dir=job_dir,
                document_mode=document_mode,
                target_lang=target_lang,
                status_meta=status_meta,
                batch_id=batch_id,
            )
        except Exception as exc:
            logger.exception("Batch translate poll failed job_id=%s error=%s", job_id, exc)
            jobs.write_batch_status(job_dir, "failed", **status_meta, batch_id=batch_id, error=str(exc))
            now_ts = time.time()
            jobs.set_job_state(
                job_dir,
                status="failed",
                stage="translate",
                error_message=str(exc),
                completed_at=now_ts,
                extra_meta={"translate_completed_at": now_ts},
            )
            return False

    if poll_only:
        return False

    jobs.set_job_state(
        job_dir,
        status="running",
        stage="translate",
        extra_meta={"translate_started_at": time.time()},
    )
    logger.info(
        "Batch translate submit job_id=%s target_lang=%s model=%s",
        job_id,
        target_lang,
        model_name,
    )
    jobs.write_batch_status(job_dir, "running", **status_meta)
    try:
        ocr_pages = ocr.load_ocr_pages(job_dir)
        pp_pages = ocr.load_pp_pages(job_dir)
        glossary_entries = glossary.load_combined_glossary()
        batch_items, alias_map, key_map, prefilled = build_batch_items(
            ocr_pages,
            model_name=model_name,
            system_prompt=system_prompt,
            glossary_entries=glossary_entries,
            pp_pages=pp_pages,
            target_lang=target_lang,
            document_mode=document_mode,
        )
        jobs.write_batch_alias_map(job_dir, alias_map)
        jobs.write_batch_prefill_map(job_dir, prefilled)
        _write_batch_key_map(job_dir, key_map)
        logger.info(
            "Batch translate collected pages=%s unique=%s dup_alias=%s tm_prefill=%s",
            len(ocr_pages),
            len(batch_items),
            len(alias_map),
            len(prefilled),
        )
        if not batch_items and not prefilled:
            raise RuntimeError("No OCR text lines found to translate.")
        if not batch_items and prefilled:
            _finalize_batch_translate_job(
                job_id=job_id,
                job_dir=job_dir,
                ocr_pages=ocr_pages,
                pp_pages=pp_pages,
                document_mode=document_mode,
                target_lang=target_lang,
                key_map=key_map,
                alias_map=alias_map,
                prefilled=prefilled,
                raw_text="",
                status_meta=status_meta,
                batch_id="prefill_only",
            )
            logger.info(
                "Batch translate completed from translation memory job_id=%s", job_id
            )
            return True

        batch_input_path = job_dir / state.BATCH_INPUT_NAME
        write_jsonl(batch_input_path, batch_items)
        logger.info(
            "Batch translate wrote input jsonl=%s", batch_input_path.resolve()
        )

        client = get_azure_client()
        with batch_input_path.open("rb") as batch_file:
            file_obj = client.files.create(
                file=batch_file,
                purpose="batch",
                extra_body={"expires_after": {"seconds": 1209600, "anchor": "created_at"}},
            )
        logger.info("Batch translate uploaded file_id=%s", file_obj.id)
        batch_obj = client.batches.create(
            input_file_id=file_obj.id,
            endpoint="chat/completions",
            completion_window=state.AZURE_BATCH_COMPLETION_WINDOW,
        )

        batch_id = batch_obj.id
        logger.info("Batch translate submitted batch_id=%s", batch_id)
        jobs.write_batch_status(job_dir, "running", **status_meta, batch_id=batch_id)
        return True
    except Exception as exc:
        logger.exception("Batch translate failed job_id=%s error=%s", job_id, exc)
        jobs.write_batch_status(job_dir, "failed", **status_meta, error=str(exc))
        now_ts = time.time()
        jobs.set_job_state(
            job_dir,
            status="failed",
            stage="translate",
            error_message=str(exc),
            completed_at=now_ts,
            extra_meta={"translate_completed_at": now_ts},
        )
        return False


def _poll_batch_translate_job(
    *,
    job_id: str,
    job_dir: Path,
    document_mode: str,
    target_lang: str,
    status_meta: dict[str, Any],
    batch_id: str,
) -> bool:
    record = jobs.job_store.get_job(job_id)
    if record is not None and record.cancel_requested:
        now_ts = time.time()
        jobs.write_batch_status(
            job_dir,
            "cancelled",
            **status_meta,
            batch_id=batch_id,
            last_check=datetime.datetime.now().isoformat(timespec="seconds"),
            error="Cancelled by user.",
        )
        jobs.set_job_state(
            job_dir,
            status="cancelled",
            stage="cancelled",
            completed_at=now_ts,
            extra_meta={"translate_completed_at": now_ts},
        )
        return True
    client = get_azure_client()
    batch_obj = client.batches.retrieve(batch_id)
    status = str(batch_obj.status or "")
    logger.info(
        "Batch translate poll job_id=%s batch_id=%s status=%s",
        job_id,
        batch_id,
        status,
    )
    jobs.write_batch_status(
        job_dir,
        status,
        **status_meta,
        batch_id=batch_id,
        last_check=datetime.datetime.now().isoformat(timespec="seconds"),
    )

    normalized_status = status.lower()
    if not _is_terminal_batch_status(normalized_status):
        return True
    if normalized_status != "completed":
        now_ts = time.time()
        error_message = f"Batch status = {status}"
        final_status = "cancelled" if normalized_status in {"canceled", "cancelled"} else "failed"
        jobs.set_job_state(
            job_dir,
            status=final_status,
            stage="translate",
            error_message=error_message,
            completed_at=now_ts,
            extra_meta={"translate_completed_at": now_ts},
        )
        return True

    output_file_id = batch_obj.output_file_id or batch_obj.error_file_id
    if not output_file_id:
        raise RuntimeError("Batch has no output_file_id/error_file_id.")

    file_response = client.files.content(output_file_id)
    raw_text = file_response.text or ""
    (job_dir / state.BATCH_OUTPUT_NAME).write_text(raw_text, encoding="utf-8")
    logger.info("Batch translate downloaded output file_id=%s", output_file_id)

    ocr_pages = ocr.load_ocr_pages(job_dir)
    pp_pages = ocr.load_pp_pages(job_dir)
    alias_map = jobs.load_batch_alias_map(job_dir)
    prefilled = jobs.load_batch_prefill_map(job_dir)
    key_map = _load_batch_key_map(job_dir)
    _finalize_batch_translate_job(
        job_id=job_id,
        job_dir=job_dir,
        ocr_pages=ocr_pages,
        pp_pages=pp_pages,
        document_mode=document_mode,
        target_lang=target_lang,
        key_map=key_map,
        alias_map=alias_map,
        prefilled=prefilled,
        raw_text=raw_text,
        status_meta=status_meta,
        batch_id=batch_id,
    )
    logger.info("Batch translate completed job_id=%s", job_id)
    return True


def _finalize_batch_translate_job(
    *,
    job_id: str,
    job_dir: Path,
    ocr_pages: list[dict[str, Any]],
    pp_pages: dict[int, dict[str, Any]] | None,
    document_mode: str,
    target_lang: str,
    key_map: dict[str, dict[str, str]],
    alias_map: dict[str, str],
    prefilled: dict[str, str],
    raw_text: str,
    status_meta: dict[str, Any],
    batch_id: str,
) -> None:
    translations = build_translations_from_jsonl_text(
        raw_text, alias_map=alias_map, prefilled=prefilled
    )
    if key_map:
        with state.TRANSLATION_MEMORY_LOCK:
            memory = translation_memory.load_translation_memory()
            now_ts = time.time()
            for custom_id, source_meta in key_map.items():
                translated = translations.get(custom_id)
                if translated:
                    translation_memory.upsert_entry(
                        memory,
                        source_meta.get("source_text", ""),
                        translated,
                        target_lang,
                        document_mode,
                        source_normalized=source_meta.get("source_normalized"),
                        source="batch",
                        now_ts=now_ts,
                    )
            translation_memory.write_translation_memory(memory)
    edits_payload = build_edits_payload_from_translations(
        ocr_pages,
        translations,
        pp_pages=pp_pages,
        target_lang=target_lang,
        document_mode=document_mode,
    )
    edits_path = job_dir / "edits.json"
    edits_path.write_text(
        json.dumps(edits_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    logger.info("Batch translate wrote edits.json=%s", edits_path.resolve())
    ocr.apply_edits_to_pdf(job_id, job_dir, edits_payload)
    logger.info("Batch translate wrote edited.pdf job_id=%s", job_id)
    jobs.write_batch_status(job_dir, "completed", **status_meta, batch_id=batch_id)
    now_ts = time.time()
    jobs.set_job_state(
        job_dir,
        status="completed",
        stage="completed",
        progress=100.0,
        completed_at=now_ts,
        extra_meta={"translate_completed_at": now_ts},
    )


def poll_active_batch_jobs(limit: int = 1) -> int:
    now_ts = time.time()
    candidates: list[tuple[float, str, Path]] = []
    for record in jobs.job_store.list_jobs(job_type="ocr_overlay"):
        if record.stage != "translate":
            continue
        if record.status not in {"running", "cancel_requested"}:
            continue
        job_dir = jobs.job_dir(record.job_id)
        batch_status = jobs.load_batch_status(job_dir) or {}
        batch_id = str(batch_status.get("batch_id") or "")
        batch_state = str(batch_status.get("status") or "").strip().lower()
        if record.cancel_requested and batch_id:
            candidates.append((0.0, record.job_id, job_dir))
            continue
        if not batch_id or batch_id == "prefill_only" or _is_terminal_batch_status(batch_state):
            continue
        updated_at = float(batch_status.get("updated_at") or 0.0)
        if updated_at and now_ts - updated_at < state.AZURE_BATCH_POLL_SECONDS:
            continue
        candidates.append((updated_at, record.job_id, job_dir))

    candidates.sort(key=lambda item: (item[0], item[1]))
    processed = 0
    for _, job_id, job_dir in candidates[: max(1, limit)]:
        config = jobs.load_batch_config(job_dir) or {}
        run_batch_translate_job(job_id, job_dir, config, poll_only=True)
        processed += 1
    return processed
