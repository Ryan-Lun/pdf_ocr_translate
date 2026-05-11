from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import threading
import time
from typing import Any

from . import batch, jobs, openai_config, state

logger = logging.getLogger(__name__)

_GLOBAL_SEMAPHORE = threading.BoundedSemaphore(state.PDF_REALTIME_GLOBAL_CONCURRENCY)
_NUMBERED_ITEM_RE = re.compile(r"(?<!\d)(\d+)\.(?=\s)")


def _unwrap_json_code_fences(text: str) -> str:
    cleaned = str(text or "").strip()
    match = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else cleaned


def _build_chunk_prompt(
    *,
    target_lang: str,
    system_prompt: str,
) -> str:
    prompt_parts = [batch.resolve_batch_prompt(target_lang, system_prompt)]
    prompt_parts.append(
        "\n".join(
            [
                "You will receive a JSON array of translation items.",
                "Translate each item's text field and return valid JSON only.",
                # "For each text value, preserve the batch formatting rules exactly.",
                # "If a translated text contains multiple numbered items such as '1.' '2.' '3.', insert a line break strictly before the second and later numbered items.",
                # "Do not add line breaks inside the same numbered item.",
                "CRITICAL FORMATTING RULE 1: You MUST insert a line break strictly before every numbered item (e.g., '2.', '3.', '4.').",
                "CRITICAL FORMATTING RULE 2: You MUST keep all text within the same numbered item as ONE continuous paragraph. Do NOT add line breaks inside a step.",
                'Return the shape: {"translations":[{"id":"...", "text":"..."}]}.',
                "Do not omit ids. Do not add explanations.",
            ]
        )
    )
    return "\n\n".join(part for part in prompt_parts if part).strip()


def _normalize_numbered_item_breaks(text: str) -> str:
    if not text:
        return ""

    normalized_lines: list[str] = []
    for raw_line in str(text).splitlines():
        matches = list(_NUMBERED_ITEM_RE.finditer(raw_line))
        if len(matches) <= 1:
            normalized_lines.append(raw_line)
            continue

        segments: list[str] = []
        last = 0
        for match in matches[1:]:
            segment = raw_line[last:match.start()].rstrip()
            if segment:
                segments.append(segment)
            last = match.start()
        tail = raw_line[last:].strip()
        if tail:
            segments.append(tail)
        normalized_lines.extend(segments or [raw_line])

    return "\n".join(normalized_lines)


def _chunk_translation_items(
    items: list[dict[str, str]],
    *,
    max_segments: int,
    max_chars: int,
) -> list[list[dict[str, str]]]:
    chunks: list[list[dict[str, str]]] = []
    current: list[dict[str, str]] = []
    current_chars = 0
    for item in items:
        text = str(item.get("text") or "")
        item_chars = len(text)
        if current and (len(current) >= max_segments or current_chars + item_chars > max_chars):
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_chars
    if current:
        chunks.append(current)
    return chunks


def _prepare_realtime_plan(
    job_dir,
    config: dict[str, Any],
) -> dict[str, Any]:
    document_mode = batch.resolve_document_mode(
        config.get("document_mode") or (jobs.load_job_meta(job_dir) or {}).get("document_mode")
    )
    target_lang = str(config.get("target_lang") or "en")
    model_name = str(config.get("model") or state.PDF_REALTIME_TRANSLATE_MODEL)
    system_prompt = batch.resolve_batch_prompt(target_lang, config.get("system_prompt"))
    ocr_pages = batch.ocr.load_ocr_pages(job_dir)
    pp_pages = batch.ocr.load_pp_pages(job_dir)
    glossary_entries = batch.glossary.load_combined_glossary()
    batch_items, alias_map, key_map, prefilled = batch.build_batch_items(
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
    batch._write_batch_key_map(job_dir, key_map)
    return {
        "document_mode": document_mode,
        "target_lang": target_lang,
        "model_name": model_name,
        "system_prompt": system_prompt,
        "ocr_pages": ocr_pages,
        "pp_pages": pp_pages,
        "glossary_entries": glossary_entries,
        "batch_items": batch_items,
        "alias_map": alias_map,
        "key_map": key_map,
        "prefilled": prefilled,
    }


async def _translate_chunk(
    client,
    *,
    chunk: list[dict[str, str]],
    model_name: str,
    prompt: str,
    request_delay: float,
    max_retries: int = 4,
) -> dict[str, str]:
    payload = json.dumps(chunk, ensure_ascii=False)
    for attempt in range(max_retries):
        try:
            await asyncio.to_thread(_GLOBAL_SEMAPHORE.acquire)
            try:
                response = await client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": prompt},
                        {"role": "user", "content": payload},
                    ],
                    temperature=0,
                    max_tokens=4000,
                )
            finally:
                _GLOBAL_SEMAPHORE.release()
            await asyncio.sleep(request_delay)
            content = str(response.choices[0].message.content or "").strip()
            data = json.loads(_unwrap_json_code_fences(content))
            rows = data.get("translations", []) if isinstance(data, dict) else []
            results: dict[str, str] = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                custom_id = str(row.get("id") or "").strip()
                text = batch.normalize_text(str(row.get("text") or ""))
                text = batch.glossary.restore_protected_glossary_terms(text)
                text = _normalize_numbered_item_breaks(text)
                if custom_id and text:
                    results[custom_id] = text
            if results:
                return results
            raise RuntimeError("Empty realtime translation response.")
        except Exception as exc:
            if attempt == max_retries - 1:
                raise RuntimeError(f"Realtime chunk translation failed: {exc}") from exc
            await asyncio.sleep((2**attempt) + random.uniform(0, 0.5))
    return {}


