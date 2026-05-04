from __future__ import annotations

import json
import re
import time
import unicodedata
from typing import Any

from . import state

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

_ENGLISH_TARGETS = {"en", "english", "en-us", "en-gb"}


def normalize_source_text(text: str | None) -> str:
    if text is None:
        return ""
    cleaned = unicodedata.normalize("NFKC", str(text))
    cleaned = cleaned.translate(_PUNCT_TRANSLATION)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def normalize_target_lang(target_lang: str | None) -> str:
    cleaned = str(target_lang or "").strip().lower()
    if not cleaned:
        return "en"
    if cleaned in _ENGLISH_TARGETS:
        return "en"
    return cleaned


def normalize_document_mode(document_mode: str | None) -> str:
    cleaned = str(document_mode or "").strip().lower()
    if cleaned == "general":
        return "general"
    if cleaned == "scanned":
        return "scanned"
    return "form"


def make_tm_key(
    source_text: str,
    target_lang: str,
    document_mode: str,
    *,
    source_normalized: str | None = None,
) -> str:
    normalized_source = (
        source_normalized
        if source_normalized is not None
        else normalize_source_text(source_text)
    )
    return (
        f"{normalize_document_mode(document_mode)}|"
        f"{normalize_target_lang(target_lang)}|"
        f"{normalized_source}"
    )


def _normalize_tm_entry(
    key: str,
    value: Any,
    now_ts: float,
) -> dict[str, Any] | None:
    if isinstance(value, str):
        value = {"target_text": value, "last_used": now_ts}
    if not isinstance(value, dict):
        return None

    target_text = value.get("target_text")
    if not isinstance(target_text, str):
        legacy_text = value.get("text")
        if not isinstance(legacy_text, str):
            return None
        target_text = legacy_text

    source_text = value.get("source_text")
    if source_text is not None:
        source_text = str(source_text)

    source_normalized = value.get("source_normalized")
    if source_normalized is None and source_text:
        source_normalized = normalize_source_text(source_text)
    elif source_normalized is not None:
        source_normalized = normalize_source_text(str(source_normalized))

    target_lang = value.get("target_lang")
    if target_lang is not None:
        target_lang = normalize_target_lang(str(target_lang))

    document_mode = value.get("document_mode")
    if document_mode is not None:
        document_mode = normalize_document_mode(str(document_mode))

    last_used = value.get("last_used")
    try:
        last_used_ts = float(last_used) if last_used is not None else now_ts
    except (TypeError, ValueError):
        last_used_ts = now_ts

    created_at = value.get("created_at")
    try:
        created_at_ts = float(created_at) if created_at is not None else last_used_ts
    except (TypeError, ValueError):
        created_at_ts = last_used_ts

    count = value.get("count")
    try:
        count_int = max(1, int(count)) if count is not None else 1
    except (TypeError, ValueError):
        count_int = 1

    entry_source = str(value.get("source") or "batch").strip() or "batch"
    normalized = {
        "source_text": source_text,
        "source_normalized": source_normalized,
        "target_text": target_text,
        "target_lang": target_lang,
        "document_mode": document_mode,
        "created_at": created_at_ts,
        "last_used": last_used_ts,
        "source": entry_source,
        "count": count_int,
    }

    # Keep legacy English form entries readable until they are promoted.
    if (
        "|" not in key
        and normalized["source_normalized"] is None
        and isinstance(key, str)
        and key.strip()
    ):
        normalized["source_normalized"] = normalize_source_text(key)

    return normalized


def load_translation_memory() -> dict[str, dict[str, Any]]:
    path = state.TRANSLATION_MEMORY_PATH
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}
    if not isinstance(data, dict):
        return {}
    now_ts = time.time()
    ttl_seconds = state.TRANSLATION_MEMORY_TTL_SECONDS
    cleaned: dict[str, dict[str, Any]] = {}
    changed = False
    for k, v in data.items():
        if not isinstance(k, str):
            changed = True
            continue
        entry = _normalize_tm_entry(k, v, now_ts)
        if not entry:
            changed = True
            continue
        last_used = entry.get("last_used", now_ts)
        if ttl_seconds and (now_ts - float(last_used) > ttl_seconds):
            changed = True
            continue
        cleaned[k] = entry
        if entry != v:
            changed = True
    if changed:
        write_translation_memory(cleaned)
    return cleaned


def write_translation_memory(memory: dict[str, dict[str, Any]]) -> None:
    path = state.TRANSLATION_MEMORY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(memory, ensure_ascii=False, indent=2), encoding="utf-8")


def extract_target_text(entry: dict[str, Any] | None) -> str:
    if not isinstance(entry, dict):
        return ""
    target_text = entry.get("target_text")
    if isinstance(target_text, str):
        return target_text
    legacy_text = entry.get("text")
    return str(legacy_text or "")


def get_tm_entry(
    memory: dict[str, dict[str, Any]],
    source_text: str,
    target_lang: str,
    document_mode: str,
    *,
    source_normalized: str | None = None,
) -> tuple[str, dict[str, Any]] | tuple[None, None]:
    normalized_source = (
        source_normalized
        if source_normalized is not None
        else normalize_source_text(source_text)
    )
    if not normalized_source:
        return None, None

    key = make_tm_key(
        source_text,
        target_lang,
        document_mode,
        source_normalized=normalized_source,
    )
    entry = memory.get(key)
    if entry:
        return key, entry

    legacy_key = normalized_source
    legacy_entry = memory.get(legacy_key)
    if (
        legacy_entry
        and normalize_document_mode(document_mode) == "form"
        and normalize_target_lang(target_lang) in _ENGLISH_TARGETS
    ):
        return legacy_key, legacy_entry
    return None, None


def touch_entry(entry: dict[str, Any], now_ts: float | None = None) -> None:
    entry["last_used"] = float(now_ts if now_ts is not None else time.time())


def upsert_entry(
    memory: dict[str, dict[str, Any]],
    source_text: str,
    target_text: str,
    target_lang: str,
    document_mode: str,
    *,
    source_normalized: str | None = None,
    source: str = "batch",
    now_ts: float | None = None,
) -> str | None:
    normalized_source = (
        source_normalized
        if source_normalized is not None
        else normalize_source_text(source_text)
    )
    cleaned_target = str(target_text or "").strip()
    if not normalized_source or not cleaned_target:
        return None

    now = float(now_ts if now_ts is not None else time.time())
    key = make_tm_key(
        source_text,
        target_lang,
        document_mode,
        source_normalized=normalized_source,
    )
    existing = memory.get(key)
    created_at = now
    count = 1
    if existing:
        created_at = float(existing.get("created_at") or now)
        try:
            count = max(1, int(existing.get("count") or 0)) + 1
        except (TypeError, ValueError):
            count = 1

    memory[key] = {
        "source_text": str(source_text or ""),
        "source_normalized": normalized_source,
        "target_text": cleaned_target,
        "target_lang": normalize_target_lang(target_lang),
        "document_mode": normalize_document_mode(document_mode),
        "created_at": created_at,
        "last_used": now,
        "source": str(source or "batch").strip() or "batch",
        "count": count,
    }
    return key
