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
        "traditional chinese": "zh",
        "繁體中文": "zh",
        "zh-tw": "zh",
        "zh-hant": "zh",
        "zh_tw": "zh",
        "zh_hant": "zh",
        "simplified chinese": "zh-cn",
        "简体中文": "zh-cn",
        "簡體中文": "zh-cn",
        "zh-cn": "zh-cn",
        "zh-hans": "zh-cn",
        "zh_cn": "zh-cn",
        "zh_hans": "zh-cn",
        "cn": "zh-cn",
        "zh-sg": "zh-cn",
        "zh_sg": "zh-cn",
    }
    return aliases.get(cleaned, cleaned or "auto")


def describe_target_language(target_lang: str) -> str:
    normalized = normalize_lang_code(target_lang)
    if normalized == "zh":
        return "Traditional Chinese (繁體中文)"
    if normalized == "zh-cn":
        return "Simplified Chinese (简体中文)"
    if normalized == "en":
        return "English"
    return str(target_lang or "").strip() or "the requested target language"


def target_language_script_instruction(target_lang: str) -> str:
    normalized = normalize_lang_code(target_lang)
    if normalized == "zh":
        return "Use Traditional Chinese characters only. Never use Simplified Chinese characters."
    if normalized == "zh-cn":
        return "Use Simplified Chinese characters only. Never use Traditional Chinese characters."
    return ""


def traditional_chinese_instruction(target_lang: str) -> str:
    return target_language_script_instruction(target_lang)
