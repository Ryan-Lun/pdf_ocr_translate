from __future__ import annotations

import asyncio
import json
import logging
import random
import re
import threading
import time
from pathlib import Path
from typing import Any

from . import batch, jobs, openai_config, rate_limiter, state

logger = logging.getLogger(__name__)

_GLOBAL_SEMAPHORE = threading.BoundedSemaphore(state.PDF_REALTIME_GLOBAL_CONCURRENCY)
_NUMBERED_ITEM_RE = re.compile(r"(?<!\d)(\d+)\.(?=\s)")
_REALTIME_DELIMITER_RE = re.compile(r"^<<<([^>\r\n]+)>>>\s*$", re.MULTILINE)
_REALTIME_CUSTOM_ID_RE = re.compile(r"^p(\d+)-([lbc])(\d+)$")


def _unwrap_code_fences(text: str) -> str:
    cleaned = str(text or "").strip()
    match = re.match(r"^```(?:text|markdown)?\s*(.*?)\s*```$", cleaned, re.DOTALL | re.IGNORECASE)
    return match.group(1).strip() if match else cleaned


def _realtime_debug_dir(job_dir: Path) -> Path:
    return job_dir / "realtime_debug" / "chunks"


def _output_realtime_debug_dir(job_dir: Path) -> Path:
    return job_dir / "output" / "realtime_debug" / "chunks"


def _realtime_debug_roots(job_dir: Path) -> tuple[Path, ...]:
    return (_realtime_debug_dir(job_dir), _output_realtime_debug_dir(job_dir))


def _write_debug_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(content or ""), encoding="utf-8")


def _write_debug_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _chunk_debug_path(job_dir: Path, chunk_label: str) -> Path:
    return _realtime_debug_dir(job_dir) / chunk_label


def _chunk_debug_paths(job_dir: Path, chunk_label: str) -> tuple[Path, ...]:
    return tuple(root / chunk_label for root in _realtime_debug_roots(job_dir))


def _record_chunk_request(
    *,
    job_dir: Path,
    chunk_label: str,
    mode: str,
    system_prompt: str,
    payload: str,
    expected_ids: list[str],
) -> None:
    for chunk_dir in _chunk_debug_paths(job_dir, chunk_label):
        _write_debug_json(
            chunk_dir / "request_meta.json",
            {
                "mode": mode,
                "expected_ids": expected_ids,
            },
        )
        _write_debug_text(chunk_dir / "system_prompt.txt", system_prompt)
        _write_debug_text(chunk_dir / "payload.txt", payload)


def _record_chunk_response(
    *,
    job_dir: Path,
    chunk_label: str,
    attempt: int,
    content: str,
) -> None:
    for chunk_dir in _chunk_debug_paths(job_dir, chunk_label):
        _write_debug_text(
            chunk_dir / f"response_attempt_{attempt}.txt",
            content,
        )


def _record_chunk_error(
    *,
    job_dir: Path,
    chunk_label: str,
    attempt: int,
    error: str,
) -> None:
    for chunk_dir in _chunk_debug_paths(job_dir, chunk_label):
        _write_debug_text(
            chunk_dir / f"error_attempt_{attempt}.txt",
            error,
        )


def _record_chunk_parsed(
    *,
    job_dir: Path,
    chunk_label: str,
    translations: dict[str, str],
) -> None:
    for chunk_dir in _chunk_debug_paths(job_dir, chunk_label):
        _write_debug_json(
            chunk_dir / "parsed_translations.json",
            translations,
        )


def _record_chunk_plan(job_dir: Path, chunks: list[list[dict[str, Any]]]) -> None:
    payload: list[dict[str, Any]] = []
    for idx, chunk in enumerate(chunks, start=1):
        ids: list[str] = []
        chars = 0
        for item in chunk:
            custom_id, _, user_text = _extract_batch_item_payload(item)
            ids.append(custom_id)
            chars += len(user_text)
        payload.append(
            {
                "chunk_label": f"chunk_{idx:04d}",
                "size": len(chunk),
                "chars": chars,
                "ids": ids,
            }
        )
    _write_debug_json(job_dir / "realtime_debug" / "chunk_plan.json", payload)
    _write_debug_json(job_dir / "output" / "realtime_debug" / "chunk_plan.json", payload)


