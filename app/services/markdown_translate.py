from __future__ import annotations

import json
import logging
import re
import subprocess
from copy import deepcopy
from html import escape
from pathlib import Path
from typing import Any

from lang_utils import (
    describe_target_language,
    traditional_chinese_instruction,
)

from . import glossary, openai_config, state, translation_debug

logger = logging.getLogger(__name__)


def _run_pandoc(text: str, from_format: str, to_format: str) -> str:
    completed = subprocess.run(
        ["pandoc", "-f", from_format, "-t", to_format],
        input=text,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "pandoc conversion failed")
    return completed.stdout


def text_to_doc(source_text: str, from_format: str) -> dict[str, Any]:
    return json.loads(_run_pandoc(source_text, from_format, "json"))


def doc_to_text(doc: dict[str, Any], to_format: str) -> str:
    payload = json.dumps(doc, ensure_ascii=False)
    return _run_pandoc(payload, "json", to_format)


def markdown_to_doc(markdown_text: str) -> dict[str, Any]:
    return text_to_doc(markdown_text, "markdown")


def doc_to_markdown(doc: dict[str, Any]) -> str:
    return doc_to_text(doc, "markdown")


def html_to_doc(html_text: str) -> dict[str, Any]:
    return text_to_doc(html_text, "html")


def doc_to_html(doc: dict[str, Any]) -> str:
    return doc_to_text(doc, "html")


def blocks_to_markdown(
    api_version: list[Any],
    meta: dict[str, Any],
    blocks: list[dict[str, Any]],
) -> str:
    doc = {"pandoc-api-version": api_version, "meta": meta, "blocks": blocks}
    return doc_to_markdown(doc).strip()


def markdown_to_blocks(markdown_text: str) -> list[dict[str, Any]]:
    return markdown_to_doc(markdown_text).get("blocks", []) or []


def _is_translatable_block(block: dict[str, Any]) -> bool:
    block_type = block.get("t")
    if block_type in {"CodeBlock", "RawBlock", "HorizontalRule"}:
        return False
    return not _block_contains_only_images(block)


def _inlines_contain_only_images(inlines: list[dict[str, Any]]) -> bool:
    has_image = False
    for inline in inlines:
        inline_type = inline.get("t")
        if inline_type == "Image":
            has_image = True
            continue
        if inline_type in {"Space", "SoftBreak", "LineBreak"}:
            continue
        return False
    return has_image


def _block_contains_only_images(block: dict[str, Any]) -> bool:
    block_type = block.get("t")
    content = block.get("c")
    if block_type in {"Plain", "Para"} and isinstance(content, list):
        return _inlines_contain_only_images(content)
    if block_type == "Div" and isinstance(content, list) and len(content) == 2:
        child_blocks = content[1]
        return (
            isinstance(child_blocks, list)
            and len(child_blocks) == 1
            and _block_contains_only_images(child_blocks[0])
        )
    return False


def _get_translation_client():
    return openai_config.create_sync_client(), state.DOC_TRANSLATE_MODEL


def _build_system_prompt(
    target_lang: str,
    glossary_entries: list[tuple[str, str]],
    *,
    source_lang: str = "auto",
) -> str:
    prompt = [
        state.DOC_TRANSLATE_SYSTEM_PROMPT,
    ]
    if str(source_lang or "").strip().lower() not in {"", "auto"}:
        prompt.append(f"Source language: {describe_target_language(source_lang)}.")
    prompt.extend(
        [
        f"Target language: {describe_target_language(target_lang)}.",
        ]
    )
    zh_rule = traditional_chinese_instruction(target_lang)
    if zh_rule:
        prompt.append(zh_rule)
    if glossary_entries:
        glossary_lines = "\n".join(
            f"- {src} => {dst}" for src, dst in glossary_entries[:50]
        )
        prompt.append(
            "If the input contains tokens in the form [[[GLOSSARY_TERM_0001::TERM]]], copy those tokens exactly unchanged and keep TERM verbatim."
        )
        prompt.append("Use the following glossary when applicable:")
        prompt.append(glossary_lines)
    return "\n".join(part for part in prompt if part).strip()


def _extract_message_text(response: Any) -> str:
    choices = getattr(response, "choices", None) or []
    if not choices:
        return ""
    message = getattr(choices[0], "message", None)
    content = getattr(message, "content", "")
    return str(content or "").strip()


