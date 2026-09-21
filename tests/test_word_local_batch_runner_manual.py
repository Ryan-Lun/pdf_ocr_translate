from __future__ import annotations

from pathlib import Path


def test_word_local_batch_runner_manual_covers_operations_and_acceptance():
    manual = Path("docs/system-description/24-WordLocalBatchRunner操作與驗收指引.md")
    text = manual.read_text(encoding="utf-8")

    required_phrases = [
        "一次性批次工具",
        "不會修改正式 `.env`",
        "不會改變一般 UI",
        "Department Glossary",
        "`--base-url`",
        "`--api-key`",
        "`--model`",
        "`--glossary-library-id`",
        "`--translate-tables true|false`",
        "`--stage-2-enabled true|false`",
        "`--disable-stage-2`",
        "`--overwrite`",
        "`--file-concurrency`",
        "`--word-request-concurrency`",
        "`--word-requests-per-minute`",
        "`--header-footer-exclude-pattern`",
        "`--header-footer-font-size`",
        "`--header-footer-term`",
        "`--exclude-table-index`",
        "Smoke-test-first",
        "Stage 1",
        "Stage 2",
        "`.doc` 轉檔預檢",
        "word_batch_report.json",
        "word_batch_report.csv",
        "job_id",
        "out/word_overlay/<job_id>/",
        "word_stage_2_post_edit.json",
        "單份樣本人工驗收清單",
        "Local Provider 驗收",
        "LOCAL_WORD_PROVIDER_ENABLED=0",
        "LOCAL_WORD_BASE_URL",
        "LOCAL_WORD_API_KEY",
        "LOCAL_WORD_MODEL",
        "不會建立 Cloud client",
        "word_translation_lifecycle.json",
        "job metadata",
    ]

    for phrase in required_phrases:
        assert phrase in text


def test_word_local_batch_runner_manual_is_listed_in_system_description_index():
    index = Path("docs/system-description/README.md").read_text(encoding="utf-8")

    assert "24-WordLocalBatchRunner操作與驗收指引.md" in index
    assert "Word Local Batch Runner 操作與驗收指引" in index
