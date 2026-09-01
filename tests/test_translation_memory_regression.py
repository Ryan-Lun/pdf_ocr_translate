from __future__ import annotations

import importlib
import json
import re
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.services import job_store, schema_control, state, translation_memory
from app.services.batch import build_batch_items, build_translations_from_jsonl_text

ROOT = Path(__file__).resolve().parents[1]


def _tm_match(
    *,
    entry_id: int,
    match_type: str,
    source_text: str,
    target_text: str,
    score: float,
    document_mode: str = "form",
) -> translation_memory.TranslationMemoryMatch:
    return translation_memory.TranslationMemoryMatch(
        entry_id=entry_id,
        match_type=match_type,
        source_text=source_text,
        source_normalized=translation_memory.normalize_source_text(source_text),
        target_text=target_text,
        source_lang="zh",
        target_lang="en",
        document_mode=document_mode,
        score=score,
    )


def _tm_result(
    source_text: str,
    *,
    exact_match: translation_memory.TranslationMemoryMatch | None = None,
    fuzzy_references: list[translation_memory.TranslationMemoryMatch] | None = None,
    semantic_references: list[translation_memory.TranslationMemoryMatch] | None = None,
) -> translation_memory.TranslationMemoryRetrievalResult:
    return translation_memory.TranslationMemoryRetrievalResult(
        source_text=source_text,
        source_normalized=translation_memory.normalize_source_text(source_text),
        source_lang="zh",
        target_lang="en",
        document_mode="form",
        exact_match=exact_match,
        fuzzy_references=fuzzy_references or [],
        semantic_references=semantic_references or [],
    )


def test_pdf_tm_requires_both_global_and_pdf_feature_flags(monkeypatch):
    exact = _tm_match(
        entry_id=1,
        match_type="byte_exact",
        source_text="確認設備是否正常。",
        target_text="Confirm whether the equipment is operating normally.",
        score=1.0,
    )
    retrieval_calls: list[str] = []

    def fake_retrieve_sql(source_text, **kwargs):
        retrieval_calls.append(str(source_text))
        return _tm_result(str(source_text), exact_match=exact)

    monkeypatch.setattr(translation_memory, "retrieve_sql", fake_retrieve_sql)
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_ENABLED", False)
    monkeypatch.setattr(state, "PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY", True)

    items, _, _, prefilled = build_batch_items(
        [{"page_index_0based": 0, "rec_texts": ["確認設備是否正常。"], "rec_polys": []}],
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[],
        target_lang="en",
        source_lang="zh",
        document_mode="form",
    )

    assert retrieval_calls == []
    assert [item["custom_id"] for item in items] == ["p0000-l0000"]
    assert prefilled == {}

    monkeypatch.setattr(state, "TRANSLATION_MEMORY_ENABLED", True)
    monkeypatch.setattr(state, "PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY", False)
    items, _, _, prefilled = build_batch_items(
        [{"page_index_0based": 0, "rec_texts": ["確認設備是否正常。"], "rec_polys": []}],
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[],
        target_lang="en",
        source_lang="zh",
        document_mode="form",
    )

    assert retrieval_calls == []
    assert [item["custom_id"] for item in items] == ["p0000-l0000"]
    assert prefilled == {}

    monkeypatch.setattr(state, "PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY", True)
    items, _, _, prefilled = build_batch_items(
        [{"page_index_0based": 0, "rec_texts": ["確認設備是否正常。"], "rec_polys": []}],
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[],
        target_lang="en",
        source_lang="zh",
        document_mode="form",
    )

    assert retrieval_calls == ["確認設備是否正常。"]
    assert items == []
    assert prefilled == {"p0000-l0000": "Confirm whether the equipment is operating normally."}


