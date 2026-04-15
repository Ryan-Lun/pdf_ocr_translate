from __future__ import annotations

import datetime
import json
import logging
import os
import re
import time
import unicodedata
from pathlib import Path
from typing import Any

from . import glossary, jobs, ocr, state, translation_memory

logger = logging.getLogger(__name__)


def normalize_text(text: str) -> str:
    if not text: 
        return ""

    text = text.replace("\\n", "\n") 
    lines = [" ".join(line.split()) for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


_PUNCT_TRANSLATION = str.maketrans(
    {
        "，": ",",
        "。": ".",
        "；": ";",
        "：": ":",
        "？": "?",
        "！": "!",
        "（": "(",
        "）": ")",
        "【": "[",
        "】": "]",
        "「": '"',
        "」": '"',
        "『": '"',
        "』": '"',
        "、": ",",
        "．": ".",
        "／": "/",
        "％": "%",
        "＋": "+",
        "－": "-",
        "～": "~",
        "—": "-",
        "–": "-",
        "…": "...",
    }
)


def normalize_for_translation(text: str) -> str:
    if text is None:
        return ""
    cleaned = unicodedata.normalize("NFKC", str(text))
    cleaned = cleaned.translate(_PUNCT_TRANSLATION)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


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


def get_azure_client():
    try:
        from dotenv import load_dotenv
        from openai import OpenAI
    except Exception as exc:
        raise RuntimeError(
            "openai and python-dotenv are required for Azure batch translation."
        ) from exc

    load_dotenv()
    api_key = os.getenv(state.AZURE_API_KEY_ENV)
    if not api_key:
        raise RuntimeError(f"Environment variable {state.AZURE_API_KEY_ENV} is not set.")
    return OpenAI(base_url=state.AZURE_BASE_URL, api_key=api_key)



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
) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str], dict[str, str]]:
    items: list[dict[str, Any]] = []
    alias_map: dict[str, str] = {}
    key_map: dict[str, str] = {}
    prefilled: dict[str, str] = {}
    seen: dict[str, str] = {}
    pp_pages = pp_pages or {}

    with state.TRANSLATION_MEMORY_LOCK:
        translation_memory_data = translation_memory.load_translation_memory()
        tm_dirty = False

    def _add_item(custom_id: str, raw_text: str) -> None:
        clean = normalize_for_translation(raw_text)
        if not clean:
            return
        if not re.search(r"[\u4e00-\u9fff\u3040-\u309F\u30A0-\u30FF]", clean):
    
            return
        # print(f"ID: {custom_id} | context: {clean}")
        clean = glossary.apply_glossary(clean, glossary_entries)
        if not clean:
            return
        key = clean
        if key in translation_memory_data:
            entry = translation_memory_data[key]
            prefilled[custom_id] = str(entry.get("text") or "")
            entry["last_used"] = time.time()
            tm_dirty = True
            return
        if key in seen:
            alias_map[custom_id] = seen[key]
            return
        seen[key] = custom_id
        key_map[custom_id] = key
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
        table_bboxes = ocr.collect_table_bboxes(pp_page)

        merged_cells = ocr.iter_merged_cells(pp_page)
        skip_table_lines = bool(merged_cells)
        has_paragraph_flags = ocr.has_paragraph_translate_flags(pp_page)
        paragraph_blocks = ocr.iter_paragraph_blocks(pp_page)
        for block in paragraph_blocks:
            if not block.get("should_translate"):
                continue
            block_idx = int(block.get("block_index", 0))
            custom_id = f"p{page_idx:04d}-b{block_idx:04d}"
            _add_item(custom_id, block.get("text", ""))

        for cell_idx, cell in enumerate(merged_cells):
            if not cell.get("should_translate"):
                continue
            custom_id = f"p{page_idx:04d}-c{cell_idx:04d}"
            _add_item(custom_id, cell.get("merged_text", ""))

        texts = page.get("rec_texts", []) or []
        rec_polys = page.get("rec_polys", []) or []
        for idx, text in enumerate(texts):
            if has_paragraph_flags:
                continue
            if skip_table_lines and table_bboxes and idx < len(rec_polys):
                bbox = poly_to_bbox(rec_polys[idx])
                if bbox:
                    cx = float(bbox["x"]) + float(bbox["w"]) * 0.5
                    cy = float(bbox["y"]) + float(bbox["h"]) * 0.5
                    if any(
                        tb[0] <= cx <= tb[2] and tb[1] <= cy <= tb[3]
                        for tb in table_bboxes
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
) -> dict[str, Any]:
    pages_payload: list[dict[str, Any]] = []
    pp_pages = pp_pages or {}
    
    for page in ocr_pages:
        page_idx = int(page.get("page_index_0based", 0))
        pp_page = pp_pages.get(page_idx)
        table_bboxes = ocr.collect_table_bboxes(pp_page)
        merged_cells = ocr.iter_merged_cells(pp_page)
        skip_table_lines = bool(merged_cells)
        has_paragraph_flags = ocr.has_paragraph_translate_flags(pp_page)
        rec_polys = page.get("rec_polys", []) or []
        
        boxes: list[dict[str, Any]] = []
        

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
            if has_paragraph_flags:
                continue
            if skip_table_lines and table_bboxes:
                cx = float(bbox["x"]) + float(bbox["w"]) * 0.5
                cy = float(bbox["y"]) + float(bbox["h"]) * 0.5
                if any(
                    tb[0] <= cx <= tb[2] and tb[1] <= cy <= tb[3]
                    for tb in table_bboxes
                ):
                    continue
            boxes.append({"id": idx, "bbox": bbox, "text": text, "deleted": False})

        paragraph_blocks = ocr.iter_paragraph_blocks(pp_page)
        if paragraph_blocks:
            base_id = 200000
            for block in paragraph_blocks:
                if not block.get("should_translate"):
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
                    }
                )

        if merged_cells:
            base_id = 100000
            for cell_idx, cell in enumerate(merged_cells):
                if not cell.get("should_translate"):
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
                    {"id": base_id + cell_idx, "bbox": bbox, "text": cell_text, "deleted": False}
                )

        pages_payload.append({"page_index_0based": page_idx, "boxes": boxes})

    return {"pages": pages_payload}


