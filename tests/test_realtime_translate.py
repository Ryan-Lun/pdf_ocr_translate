from app.services import realtime_translate


def test_build_chunk_prompt_repeats_numbered_item_rules():
    prompt = realtime_translate._build_chunk_prompt(
        target_lang="en",
        system_prompt="base prompt",
    )

    assert "line break strictly before the second and later numbered items" in prompt
    assert "Do not add line breaks inside the same numbered item." in prompt


def test_normalize_numbered_item_breaks_splits_later_items_on_same_line():
    text = "1. First step 2. Second step 3. Third step"

    assert realtime_translate._normalize_numbered_item_breaks(text) == (
        "1. First step\n2. Second step\n3. Third step"
    )


def test_normalize_numbered_item_breaks_preserves_single_item_line():
    text = "Section 2. Scope"

    assert realtime_translate._normalize_numbered_item_breaks(text) == text


def test_glossary_protection_wraps_and_restores_terms():
    protected = realtime_translate.batch.glossary.apply_glossary_with_protection(
        "本產品符合品質系統規範。",
        [("品質系統規範", "Quality System Regulation")],
    )

    assert "Quality System Regulation" in protected
    assert "[[[GLOSSARY_TERM_" in protected
    assert (
        realtime_translate.batch.glossary.restore_protected_glossary_terms(protected)
        == "本產品符合Quality System Regulation。"
    )
