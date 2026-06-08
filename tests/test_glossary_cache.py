from __future__ import annotations

import json

from app.services import glossary, state


def test_load_global_glossary_reload_on_write(tmp_path, monkeypatch):
    glossary_path = tmp_path / "global_glossary.json"
    glossary_path.write_text(
        json.dumps([{"cn": "初始詞", "en": "Initial Term"}], ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(state, "GLOBAL_GLOSSARY_PATH", str(glossary_path))
    glossary.invalidate_glossary_cache()

    first = glossary.load_global_glossary()
    assert first == [{"cn": "初始詞", "en": "Initial Term"}]

    glossary.write_global_glossary([{"cn": "更新詞", "en": "Updated Term"}])

    second = glossary.load_global_glossary()
    combined = glossary.load_combined_glossary()
    assert second == [{"cn": "更新詞", "en": "Updated Term"}]
    assert ("更新詞", "Updated Term") in combined
    assert ("初始詞", "Initial Term") not in combined


def test_empty_glossary_entries_disable_default_loading(tmp_path, monkeypatch):
    system_path = tmp_path / "system_glossary.json"
    global_path = tmp_path / "global_glossary.json"
    system_path.write_text("[]", encoding="utf-8")
    global_path.write_text(
        json.dumps([{"cn": "中文", "en": "Chinese"}], ensure_ascii=False),
        encoding="utf-8",
    )
    monkeypatch.setattr(state, "SYSTEM_GLOSSARY_PATH", str(system_path))
    monkeypatch.setattr(state, "GLOBAL_GLOSSARY_PATH", str(global_path))
    glossary.invalidate_glossary_cache()

    assert glossary.apply_glossary("中文說明", []) == "中文說明"
    assert glossary.apply_glossary_with_protection("中文說明", []) == "中文說明"
    assert glossary.apply_glossary("中文說明") == "Chinese說明"
    assert "[[[GLOSSARY_TERM_0001::Chinese]]]" in glossary.apply_glossary_with_protection("中文說明")