def run_batch_translate_job(
    job_id: str, job_dir: Path, config: dict[str, Any] | None = None
) -> None:
    config = config or jobs.load_batch_config(job_dir) or {}
    target_lang = str(config.get("target_lang") or "en")
    model_name = str(config.get("model") or state.AZURE_BATCH_MODEL)
    system_prompt = resolve_batch_prompt(target_lang, config.get("system_prompt"))
    jobs.update_job_meta(job_dir, translate_started_at=time.time(), translate_completed_at=None)
    status_meta = {
        "job_id": job_id,
        "started_at": time.time(),
        "model": model_name,
        "target_lang": target_lang,
    }
    logger.info(
        "Batch translate start job_id=%s target_lang=%s model=%s",
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
        )
        jobs.write_batch_alias_map(job_dir, alias_map)
        jobs.write_batch_prefill_map(job_dir, prefilled)
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
            translations = build_translations_from_jsonl_text(
                "", alias_map=alias_map, prefilled=prefilled
            )
            edits_payload = build_edits_payload_from_translations(
                ocr_pages, translations, pp_pages=pp_pages
            )
            edits_path = job_dir / "edits.json"
            edits_path.write_text(
                json.dumps(edits_payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            logger.info(
                "Batch translate skipped remote call; wrote edits.json=%s",
                edits_path.resolve(),
            )
            ocr.apply_edits_to_pdf(job_id, job_dir, edits_payload)
            logger.info("Batch translate wrote edited.pdf job_id=%s", job_id)
            jobs.write_batch_status(
                job_dir, "completed", **status_meta, batch_id="prefill_only"
            )
            jobs.update_job_meta(
                job_dir, processing_completed_at=time.time(), translate_completed_at=time.time()
            )
            logger.info(
                "Batch translate completed from translation memory job_id=%s", job_id
            )
            return

        batch_input_path = job_dir / state.BATCH_INPUT_NAME
        write_jsonl(batch_input_path, batch_items)
        logger.info(
            "Batch translate wrote input jsonl=%s", batch_input_path.resolve()
        )

        client = get_azure_client()
        file_obj = client.files.create(
            file=open(batch_input_path, "rb"),
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
        logger.info("Batch translate created batch_id=%s", batch_id)
        jobs.write_batch_status(job_dir, "running", **status_meta, batch_id=batch_id)

        status = batch_obj.status
        while status not in ("completed", "failed", "canceled", "cancelled"):
            time.sleep(state.AZURE_BATCH_POLL_SECONDS)
            batch_obj = client.batches.retrieve(batch_id)
            status = batch_obj.status
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

        if status != "completed":
            raise RuntimeError(f"Batch status = {status}")

        output_file_id = batch_obj.output_file_id or batch_obj.error_file_id
        if not output_file_id:
            raise RuntimeError("Batch has no output_file_id/error_file_id.")

        file_response = client.files.content(output_file_id)
        raw_text = file_response.text or ""
        (job_dir / state.BATCH_OUTPUT_NAME).write_text(raw_text, encoding="utf-8")
        logger.info("Batch translate downloaded output file_id=%s", output_file_id)

        translations = build_translations_from_jsonl_text(
            raw_text, alias_map=alias_map, prefilled=prefilled
        )
        if key_map:
            with state.TRANSLATION_MEMORY_LOCK:
                memory = translation_memory.load_translation_memory()
                now_ts = time.time()
                for custom_id, key in key_map.items():
                    translated = translations.get(custom_id)
                    if translated:
                        memory[key] = {"text": translated, "last_used": now_ts}
                translation_memory.write_translation_memory(memory)
        edits_payload = build_edits_payload_from_translations(
            ocr_pages, translations, pp_pages=pp_pages
        )
        edits_path = job_dir / "edits.json"
        edits_path.write_text(
            json.dumps(edits_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        logger.info("Batch translate wrote edits.json=%s", edits_path.resolve())
        ocr.apply_edits_to_pdf(job_id, job_dir, edits_payload)
        logger.info("Batch translate wrote edited.pdf job_id=%s", job_id)
        jobs.write_batch_status(job_dir, "completed", **status_meta, batch_id=batch_id)
        jobs.update_job_meta(
            job_dir, processing_completed_at=time.time(), translate_completed_at=time.time()
        )
        logger.info("Batch translate completed job_id=%s", job_id)
    except Exception as exc:
        logger.exception("Batch translate failed job_id=%s error=%s", job_id, exc)
        jobs.write_batch_status(job_dir, "failed", **status_meta, error=str(exc))
        jobs.update_job_meta(
            job_dir, processing_completed_at=time.time(), translate_completed_at=time.time()
        )