def _normalize_numbered_item_breaks(text: str) -> str:
    if not text:
        return ""

    normalized_lines: list[str] = []
    for raw_line in str(text).splitlines():
        matches = list(_NUMBERED_ITEM_RE.finditer(raw_line))
        if not matches:
            normalized_lines.append(raw_line)
            continue

        prefix = raw_line[: matches[0].start()].rstrip()
        split_from_first = bool(prefix) and prefix.endswith((":", "："))
        split_matches = matches if split_from_first else matches[1:]
        if not split_matches:
            normalized_lines.append(raw_line)
            continue

        segments: list[str] = []
        last = 0
        for match in split_matches:
            segment = raw_line[last:match.start()].rstrip()
            if segment:
                segments.append(segment)
            last = match.start()
        tail = raw_line[last:].strip()
        if tail:
            segments.append(tail)
        normalized_lines.extend(segments or [raw_line])

    return "\n".join(normalized_lines)


def _normalize_realtime_translation(text: str) -> str:
    normalized = batch.normalize_text(str(text or ""))
    normalized = batch.glossary.restore_protected_glossary_terms(normalized)
    return _normalize_numbered_item_breaks(normalized)


def _extract_batch_item_payload(item: dict[str, Any]) -> tuple[str, str, str]:
    custom_id = str(item.get("custom_id") or "").strip()
    body = item.get("body") or {}
    messages = body.get("messages") or []
    if len(messages) < 2:
        raise RuntimeError(f"Invalid realtime batch item payload for {custom_id or 'unknown item'}.")
    system_prompt = str(messages[0].get("content") or "")
    user_text = str(messages[1].get("content") or "")
    if not custom_id or not system_prompt or not user_text:
        raise RuntimeError(f"Incomplete realtime batch item payload for {custom_id or 'unknown item'}.")
    return custom_id, system_prompt, user_text


def _parse_realtime_custom_id(custom_id: str) -> tuple[int, str, int] | None:
    match = _REALTIME_CUSTOM_ID_RE.match(str(custom_id or "").strip())
    if not match:
        return None
    return int(match.group(1)), str(match.group(2)), int(match.group(3))


def _editor_box_id_from_custom_id(custom_id: str) -> int | None:
    parsed = _parse_realtime_custom_id(custom_id)
    if not parsed:
        return None
    _, kind, index = parsed
    if kind == "l":
        return index
    if kind == "c":
        return 100000 + index
    if kind == "b":
        return 200000 + index
    return None


def _extract_chunk_segments(output: str) -> tuple[str, list[tuple[str, str]]]:
    cleaned = _unwrap_code_fences(output)
    matches = list(_REALTIME_DELIMITER_RE.finditer(cleaned))
    segments: list[tuple[str, str]] = []
    for idx, match in enumerate(matches):
        custom_id = str(match.group(1) or "").strip()
        start = match.end()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(cleaned)
        text = _normalize_realtime_translation(cleaned[start:end].strip())
        segments.append((custom_id, text))
    return cleaned, segments


