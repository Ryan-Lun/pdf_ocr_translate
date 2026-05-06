from __future__ import annotations

import json
from pathlib import Path

from . import state


def global_glossary_path() -> Path:
    return Path(state.GLOBAL_GLOSSARY_PATH)


def load_global_glossary() -> list[dict[str, str]]:
    path = global_glossary_path()
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    cleaned: list[dict[str, str]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        cn = str(item.get("cn") or "").strip()
        en = str(item.get("en") or "").strip()
        if not cn or not en:
            continue
        cleaned.append({"cn": cn, "en": en})
    return cleaned


def write_global_glossary(items: list[dict[str, str]]) -> None:
    payload: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        if not isinstance(item, dict):
            continue
        cn = str(item.get("cn") or "").strip()
        en = str(item.get("en") or "").strip()
        if not cn or not en:
            continue
        key = (cn, en)
        if key in seen:
            continue
        payload.append({"cn": cn, "en": en})
        seen.add(key)
    global_glossary_path().write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def load_glossary_entries() -> list[tuple[str, str]]:
    entries: list[tuple[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for raw_path in (
        state.GLOSSARY_INSPECTION_PATH,
        state.GLOSSARY_PROCESS_PATH,
        state.GLOBAL_GLOSSARY_PATH,
    ):
        if not raw_path:
            continue
        path = Path(raw_path)
        if not path.is_absolute():
            path = Path(__file__).resolve().parent / path
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(data, list):
            continue
        for item in data:
            if not isinstance(item, dict):
                continue
            cn = str(item.get("cn") or "").strip()
            en = str(item.get("en") or "").strip()
            if not cn or not en:
                continue
            key = (cn, en)
            if key in seen:
                continue
            entries.append(key)
            seen.add(key)
    entries.sort(key=lambda pair: len(pair[0]), reverse=True)
    return entries


def load_combined_glossary() -> list[tuple[str, str]]:
    return load_glossary_entries()


def apply_glossary(text: str, entries: list[tuple[str, str]] | None = None) -> str:
    if not text:
        return text
    entries = entries or load_glossary_entries()
    if not entries:
        return text
    out = text
    hits: list[tuple[str, str]] = []
    for cn, en in entries:
        if cn in out:
            out = out.replace(cn, en)
            hits.append((cn, en))
    if hits:
        preview = ", ".join([f"{cn}->{en}" for cn, en in hits[:6]])
        more = f" (+{len(hits) - 6})" if len(hits) > 6 else ""
        print(f"[GLOSSARY] hits={len(hits)} {preview}{more}")
    return out
