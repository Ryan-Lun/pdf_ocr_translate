from __future__ import annotations

from typing import Any


def normalize_lang_code(value: Any) -> str:
    cleaned = str(value or "").strip().lower()
    aliases = {
        "auto": "auto",
        "english": "en",
        "en-us": "en",
        "en-gb": "en",
        "chinese": "zh",
        "zh-cn": "zh",
        "zh-tw": "zh",
        "zh-hans": "zh",
        "zh-hant": "zh",
    }
    return aliases.get(cleaned, cleaned or "auto")


def describe_target_language(target_lang: str) -> str:
    normalized = normalize_lang_code(target_lang)
    if normalized == "zh":
        return "Traditional Chinese (繁體中文)"
    if normalized == "en":
        return "English"
    return str(target_lang or "").strip() or "the requested target language"


def traditional_chinese_instruction(target_lang: str) -> str:
    if normalize_lang_code(target_lang) == "zh":
        return "Use Traditional Chinese characters only. Never use Simplified Chinese characters."
    return ""