def test_tm_references_are_prompt_context_not_direct_translations(monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_ENABLED", True)
    monkeypatch.setattr(state, "PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY", True)
    fuzzy = _tm_match(
        entry_id=2,
        match_type="fuzzy",
        source_text="確認設備是否正常。",
        target_text="Confirm whether the equipment is normal.",
        score=0.91,
    )
    semantic = _tm_match(
        entry_id=3,
        match_type="semantic",
        source_text="作業前確認機台運作狀態。",
        target_text="Check the machine operating condition before operation.",
        score=0.86,
    )
    monkeypatch.setattr(
        translation_memory,
        "retrieve_sql",
        lambda source_text, **kwargs: _tm_result(
            str(source_text),
            fuzzy_references=[fuzzy],
            semantic_references=[semantic],
        ),
    )

    collector = translation_memory.create_artifact_collector()
    items, _, key_map, prefilled = build_batch_items(
        [{"page_index_0based": 0, "rec_texts": ["確認設備是否異常。"], "rec_polys": []}],
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[],
        target_lang="en",
        source_lang="zh",
        document_mode="form",
        tm_artifact_collector=collector,
    )

    assert prefilled == {}
    assert [item["custom_id"] for item in items] == ["p0000-l0000"]
    user_content = items[0]["body"]["messages"][1]["content"]
    system_content = items[0]["body"]["messages"][0]["content"]
    assert "Current source text:" in user_content
    assert "確認設備是否異常。" in user_content
    assert "Translation Memory references:" in user_content
    assert fuzzy.target_text in user_content
    assert semantic.target_text in user_content
    assert "Do not copy a Translation Memory reference mechanically" in system_content
    references = key_map["p0000-l0000"]["translation_memory_references"]
    assert [reference["match_type"] for reference in references] == ["fuzzy", "semantic"]
    assert [row["match_type"] for row in collector.references] == ["fuzzy", "semantic"]
    assert collector.matches == []


def test_required_glossary_term_stays_stronger_than_tm_reference(monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_ENABLED", True)
    monkeypatch.setattr(state, "PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY", True)
    fuzzy = _tm_match(
        entry_id=4,
        match_type="fuzzy",
        source_text="作業前確認外觀是否正常。",
        target_text="Before operation, confirm whether the look is normal.",
        score=0.9,
    )
    monkeypatch.setattr(
        translation_memory,
        "retrieve_sql",
        lambda source_text, **kwargs: _tm_result(str(source_text), fuzzy_references=[fuzzy]),
    )

    items, _, key_map, prefilled = build_batch_items(
        [{"page_index_0based": 0, "rec_texts": ["作業前確認外觀。"], "rec_polys": []}],
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[("外觀", "Appearance")],
        target_lang="en",
        source_lang="zh",
        document_mode="form",
    )

    assert prefilled == {}
    system_content = items[0]["body"]["messages"][0]["content"]
    user_content = items[0]["body"]["messages"][1]["content"]
    assert "They cannot override any Required Glossary Term" in system_content
    assert '<term id="0001">Appearance</term>' in user_content
    assert "look is normal" in user_content
    assert key_map["p0000-l0000"]["required_glossary_terms"][0]["target"] == "Appearance"

    bad_raw_text = json.dumps(
        {
            "custom_id": "p0000-l0000",
            "response": {"body": {"output_text": "Before operation, confirm whether the look is normal."}},
        }
    )
    try:
        build_translations_from_jsonl_text(bad_raw_text, key_map=key_map)
    except RuntimeError as exc:
        assert "missing required glossary terms" in str(exc)
        assert "Appearance" in str(exc)
    else:
        raise AssertionError("TM wording that omits the required glossary term must fail validation")

    good_raw_text = json.dumps(
        {
            "custom_id": "p0000-l0000",
            "response": {"body": {"output_text": "Confirm the Appearance before operation."}},
        }
    )
    assert build_translations_from_jsonl_text(good_raw_text, key_map=key_map) == {
        "p0000-l0000": "Confirm the Appearance before operation."
    }


def test_markdown_translation_does_not_call_or_emit_translation_memory(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_ENABLED", True)
    module = importlib.import_module("app.services.markdown_translate")
    source = tmp_path / "doc.html"
    output = tmp_path / "doc.translated.html"
    source.write_text("<p>確認設備是否正常。</p>", encoding="utf-8")
    requests: list[dict] = []

    class FakeCompletions:
        def create(self, **kwargs):
            requests.append(kwargs)
            message = type("Message", (), {"content": "Confirm whether the equipment is normal."})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    def fail_retrieve_sql(*args, **kwargs):
        raise AssertionError("Markdown translation must not call Translation Memory retrieval")

    monkeypatch.setattr(translation_memory, "retrieve_sql", fail_retrieve_sql)
    monkeypatch.setattr(module, "_get_translation_client", lambda: (FakeClient(), "fake-model"))
    monkeypatch.setattr(module.glossary, "load_combined_glossary", lambda: [])

    module.translate_html_file(source, output, target_lang="en", debug_job_dir=tmp_path / "job")

    assert output.read_text(encoding="utf-8") == "<p>Confirm whether the equipment is normal.</p>"
    assert requests
    assert "Translation Memory references" not in requests[0]["messages"][0]["content"]
    assert "Translation Memory references" not in requests[0]["messages"][-1]["content"]
    assert not (tmp_path / "job" / "tm_matches.json").exists()
    assert not (tmp_path / "job" / "tm_references.json").exists()


def test_translation_memory_schema_baseline_migration_and_sql_init_stay_aligned(monkeypatch, tmp_path):
    table = job_store.TranslationMemoryEntryRecord.__table__
    model_columns = tuple(table.columns.keys())
    assert schema_control.REQUIRED_COLUMNS["translation_memory_entries"] == model_columns
    model_contract = {
        column.name: {
            "type": str(column.type),
            "nullable": bool(column.nullable),
            "primary_key": bool(column.primary_key),
            "autoincrement": column.autoincrement,
            "default": column.default.arg if column.default is not None else None,
            "server_default": column.server_default.arg if column.server_default is not None else None,
        }
        for column in table.columns
    }
    assert model_contract == {
        "id": {"type": "INTEGER", "nullable": False, "primary_key": True, "autoincrement": True, "default": None, "server_default": None},
        "source_text": {"type": "TEXT", "nullable": False, "primary_key": False, "autoincrement": "auto", "default": None, "server_default": None},
        "source_normalized": {"type": "TEXT", "nullable": False, "primary_key": False, "autoincrement": "auto", "default": None, "server_default": None},
        "source_hash": {"type": "VARCHAR(64)", "nullable": False, "primary_key": False, "autoincrement": "auto", "default": None, "server_default": None},
        "target_text": {"type": "TEXT", "nullable": False, "primary_key": False, "autoincrement": "auto", "default": None, "server_default": None},
        "source_lang": {"type": "VARCHAR(20)", "nullable": False, "primary_key": False, "autoincrement": "auto", "default": None, "server_default": None},
        "target_lang": {"type": "VARCHAR(20)", "nullable": False, "primary_key": False, "autoincrement": "auto", "default": None, "server_default": None},
        "document_mode": {"type": "VARCHAR(20)", "nullable": False, "primary_key": False, "autoincrement": "auto", "default": None, "server_default": None},
        "status": {"type": "VARCHAR(20)", "nullable": False, "primary_key": False, "autoincrement": "auto", "default": "approved", "server_default": None},
        "source": {"type": "VARCHAR(100)", "nullable": True, "primary_key": False, "autoincrement": "auto", "default": None, "server_default": None},
        "source_job_id": {"type": "VARCHAR(32)", "nullable": True, "primary_key": False, "autoincrement": "auto", "default": None, "server_default": None},
        "source_metadata_json": {"type": "TEXT", "nullable": True, "primary_key": False, "autoincrement": "auto", "default": None, "server_default": None},
        "notes": {"type": "TEXT", "nullable": True, "primary_key": False, "autoincrement": "auto", "default": None, "server_default": None},
        "exact_reuse_count": {"type": "INTEGER", "nullable": False, "primary_key": False, "autoincrement": "auto", "default": 0, "server_default": None},
        "reference_count": {"type": "INTEGER", "nullable": False, "primary_key": False, "autoincrement": "auto", "default": 0, "server_default": None},
        "created_at": {"type": "DATETIME", "nullable": False, "primary_key": False, "autoincrement": "auto", "default": None, "server_default": None},
        "updated_at": {"type": "DATETIME", "nullable": False, "primary_key": False, "autoincrement": "auto", "default": None, "server_default": None},
        "last_used_at": {"type": "DATETIME", "nullable": True, "primary_key": False, "autoincrement": "auto", "default": None, "server_default": None},
        "last_referenced_at": {"type": "DATETIME", "nullable": True, "primary_key": False, "autoincrement": "auto", "default": None, "server_default": None},
    }

    init_sql = (ROOT / "scripts" / "init_sqlserver_schema.sql").read_text(encoding="utf-8")
    create_block_match = re.search(
        r"CREATE TABLE translation\.translation_memory_entries \((.*?)\n\s*CONSTRAINT PK_translation_memory_entries",
        init_sql,
        re.DOTALL,
    )
    assert create_block_match is not None
    column_lines = {
        match.group(1): " ".join(match.group(2).strip().rstrip(",").split())
        for match in re.finditer(
            r"^\s*([a-zA-Z_][a-zA-Z0-9_]*)\s+(.+?),?\s*$",
            create_block_match.group(1),
            re.MULTILINE,
        )
    }
    assert tuple(column_lines) == model_columns
    assert column_lines == {
        "id": "int IDENTITY(1,1) NOT NULL",
        "source_text": "nvarchar(max) NOT NULL",
        "source_normalized": "nvarchar(max) NOT NULL",
        "source_hash": "varchar(64) NOT NULL",
        "target_text": "nvarchar(max) NOT NULL",
        "source_lang": "varchar(20) NOT NULL",
        "target_lang": "varchar(20) NOT NULL",
        "document_mode": "varchar(20) NOT NULL",
        "status": "varchar(20) NOT NULL",
        "source": "nvarchar(100) NULL",
        "source_job_id": "varchar(32) NULL",
        "source_metadata_json": "nvarchar(max) NULL",
        "notes": "nvarchar(max) NULL",
        "exact_reuse_count": "int NOT NULL",
        "reference_count": "int NOT NULL",
        "created_at": "datetime2(6) NOT NULL",
        "updated_at": "datetime2(6) NOT NULL",
        "last_used_at": "datetime2(6) NULL",
        "last_referenced_at": "datetime2(6) NULL",
    }
    assert "CONSTRAINT PK_translation_memory_entries PRIMARY KEY CLUSTERED (id)" in init_sql

    init_indexes = {
        match.group(1).lower(): tuple(
            part.strip().split()[0]
            for part in match.group(2).split(",")
        )
        for match in re.finditer(
            r"CREATE INDEX (IX_translation_memory[^ ]+) ON translation\.translation_memory_entries \((.*?)\);",
            init_sql,
        )
    }
    model_indexes = {
        str(index.name).lower(): tuple(expression.name for expression in index.expressions)
        for index in table.indexes
    }
    assert init_indexes == model_indexes
    migration = (ROOT / "migrations" / "versions" / "0004_add_translation_memory_entries.py").read_text(encoding="utf-8")
    assert "TranslationMemoryEntryRecord.__table__" in migration
    assert "table.create" in migration
    assert "index.create" in migration

    db_path = tmp_path / "tm_schema.sqlite"
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ALEMBIC_CONFIG_NAME", "testing")
    cfg = Config(str(ROOT / "alembic.ini"))
    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    migrated_column_info = inspect(engine).get_columns("translation_memory_entries")
    migrated_columns = tuple(column["name"] for column in migrated_column_info)
    migrated_nullable = {column["name"]: bool(column["nullable"]) for column in migrated_column_info}
    model_nullable = {
        column.name: bool(column.nullable)
        for column in table.columns
    }
    migrated_pk = inspect(engine).get_pk_constraint("translation_memory_entries")["constrained_columns"]
    migrated_indexes = {index["name"].lower() for index in inspect(engine).get_indexes("translation_memory_entries")}

    assert migrated_columns == model_columns
    assert migrated_nullable == model_nullable
    assert migrated_pk == ["id"]
    assert set(model_indexes).issubset(migrated_indexes)
