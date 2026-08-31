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


def test_apply_required_glossary_terms_returns_structured_hits():
    result = glossary.apply_required_glossary_terms(
        "外觀形狀與製程規範",
        [("外觀", "Appearance"), ("製程規範", "Process Specification")],
    )

    assert result.text == (
        '<term id="0001">Appearance</term>形狀與'
        '<term id="0002">Process Specification</term>'
    )
    assert result.required_terms == (
        glossary.RequiredGlossaryTerm(
            id="0001",
            source="外觀",
            target="Appearance",
        ),
        glossary.RequiredGlossaryTerm(
            id="0002",
            source="製程規範",
            target="Process Specification",
        ),
    )


def test_required_glossary_terms_escape_and_restore_targets():
    result = glossary.apply_required_glossary_terms(
        "特殊詞",
        [("特殊詞", "A&B <Spec> \"Prime\" 'Core'")],
    )

    assert result.text == (
        '<term id="0001">A&amp;B &lt;Spec&gt; &quot;Prime&quot; '
        "&apos;Core&apos;</term>"
    )
    assert (
        glossary.restore_protected_glossary_terms(result.text, result.required_terms)
        == "A&B <Spec> \"Prime\" 'Core'"
    )


def test_restore_required_glossary_terms_without_context_uses_wrapped_target():
    text = 'The <term id="0001">Appearance</term> shape was checked.'

    assert (
        glossary.restore_protected_glossary_terms(text)
        == "The Appearance shape was checked."
    )


def test_restore_required_glossary_terms_accepts_target_map():
    text = 'The <term id="0002">Visual Appearance</term> shape was checked.'

    assert (
        glossary.restore_protected_glossary_terms(text, {"0002": "Appearance"})
        == "The Appearance shape was checked."
    )


def test_restore_required_glossary_terms_uses_approved_target_from_context():
    result = glossary.apply_required_glossary_terms(
        "外觀",
        [("外觀", "Appearance")],
    )
    model_output = result.text.replace("Appearance", "Visual Appearance")

    assert (
        glossary.restore_protected_glossary_terms(model_output, result.required_terms)
        == "Appearance"
    )


def test_find_missing_required_glossary_terms_only_checks_matched_terms():
    result = glossary.apply_required_glossary_terms(
        "外觀",
        [("外觀", "Appearance"), ("製程規範", "Process Specification")],
    )

    assert glossary.find_missing_required_glossary_terms(
        "The Appearance shape was checked.",
        result.required_terms,
    ) == []
    assert glossary.find_missing_required_glossary_terms(
        "The shape was checked.",
        result.required_terms,
    ) == ["Appearance"]


def test_required_glossary_terms_preserve_longest_match_and_reversal():
    entries = [("批號", "Batch No."), ("批號格式", "Batch No. Format")]

    result = glossary.apply_required_glossary_terms("批號格式: 批號", entries)
    assert result.text == (
        '<term id="0001">Batch No. Format</term>: '
        '<term id="0002">Batch No.</term>'
    )

    reversed_result = glossary.apply_required_glossary_terms(
        "Batch No. Format",
        entries,
        source_lang="en",
        target_lang="zh",
    )
    assert reversed_result.text == '<term id="0001">批號格式</term>'
