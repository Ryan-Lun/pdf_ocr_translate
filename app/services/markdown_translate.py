from __future__ import annotations

import json
import logging
import subprocess
from copy import deepcopy
from pathlib import Path
from typing import Any

from . import glossary, openai_config, state

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


def markdown_to_doc(markdown_text: str) -> dict[str, Any]:
    return json.loads(_run_pandoc(markdown_text, "markdown", "json"))


def doc_to_markdown(doc: dict[str, Any]) -> str:
    payload = json.dumps(doc, ensure_ascii=False)
    return _run_pandoc(payload, "json", "markdown")


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
    return block_type not in {"CodeBlock", "RawBlock", "HorizontalRule"}


def _get_translation_client():
    return openai_config.create_sync_client(), state.DOC_TRANSLATE_MODEL


def _build_system_prompt(target_lang: str, glossary_entries: list[tuple[str, str]]) -> str:
    prompt = [
        state.DOC_TRANSLATE_SYSTEM_PROMPT,
        f"Target language: {target_lang}.",
    ]
    if glossary_entries:
        glossary_lines = "\n".join(
            f"- {src} => {dst}" for src, dst in glossary_entries[:50]
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
) -> str:
    if not snippet.strip():
        return snippet
    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": snippet},
        ],
    )
    translated = _extract_message_text(response)
    return translated or snippet


def translate_markdown_file(
    source_path: Path,
    out_path: Path,
    target_lang: str = "en",
) -> Path:
    markdown_text = source_path.read_text(encoding="utf-8")
    doc = markdown_to_doc(markdown_text)
    api_version = doc.get("pandoc-api-version", [])
    blocks = doc.get("blocks", []) or []
    meta = deepcopy(doc.get("meta", {}) or {})

    client, model = _get_translation_client()
    glossary_entries = glossary.load_combined_glossary()
    system_prompt = _build_system_prompt(target_lang, glossary_entries)

    translated_blocks: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    pending_len = 0

    def flush_pending() -> None:
        nonlocal pending, pending_len
        if not pending:
            return
        snippet = blocks_to_markdown(api_version, meta, pending)
        translated_snippet = _translate_snippet(snippet, client, model, system_prompt)
        parsed_blocks = markdown_to_blocks(translated_snippet)
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

    translated_doc = {
        "pandoc-api-version": api_version,
        "meta": meta,
        "blocks": translated_blocks,
    }
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(doc_to_markdown(translated_doc), encoding="utf-8")
    return out_path