def _translate_snippet(
    snippet: str,
    client: Any,
    model: str,
    system_prompt: str,
    glossary_entries: list[tuple[str, str]] | None = None,
    debug_job_dir: Path | None = None,
    debug_custom_id: str | None = None,
) -> str:
    if not snippet.strip():
        return snippet
    protected_snippet = glossary.apply_glossary_with_protection(snippet, glossary_entries)
    if debug_job_dir is not None and debug_custom_id:
        translation_debug.record_request(
            job_dir=debug_job_dir,
            chunk_label=debug_custom_id,
            mode="doc_workspace_markdown",
            system_prompt=system_prompt,
            payload=protected_snippet,
            expected_ids=[debug_custom_id],
        )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": protected_snippet},
            ],
        )
    except Exception as exc:
        if debug_job_dir is not None and debug_custom_id:
            translation_debug.record_error(
                job_dir=debug_job_dir,
                chunk_label=debug_custom_id,
                attempt=1,
                error=str(exc),
            )
        raise
    translated = _extract_message_text(response)
    if debug_job_dir is not None and debug_custom_id:
        translation_debug.record_response(
            job_dir=debug_job_dir,
            chunk_label=debug_custom_id,
            attempt=1,
            content=translated,
        )
    restored = glossary.restore_protected_glossary_terms(translated)
    if debug_job_dir is not None and debug_custom_id and restored:
        translation_debug.record_parsed(
            job_dir=debug_job_dir,
            chunk_label=debug_custom_id,
            translations={debug_custom_id: restored},
        )
    return restored or glossary.restore_protected_glossary_terms(snippet)


def _translate_text(
    text: str,
    client: Any,
    model: str,
    system_prompt: str,
    glossary_entries: list[tuple[str, str]] | None = None,
    debug_job_dir: Path | None = None,
    debug_custom_id: str | None = None,
) -> str:
    if not text.strip():
        return text
    protected_text = glossary.apply_glossary_with_protection(text, glossary_entries)
    payload = (
        "Translate the following source text from an HTML text node.\n"
        "Return only the translated text. Do not add tags or explanations.\n"
        f"{protected_text}"
    )
    if debug_job_dir is not None and debug_custom_id:
        translation_debug.record_request(
            job_dir=debug_job_dir,
            chunk_label=debug_custom_id,
            mode="doc_workspace_html",
            system_prompt=system_prompt,
            payload=payload,
            expected_ids=[debug_custom_id],
        )
    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": payload},
            ],
        )
    except Exception as exc:
        if debug_job_dir is not None and debug_custom_id:
            translation_debug.record_error(
                job_dir=debug_job_dir,
                chunk_label=debug_custom_id,
                attempt=1,
                error=str(exc),
            )
        raise
    translated = _extract_message_text(response)
    if debug_job_dir is not None and debug_custom_id:
        translation_debug.record_response(
            job_dir=debug_job_dir,
            chunk_label=debug_custom_id,
            attempt=1,
            content=translated,
        )
    restored = glossary.restore_protected_glossary_terms(translated)
    if debug_job_dir is not None and debug_custom_id and restored:
        translation_debug.record_parsed(
            job_dir=debug_job_dir,
            chunk_label=debug_custom_id,
            translations={debug_custom_id: restored},
        )
    return restored or glossary.restore_protected_glossary_terms(text)


def _translate_pandoc_doc(
    doc: dict[str, Any],
    *,
    source_lang: str = "auto",
    target_lang: str,
    snippet_to_text,
    text_to_blocks,
    debug_job_dir: Path | None = None,
) -> dict[str, Any]:
    api_version = doc.get("pandoc-api-version", [])
    blocks = doc.get("blocks", []) or []
    meta = deepcopy(doc.get("meta", {}) or {})

    client, model = _get_translation_client()
    glossary_entries = glossary.load_combined_glossary()
    system_prompt = _build_system_prompt(target_lang, glossary_entries, source_lang=source_lang)

    translated_blocks: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    pending_len = 0
    chunk_counter = 0

    def flush_pending() -> None:
        nonlocal pending, pending_len, chunk_counter
        if not pending:
            return
        chunk_counter += 1
        snippet = snippet_to_text(api_version, meta, pending)
        chunk_label = f"chunk_{chunk_counter:04d}"
        translated_snippet = _translate_snippet(
            snippet,
            client,
            model,
            system_prompt,
            glossary_entries=glossary_entries,
            debug_job_dir=debug_job_dir,
            debug_custom_id=chunk_label,
        )
        parsed_blocks = text_to_blocks(translated_snippet)
        translated_blocks.extend(parsed_blocks or pending)
        pending = []
        pending_len = 0

    for block in blocks:
        if not _is_translatable_block(block):
            flush_pending()
            translated_blocks.append(block)
            continue
        block_snippet = blocks_to_markdown(api_version, meta, [block])
        if pending and pending_len + len(block_snippet) > state.DOC_TRANSLATE_MAX_CHARS:
            flush_pending()
        pending.append(block)
        pending_len += len(block_snippet)

    flush_pending()
    if debug_job_dir is not None:
        translation_debug.record_plan(
            debug_job_dir,
            [
                {
                    "chunk_label": f"chunk_{index:04d}",
                    "mode": "doc_workspace_markdown",
                    "size": 1,
                }
                for index in range(1, chunk_counter + 1)
            ],
        )

    translated_doc = {
        "pandoc-api-version": api_version,
        "meta": meta,
        "blocks": translated_blocks,
    }
    return translated_doc


