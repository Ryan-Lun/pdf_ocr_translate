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


def test_glossary_entries_reverse_for_english_to_chinese():
    entries = [("批號", "Batch No."), ("批號格式", "Batch No. Format")]

    assert glossary.glossary_pairs_for_translation(
        entries,
        source_lang="en",
        target_lang="zh",
    ) == [("Batch No. Format", "批號格式"), ("Batch No.", "批號")]
    assert (
        glossary.apply_glossary(
            "Batch No. Format: Batch No.",
            entries,
            source_lang="en",
            target_lang="zh",
        )
        == "批號格式: 批號"
    )
    protected = glossary.apply_glossary_with_protection(
        "Batch No.",
        entries,
        source_lang="auto",
        target_lang="zh-cn",
    )
    assert "[[[GLOSSARY_TERM_0001::批號]]]" in protected
    assert glossary.restore_protected_glossary_terms(protected) == "批號"


def test_restore_protected_glossary_terms_tolerates_extra_brackets():
    text = "The purpose is [[[[GLOSSARY_TERM_0001::artificial hip joint]]] replacement."

    assert (
        glossary.restore_protected_glossary_terms(text)
        == "The purpose is artificial hip joint replacement."
    )