def run_realtime_translate_job(
    job_id: str,
    job_dir,
    config: dict[str, Any] | None = None,
) -> bool:
    config = config or jobs.load_batch_config(job_dir) or {}
    config = {
        **config,
        "translate_mode": jobs.normalize_translate_mode(
            config.get("translate_mode") or (jobs.load_job_meta(job_dir) or {}).get("translate_mode")
        ),
    }
    target_lang = str(config.get("target_lang") or "en")
    model_name = str(config.get("model") or state.PDF_REALTIME_TRANSLATE_MODEL)
    existing_status = jobs.load_batch_status(job_dir) or {}
    status_meta = batch._build_batch_status_meta(job_id, target_lang, model_name, existing_status)
    status_meta["translate_mode"] = "realtime"

    jobs.set_job_state(
        job_dir,
        status="running",
        stage="translate",
        extra_meta={"translate_started_at": time.time()},
    )
    jobs.write_batch_status(job_dir, "running", **status_meta, completed_chunks=0, total_chunks=0)

    try:
        plan = _prepare_realtime_plan(job_dir, config)
        batch_items = plan["batch_items"]
        prefilled = plan["prefilled"]
        if not batch_items and not prefilled:
            raise RuntimeError("No OCR text lines found to translate.")
        if not batch_items and prefilled:
            translations = batch.build_translations_from_jsonl_text("", prefilled=prefilled)
            batch.finalize_translation_job(
                job_id=job_id,
                job_dir=job_dir,
                ocr_pages=plan["ocr_pages"],
                pp_pages=plan["pp_pages"],
                document_mode=plan["document_mode"],
                target_lang=plan["target_lang"],
                key_map=plan["key_map"],
                translations=translations,
                status_meta=status_meta,
                backend_id="realtime_prefill_only",
            )
            return True

        chunk_items = [
            {
                "id": str(item.get("custom_id") or ""),
                "text": str((((item.get("body") or {}).get("messages") or [{}, {}])[1]).get("content") or ""),
            }
            for item in batch_items
        ]
        chunks = _chunk_translation_items(
            chunk_items,
            max_segments=state.PDF_REALTIME_MAX_SEGMENTS_PER_REQUEST,
            max_chars=state.PDF_REALTIME_MAX_CHARS_PER_REQUEST,
        )
        jobs.write_batch_status(
            job_dir,
            "running",
            **status_meta,
            completed_chunks=0,
            total_chunks=len(chunks),
        )

        async def _runner() -> dict[str, str]:
            client = openai_config.create_async_client()
            semaphore = asyncio.Semaphore(state.PDF_REALTIME_JOB_CONCURRENCY)
            request_delay = 60.0 / max(1, state.PDF_REALTIME_RPM_LIMIT)
            prompt = _build_chunk_prompt(
                target_lang=plan["target_lang"],
                system_prompt=plan["system_prompt"],
            )
            translations = batch.build_translations_from_jsonl_text("", prefilled=plan["prefilled"])

            async def _task(index: int, chunk: list[dict[str, str]]) -> tuple[int, dict[str, str]]:
                async with semaphore:
                    result = await _translate_chunk(
                        client,
                        chunk=chunk,
                        model_name=plan["model_name"],
                        prompt=prompt,
                        request_delay=request_delay,
                    )
                    return index, result

            tasks = [_task(index, chunk) for index, chunk in enumerate(chunks, start=1)]
            completed = 0
            for coro in asyncio.as_completed(tasks):
                _, chunk_result = await coro
                translations.update(chunk_result)
                completed += 1
                progress = round((completed / max(1, len(chunks))) * 100.0, 2)
                jobs.write_batch_status(
                    job_dir,
                    "running",
                    **status_meta,
                    completed_chunks=completed,
                    total_chunks=len(chunks),
                    progress=progress,
                )
                jobs.set_job_state(job_dir, status="running", stage="translate", progress=progress)
            return batch.apply_alias_map_to_translations(translations, plan["alias_map"])

        translations = asyncio.run(_runner())
        batch.finalize_translation_job(
            job_id=job_id,
            job_dir=job_dir,
            ocr_pages=plan["ocr_pages"],
            pp_pages=plan["pp_pages"],
            document_mode=plan["document_mode"],
            target_lang=plan["target_lang"],
            key_map=plan["key_map"],
            translations=translations,
            status_meta=status_meta,
            backend_id="realtime",
        )
        return True
    except Exception as exc:
        logger.exception("Realtime translate failed job_id=%s error=%s", job_id, exc)
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
