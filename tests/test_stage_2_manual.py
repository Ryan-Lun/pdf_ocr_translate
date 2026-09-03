from __future__ import annotations

from pathlib import Path


def test_stage_2_manual_covers_configuration_artifacts_and_acceptance_cases():
    manual = Path("docs/system-description/20-Stage2兩階段翻譯設定與驗收指引.md")
    text = manual.read_text(encoding="utf-8")

    required_phrases = [
        "TRANSLATION_POST_EDIT_ENABLED",
        "TRANSLATION_POST_EDIT_MODEL",
        "TRANSLATION_POST_EDIT_TEMPERATURE",
        "TRANSLATION_POST_EDIT_MAX_TOKENS",
        "預設為關閉",
        "Stage 2 關閉時",
        "TM Exact Match",
        "Approved Translation",
        "不會再送 Stage 2",
        "不會自動寫入 Translation Memory",
        "word_stage_2_post_edit.json",
        "pdf_batch_stage_2_post_edit.json",
        "pdf_markdown_stage_2_post_edit.json",
        "stage_1_draft",
        "stage_2_revised",
        "changed",
        "fallback_reason",
        "validation_warnings",
        "translationese",
        "already-natural draft",
        "Required Glossary Term",
        "Exact Protected Content",
        "numbers、dates、units、factual values",
        "must / should / may",
        "fallback 到 Stage 1",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_stage_2_manual_is_listed_in_system_description_index():
    index = Path("docs/system-description/README.md").read_text(encoding="utf-8")

    assert "20-Stage2兩階段翻譯設定與驗收指引.md" in index
    assert "Stage 2 兩階段翻譯設定與驗收指引" in index