def _extract_merge_notice_candidates(output: str, items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    _, segments = _extract_chunk_segments(output)
    if not segments or not items:
        return []

    expected_ids = [_extract_batch_item_payload(item)[0] for item in items]
    found_ids = [custom_id for custom_id, _ in segments]
    if len(found_ids) >= len(expected_ids):
        return []

    item_meta: dict[str, dict[str, Any]] = {}
    for item in items:
        custom_id, _, user_text = _extract_batch_item_payload(item)
        parsed = _parse_realtime_custom_id(custom_id)
        if not parsed:
            continue
        page_idx, kind, _ = parsed
        item_meta[custom_id] = {
            "page_index_0based": page_idx,
            "kind": kind,
            "source_text": batch.glossary.restore_protected_glossary_terms(
                batch.normalize_text(user_text)
            ),
            "editor_box_id": _editor_box_id_from_custom_id(custom_id),
        }

    segment_map = {custom_id: text for custom_id, text in segments if custom_id}
    candidates: list[dict[str, Any]] = []
    missing_ids = [custom_id for custom_id in expected_ids if custom_id not in found_ids]
    for missing_id in missing_ids:
        current_index = expected_ids.index(missing_id)
        if current_index <= 0:
            continue
        previous_id = expected_ids[current_index - 1]
        previous_text = segment_map.get(previous_id)
        previous_meta = item_meta.get(previous_id)
        missing_meta = item_meta.get(missing_id)
        if not previous_text or not previous_meta or not missing_meta:
            continue
        candidates.append(
            {
                "notice_id": f"{previous_id}__{missing_id}",
                "status": "pending",
                "primary_custom_id": previous_id,
                "secondary_custom_id": missing_id,
                "primary_page_index_0based": previous_meta["page_index_0based"],
                "secondary_page_index_0based": missing_meta["page_index_0based"],
                "primary_box_id": previous_meta["editor_box_id"],
                "secondary_box_id": missing_meta["editor_box_id"],
                "primary_kind": previous_meta["kind"],
                "secondary_kind": missing_meta["kind"],
                "source_text": "\n".join(
                    text
                    for text in [
                        str(previous_meta.get("source_text") or "").strip(),
                        str(missing_meta.get("source_text") or "").strip(),
                    ]
                    if text
                ),
                "suggested_translation": previous_text,
            }
        )
    return candidates


def _record_merge_notice_candidates(
    *,
    job_dir: Path,
    chunk_label: str,
    items: list[dict[str, Any]],
    output: str,
    error: str,
) -> None:
    for notice in _extract_merge_notice_candidates(output, items):
        jobs.upsert_merge_notice(
            job_dir,
            {
                **notice,
                "chunk_label": chunk_label,
                "error": str(error or ""),
            },
        )


def _build_chunk_prompt(*, system_prompt: str) -> str:
    return "\n\n".join(
        [
            system_prompt,
            "\n".join(
                [
                    "You will receive multiple translation items.",
                    "Each item starts with a delimiter line exactly in the form <<<ID>>>.",
                    "Translate the text under each delimiter.",
                    "Return the translations using the exact same delimiters, ids, and order.",
                    "Do not omit, rename, or add delimiters.",
                    "Output only the translated items.",
                ]
            ),
        ]
    ).strip()


def _chunk_batch_items(
    items: list[dict[str, Any]],
    *,
    max_segments: int,
    max_chars: int,
) -> list[list[dict[str, Any]]]:
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    current_chars = 0
    for item in items:
        _, _, user_text = _extract_batch_item_payload(item)
        item_chars = len(user_text)
        if current and (len(current) >= max_segments or current_chars + item_chars > max_chars):
            chunks.append(current)
            current = []
            current_chars = 0
        current.append(item)
        current_chars += item_chars
    if current:
        chunks.append(current)
    return chunks


def _serialize_translation_chunk(items: list[dict[str, Any]]) -> str:
    parts: list[str] = []
    for item in items:
        custom_id, _, user_text = _extract_batch_item_payload(item)
        parts.append(f"<<<{custom_id}>>>\n{user_text}")
    return "\n\n".join(parts)


def _parse_translation_chunk_output(output: str, expected_ids: list[str]) -> dict[str, str]:
    _, segments = _extract_chunk_segments(output)
    if len(segments) != len(expected_ids):
        raise RuntimeError(
            f"Expected {len(expected_ids)} delimiters but received {len(segments)}."
        )

    found_ids: list[str] = []
    translations: dict[str, str] = {}
    for custom_id, text in segments:
        found_ids.append(custom_id)
        if not text:
            raise RuntimeError(f"Empty translation for {custom_id}.")
        translations[custom_id] = text

    if found_ids != expected_ids:
        raise RuntimeError(f"Delimiter order mismatch. expected={expected_ids} actual={found_ids}")
    return translations


def _prepare_realtime_plan(
    job_dir,
    config: dict[str, Any],
) -> dict[str, Any]:
    document_mode = batch.resolve_document_mode(
        config.get("document_mode") or (jobs.load_job_meta(job_dir) or {}).get("document_mode")
    )
    source_lang = str(config.get("source_lang") or "auto")
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
        source_lang=source_lang,
        document_mode=document_mode,
    )
    jobs.write_batch_alias_map(job_dir, alias_map)
    jobs.write_batch_prefill_map(job_dir, prefilled)
    batch._write_batch_key_map(job_dir, key_map)
    return {
        "document_mode": document_mode,
        "source_lang": source_lang,
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


async def _translate_item(
    client,
    *,
    job_dir: Path,
    chunk_label: str,
    item: dict[str, Any],
    model_name: str,
    request_delay: float,
    max_retries: int = 4,
) -> tuple[str, str]:
    custom_id, system_prompt, user_text = _extract_batch_item_payload(item)
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_text},
    ]
    _record_chunk_request(
        job_dir=job_dir,
        chunk_label=chunk_label,
        mode="single",
        system_prompt=system_prompt,
        payload=user_text,
        expected_ids=[custom_id],
    )
    estimated_tokens = rate_limiter.estimate_messages_tokens(messages) + state.REALTIME_COMPLETION_TOKEN_BUDGET
    for attempt in range(max_retries):
        try:
            await rate_limiter.REALTIME_RATE_LIMITER.acquire_async(model_name, estimated_tokens)
            await asyncio.to_thread(_GLOBAL_SEMAPHORE.acquire)
            try:
                response = await client.chat.completions.with_raw_response.create(
                    model=model_name,
                    messages=messages,
                    temperature=0,
                    max_tokens=4000,
                )
            finally:
                _GLOBAL_SEMAPHORE.release()
            rate_limiter.REALTIME_RATE_LIMITER.update_from_headers(model_name, response.headers)
            await asyncio.sleep(request_delay)
            parsed = response.parse()
            raw_content = str(parsed.choices[0].message.content or "").strip()
            _record_chunk_response(
                job_dir=job_dir,
                chunk_label=chunk_label,
                attempt=attempt + 1,
                content=raw_content,
            )
            content = _normalize_realtime_translation(raw_content)
            if content:
                _record_chunk_parsed(
                    job_dir=job_dir,
                    chunk_label=chunk_label,
                    translations={custom_id: content},
                )
                return custom_id, content
            raise RuntimeError("Empty realtime translation response.")
        except Exception as exc:
            _record_chunk_error(
                job_dir=job_dir,
                chunk_label=chunk_label,
                attempt=attempt + 1,
                error=str(exc),
            )
            if attempt == max_retries - 1:
                raise RuntimeError(f"Realtime item translation failed for {custom_id}: {exc}") from exc
            await asyncio.sleep((2**attempt) + random.uniform(0, 0.5))
    return custom_id, ""