def translate_markdown_file(
    source_path: Path,
    out_path: Path,
    source_lang: str = "auto",
    target_lang: str = "en",
    debug_job_dir: Path | None = None,
) -> Path:
    markdown_text = source_path.read_text(encoding="utf-8")
    doc = markdown_to_doc(markdown_text)
    translated_doc = _translate_pandoc_doc(
        doc,
        source_lang=source_lang,
        target_lang=target_lang,
        snippet_to_text=blocks_to_markdown,
        text_to_blocks=markdown_to_blocks,
        debug_job_dir=debug_job_dir,
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc_to_markdown(translated_doc), encoding="utf-8")
    return out_path


def blocks_to_html(
    api_version: list[Any],
    meta: dict[str, Any],
    blocks: list[dict[str, Any]],
) -> str:
    doc = {"pandoc-api-version": api_version, "meta": meta, "blocks": blocks}
    return doc_to_html(doc).strip()


def html_to_blocks(html_text: str) -> list[dict[str, Any]]:
    return html_to_doc(html_text).get("blocks", []) or []


def _unwrap_html_code_fences(html_text: str) -> str:
    pattern = re.compile(r"```(?:html)?\s*\n(.*?)\n```", re.IGNORECASE | re.DOTALL)
    return pattern.sub(lambda match: match.group(1).strip(), html_text)


def _split_leading_trailing_ws(text: str) -> tuple[str, str, str]:
    leading_match = re.match(r"^\s*", text)
    trailing_match = re.search(r"\s*$", text)
    leading = leading_match.group(0) if leading_match else ""
    trailing = trailing_match.group(0) if trailing_match else ""
    core = text[len(leading) : len(text) - len(trailing) if trailing else len(text)]
    return leading, core, trailing


def _translate_html_text_nodes(
    html_text: str,
    *,
    source_lang: str = "auto",
    target_lang: str,
    debug_job_dir: Path | None = None,
) -> str:
    parts = re.split(r"(<[^>]+>)", html_text)
    client, model = _get_translation_client()
    glossary_entries = glossary.load_combined_glossary()
    system_prompt = _build_system_prompt(target_lang, glossary_entries, source_lang=source_lang)
    translated_cache: dict[str, str] = {}
    translated_parts: list[str] = []
    debug_ids: dict[str, str] = {}
    debug_plan: list[dict[str, Any]] = []

    for part in parts:
        if not part:
            continue
        if part.startswith("<") and part.endswith(">"):
            translated_parts.append(part)
            continue
        if not part.strip():
            translated_parts.append(part)
            continue

        leading, core, trailing = _split_leading_trailing_ws(part)
        if not core:
            translated_parts.append(part)
            continue
        translated_core = translated_cache.get(core)
        if translated_core is None:
            debug_custom_id = debug_ids.get(core)
            if debug_custom_id is None:
                debug_custom_id = f"chunk_{len(debug_ids) + 1:04d}"
                debug_ids[core] = debug_custom_id
                debug_plan.append(
                    {
                        "chunk_label": debug_custom_id,
                        "mode": "doc_workspace_html",
                        "size": 1,
                        "chars": len(core),
                        "ids": [debug_custom_id],
                    }
                )
            translated_core = _translate_text(
                core,
                client,
                model,
                system_prompt,
                glossary_entries=glossary_entries,
                debug_job_dir=debug_job_dir,
                debug_custom_id=debug_custom_id,
            )
            translated_cache[core] = translated_core
        translated_parts.append(f"{leading}{escape(translated_core, quote=False)}{trailing}")

    if debug_job_dir is not None:
        translation_debug.record_plan(debug_job_dir, debug_plan)
    return "".join(translated_parts)


def translate_html_file(
    source_path: Path,
    out_path: Path,
    source_lang: str = "auto",
    target_lang: str = "en",
    debug_job_dir: Path | None = None,
) -> Path:
    html_text = source_path.read_text(encoding="utf-8")
    out_path.parent.mkdir(parents=True, exist_ok=True)
    translated_html = _translate_html_text_nodes(
        html_text,
        source_lang=source_lang,
        target_lang=target_lang,
        debug_job_dir=debug_job_dir,
    )
    out_path.write_text(_unwrap_html_code_fences(translated_html), encoding="utf-8")
    return out_path
