from __future__ import annotations

import pytest

from app.services import job_store, state, translation_memory


def _clear_tm_entries() -> None:
    with job_store.session_scope() as session:
        session.query(job_store.TranslationMemoryEntryRecord).delete()


def test_sql_translation_memory_retrieves_approved_byte_exact_match(app, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_ENABLED", True)
    _clear_tm_entries()

    entry_id = translation_memory.upsert_sql_entry(
        source_text="確認首件半成品尺寸是否符合製程規範。",
        target_text="Confirm whether the dimensions of the first semi-finished product comply with the Process Specification.",
        source_lang="zh-TW",
        target_lang="en",
        document_mode="form",
        status="approved",
        source="test",
        notes="seed",
    )

    result = translation_memory.retrieve_sql(
        "確認首件半成品尺寸是否符合製程規範。",
        source_lang="zh-TW",
        target_lang="English",
        document_mode="form",
    )

    assert result.exact_match is not None
    assert result.exact_match.entry_id == entry_id
    assert result.exact_match.match_type == "byte_exact"
    assert result.exact_match.target_text.startswith("Confirm whether")
    assert result.fuzzy_references == []
    assert result.semantic_references == []


def test_sql_translation_memory_filters_disabled_entries(app, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_ENABLED", True)
    _clear_tm_entries()
    translation_memory.upsert_sql_entry(
        source_text="確認設備是否正常。",
        target_text="Confirm whether the equipment is normal.",
        source_lang="zh-TW",
        target_lang="en",
        document_mode="form",
        status="disabled",
    )

    result = translation_memory.retrieve_sql(
        "確認設備是否正常。",
        source_lang="zh-TW",
        target_lang="en",
        document_mode="form",
    )

    assert result.exact_match is None
    assert result.fuzzy_references == []


def test_sql_translation_memory_normalized_exact_direct_reuse_requires_same_document_mode(app, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_ENABLED", True)
    _clear_tm_entries()
    entry_id = translation_memory.upsert_sql_entry(
        source_text="確認首件半成品尺寸是否符合製程規範。",
        target_text="Confirm whether the dimensions of the first semi-finished product comply with the Process Specification.",
        source_lang="zh-TW",
        target_lang="en",
        document_mode="form",
        status="approved",
    )

    same_mode = translation_memory.retrieve_sql(
        "確認首件半成品尺寸是否符合製程規範.",
        source_lang="zh-TW",
        target_lang="en",
        document_mode="form",
    )
    cross_mode = translation_memory.retrieve_sql(
        "確認首件半成品尺寸是否符合製程規範.",
        source_lang="zh-TW",
        target_lang="en",
        document_mode="word",
    )

    assert same_mode.exact_match is not None
    assert same_mode.exact_match.entry_id == entry_id
    assert same_mode.exact_match.match_type == "normalized_exact"
    assert cross_mode.exact_match is None
    assert [ref.entry_id for ref in cross_mode.fuzzy_references] == [entry_id]


def test_sql_translation_memory_fuzzy_references_are_limited_and_cross_document_mode(app, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_ENABLED", True)
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_FUZZY_THRESHOLD", 0.6)
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_FUZZY_LIMIT", 2)
    _clear_tm_entries()
    first_id = translation_memory.upsert_sql_entry(
        source_text="確認首件半成品尺寸是否符合製程規範。",
        target_text="Confirm whether the dimensions of the first semi-finished product comply with the Process Specification.",
        source_lang="zh-TW",
        target_lang="en",
        document_mode="form",
        status="approved",
    )
    second_id = translation_memory.upsert_sql_entry(
        source_text="確認首件成品尺寸是否符合製程規範。",
        target_text="Confirm whether the dimensions of the first finished product comply with the Process Specification.",
        source_lang="zh-TW",
        target_lang="en",
        document_mode="word",
        status="approved",
    )
    translation_memory.upsert_sql_entry(
        source_text="包裝前確認標籤內容。",
        target_text="Confirm the label content before packaging.",
        source_lang="zh-TW",
        target_lang="en",
        document_mode="form",
        status="approved",
    )

    result = translation_memory.retrieve_sql(
        "確認首件成品尺寸是否符合製程規範。",
        source_lang="zh-TW",
        target_lang="en",
        document_mode="scanned",
    )

    assert result.exact_match is None
    assert [ref.entry_id for ref in result.fuzzy_references] == [second_id, first_id]
    assert all(ref.match_type == "fuzzy" for ref in result.fuzzy_references)
    assert all(ref.score >= 0.6 for ref in result.fuzzy_references)


def test_sql_translation_memory_does_not_fuzzy_match_short_segments(app, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_ENABLED", True)
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_MIN_FUZZY_CHARS", 8)
    _clear_tm_entries()
    translation_memory.upsert_sql_entry(
        source_text="外觀",
        target_text="Appearance",
        source_lang="zh-TW",
        target_lang="en",
        document_mode="form",
        status="approved",
    )

    result = translation_memory.retrieve_sql(
        "外觀形狀",
        source_lang="zh-TW",
        target_lang="en",
        document_mode="form",
    )

    assert result.exact_match is None
    assert result.fuzzy_references == []


def test_sql_translation_memory_updates_exact_and_reference_counters(app, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_ENABLED", True)
    _clear_tm_entries()
    entry_id = translation_memory.upsert_sql_entry(
        source_text="確認設備是否正常。",
        target_text="Confirm whether the equipment is normal.",
        source_lang="zh-TW",
        target_lang="en",
        document_mode="form",
        status="approved",
    )

    translation_memory.record_exact_reuse([entry_id])
    translation_memory.record_reference_use([entry_id, entry_id])

    entry = translation_memory.get_sql_entry(entry_id)
    assert entry is not None
    assert entry.exact_reuse_count == 1
    assert entry.reference_count == 2
    assert entry.last_used_at is not None
    assert entry.last_referenced_at is not None


def test_sql_translation_memory_returns_empty_result_when_disabled(app, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_ENABLED", False)
    _clear_tm_entries()
    translation_memory.upsert_sql_entry(
        source_text="確認設備是否正常。",
        target_text="Confirm whether the equipment is normal.",
        source_lang="zh-TW",
        target_lang="en",
        document_mode="form",
        status="approved",
    )

    result = translation_memory.retrieve_sql(
        "確認設備是否正常。",
        source_lang="zh-TW",
        target_lang="en",
        document_mode="form",
    )

    assert result.exact_match is None
    assert result.fuzzy_references == []
    assert result.semantic_references == []


def test_sql_translation_memory_rejects_unknown_status(app):
    _clear_tm_entries()

    with pytest.raises(ValueError, match="Unsupported Translation Memory status"):
        translation_memory.upsert_sql_entry(
            source_text="確認設備是否正常。",
            target_text="Confirm whether the equipment is normal.",
            source_lang="zh-TW",
            target_lang="en",
            document_mode="form",
            status="draft",
        )


def test_sql_translation_memory_entry_input_helper_persists_metadata(app, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_ENABLED", True)
    _clear_tm_entries()

    entry_id = translation_memory.upsert_sql_entry_input(
        translation_memory.TranslationMemoryEntryInput(
            source_text="確認設備是否正常。",
            target_text="Confirm whether the equipment is normal.",
            source_lang="zh-TW",
            target_lang="en",
            document_mode="form",
            status="approved",
            source="csv_import",
            source_job_id="a" * 32,
            source_metadata={"row": 2},
            notes="reviewed",
        )
    )

    entry = translation_memory.get_sql_entry(entry_id)
    assert entry is not None
    assert entry.source == "csv_import"
    assert entry.source_job_id == "a" * 32
    assert entry.source_metadata == {"row": 2}
    assert entry.notes == "reviewed"


def test_sql_translation_memory_semantic_reference_seam_returns_empty_list(app):
    assert translation_memory.retrieve_semantic_references(
        "作業前確認設備是否正常。",
        source_lang="zh-TW",
        target_lang="en",
        document_mode="form",
    ) == []