async def _translate_chunk(
    client,
    *,
    job_dir: Path,
    chunk_label: str,
    items: list[dict[str, Any]],
    model_name: str,
    request_delay: float,
    max_retries: int = 4,
) -> dict[str, str]:
    if not items:
        return {}
    first_id, system_prompt, _ = _extract_batch_item_payload(items[0])
    expected_ids = [_extract_batch_item_payload(item)[0] for item in items]
    prompt = _build_chunk_prompt(system_prompt=system_prompt)
    payload = _serialize_translation_chunk(items)
    _record_chunk_request(
        job_dir=job_dir,
        chunk_label=chunk_label,
        mode="chunk",
        system_prompt=prompt,
        payload=payload,
        expected_ids=expected_ids,
    )
    estimated_tokens = rate_limiter.estimate_text_tokens(prompt) + rate_limiter.estimate_text_tokens(payload) + state.REALTIME_COMPLETION_TOKEN_BUDGET

    last_content = ""
    for attempt in range(max_retries):
        try:
            await rate_limiter.REALTIME_RATE_LIMITER.acquire_async(model_name, estimated_tokens)
            await asyncio.to_thread(_GLOBAL_SEMAPHORE.acquire)
            try:
                response = await client.chat.completions.with_raw_response.create(
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
            rate_limiter.REALTIME_RATE_LIMITER.update_from_headers(model_name, response.headers)
            await asyncio.sleep(request_delay)
            parsed = response.parse()
            content = str(parsed.choices[0].message.content or "").strip()
            last_content = content
            _record_chunk_response(
                job_dir=job_dir,
                chunk_label=chunk_label,
                attempt=attempt + 1,
                content=content,
            )
            translations = _parse_translation_chunk_output(content, expected_ids)
            if translations:
                _record_chunk_parsed(
                    job_dir=job_dir,
                    chunk_label=chunk_label,
                    translations=translations,
                )
                return translations
            raise RuntimeError("Empty realtime chunk translation response.")
        except Exception as exc:
            _record_chunk_error(
                job_dir=job_dir,
                chunk_label=chunk_label,
                attempt=attempt + 1,
                error=str(exc),
            )
            if attempt == max_retries - 1:
                if last_content:
                    _record_merge_notice_candidates(
                        job_dir=job_dir,
                        chunk_label=chunk_label,
                        items=items,
                        output=last_content,
                        error=str(exc),
                    )
                raise RuntimeError(f"Realtime chunk translation failed for {first_id}: {exc}") from exc
            await asyncio.sleep((2**attempt) + random.uniform(0, 0.5))
    return {}


async def _translate_chunk_with_fallback(
    client,
    *,
    job_dir: Path,
    chunk_label: str,
    items: list[dict[str, Any]],
    model_name: str,
    request_delay: float,
) -> dict[str, str]:
    if not items:
        return {}
    if len(items) == 1:
        custom_id, text = await _translate_item(
            client,
            job_dir=job_dir,
            chunk_label=f"{chunk_label}__single",
            item=items[0],
            model_name=model_name,
            request_delay=request_delay,
        )
        return {custom_id: text} if custom_id and text else {}
    try:
        return await _translate_chunk(
            client,
            job_dir=job_dir,
            chunk_label=chunk_label,
            items=items,
            model_name=model_name,
            request_delay=request_delay,
        )
    except Exception:
        mid = max(1, len(items) // 2)
        left = await _translate_chunk_with_fallback(
            client,
            job_dir=job_dir,
            chunk_label=f"{chunk_label}__a",
            items=items[:mid],
            model_name=model_name,
            request_delay=request_delay,
        )
        right = await _translate_chunk_with_fallback(
            client,
            job_dir=job_dir,
            chunk_label=f"{chunk_label}__b",
            items=items[mid:],
            model_name=model_name,
            request_delay=request_delay,
        )
        merged = dict(left)
        merged.update(right)
        return merged


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
    jobs.write_merge_notices(job_dir, [])
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
                source_lang=plan["source_lang"],
                key_map=plan["key_map"],
                translations=translations,
                status_meta=status_meta,
                backend_id="realtime_prefill_only",
            )
            return True

        chunks = _chunk_batch_items(
            batch_items,
            max_segments=state.PDF_REALTIME_MAX_SEGMENTS_PER_REQUEST,
            max_chars=state.PDF_REALTIME_MAX_CHARS_PER_REQUEST,
        )
        _record_chunk_plan(job_dir, chunks)
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
            translations = batch.build_translations_from_jsonl_text("", prefilled=plan["prefilled"])

            async def _task(index: int, realtime_items: list[dict[str, Any]]) -> tuple[int, dict[str, str]]:
                async with semaphore:
                    chunk_translations = await _translate_chunk_with_fallback(
                        client,
                        job_dir=job_dir,
                        chunk_label=f"chunk_{index:04d}",
                        items=realtime_items,
                        model_name=plan["model_name"],
                        request_delay=request_delay,
                    )
                    return index, chunk_translations

            tasks = [_task(index, chunk) for index, chunk in enumerate(chunks, start=1)]
            completed = 0
            for coro in asyncio.as_completed(tasks):
                _, chunk_translations = await coro
                translations.update(chunk_translations)
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
            source_lang=plan["source_lang"],
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
