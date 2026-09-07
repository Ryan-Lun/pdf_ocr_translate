from __future__ import annotations

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect

from app.services import glossary, job_store, schema_control


ROOT = Path(__file__).resolve().parents[1]


def _clear_department_glossary() -> None:
    with job_store.session_scope() as session:
        session.query(job_store.DepartmentGlossaryEntryRecord).delete()
        session.query(job_store.DepartmentGlossaryLibraryRecord).delete()


def test_department_glossary_creates_default_regulatory_document_control_library(app):
    _clear_department_glossary()

    library = glossary.get_or_create_default_department_glossary()
    same_library = glossary.get_or_create_default_department_glossary()

    assert same_library.library_id == library.library_id
    assert library.code == glossary.DEFAULT_DEPARTMENT_GLOSSARY_CODE
    assert library.name == "法規文管部"
    assert library.department_code == "法規文管部"
    assert library.is_default is True
    assert library.is_active is True


def test_department_glossary_lists_only_active_entries_for_translation(app):
    _clear_department_glossary()
    library = glossary.get_or_create_default_department_glossary()
    active_id = glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh-TW",
        target_lang="English",
        source_term="製程規範",
        target_term="Process Specification",
        created_by_work_id="NE025",
    )
    disabled_id = glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="外觀",
        target_term="Appearance",
        status="disabled",
    )

    all_entries = glossary.list_department_glossary_entries(library.library_id)
    active_entries = glossary.list_department_glossary_entries(
        library.library_id,
        active_only=True,
    )

    assert [entry.entry_id for entry in all_entries] == [active_id, disabled_id]
    assert [entry.entry_id for entry in active_entries] == [active_id]
    assert glossary.load_department_glossary_pairs(library.library_id) == [
        ("製程規範", "Process Specification")
    ]


def test_department_glossary_upsert_keeps_one_active_entry_per_term(app):
    _clear_department_glossary()
    library = glossary.get_or_create_default_department_glossary()

    first_id = glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh-TW",
        target_lang="en",
        source_term="外觀",
        target_term="Appearance",
    )
    second_id = glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh",
        target_lang="English",
        source_term="外觀",
        target_term="Appearance Characteristics",
        updated_by_work_id="NE025",
    )

    entries = glossary.list_department_glossary_entries(
        library.library_id,
        active_only=True,
    )

    assert second_id == first_id
    assert len(entries) == 1
    assert entries[0].target_term == "Appearance Characteristics"
    assert entries[0].updated_by_work_id == "NE025"


def test_department_glossary_disable_entry_removes_it_from_effective_pairs(app):
    _clear_department_glossary()
    library = glossary.get_or_create_default_department_glossary()
    entry_id = glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="外觀",
        target_term="Appearance",
    )

    assert glossary.disable_department_glossary_entry(entry_id, updated_by_work_id="NE025") is True

    entries = glossary.list_department_glossary_entries(library.library_id)
    assert entries[0].status == glossary.STATUS_DISABLED
    assert entries[0].updated_by_work_id == "NE025"
    assert glossary.load_department_glossary_pairs(library.library_id) == []


def test_different_department_glossaries_can_define_same_source_term(app):
    _clear_department_glossary()
    regulatory = glossary.get_or_create_department_glossary_library(
        code="regulatory-document-control",
        name="法規文管部",
        department_code="法規文管部",
        is_default=True,
    )
    quality = glossary.get_or_create_department_glossary_library(
        code="quality-assurance",
        name="品保部",
        department_code="品保部",
    )

    regulatory_id = glossary.upsert_department_glossary_entry(
        library_id=regulatory.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="製程規範",
        target_term="Process Specification",
    )
    quality_id = glossary.upsert_department_glossary_entry(
        library_id=quality.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="製程規範",
        target_term="Manufacturing Process Standard",
    )

    assert quality_id != regulatory_id
    assert glossary.load_department_glossary_pairs(regulatory.library_id) == [
        ("製程規範", "Process Specification")
    ]
    assert glossary.load_department_glossary_pairs(quality.library_id) == [
        ("製程規範", "Manufacturing Process Standard")
    ]


def test_department_glossary_pairs_preserve_longest_match_order(app):
    _clear_department_glossary()
    library = glossary.get_or_create_default_department_glossary()
    glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="規範",
        target_term="Specification",
    )
    glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="製程規範",
        target_term="Process Specification",
    )

    assert glossary.load_department_glossary_pairs(library.library_id) == [
        ("製程規範", "Process Specification"),
        ("規範", "Specification"),
    ]


def test_combined_glossary_can_load_selected_department_library(app):
    _clear_department_glossary()
    regulatory = glossary.get_or_create_default_department_glossary()
    quality = glossary.get_or_create_department_glossary_library(
        code="quality-assurance",
        name="品保部",
        department_code="品保部",
    )
    glossary.upsert_department_glossary_entry(
        library_id=regulatory.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="製程規範",
        target_term="Process Specification",
    )
    glossary.upsert_department_glossary_entry(
        library_id=quality.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="製程規範",
        target_term="Manufacturing Process Standard",
    )

    assert glossary.load_combined_glossary() == [("製程規範", "Process Specification")]
    assert glossary.load_combined_glossary(quality.library_id) == [
        ("製程規範", "Manufacturing Process Standard")
    ]


def test_combined_glossary_rejects_invalid_translation_glossary_source(app, monkeypatch):
    _clear_department_glossary()
    monkeypatch.setattr(glossary.state, "TRANSLATION_GLOSSARY_SOURCE", "ssql")

    try:
        glossary.load_combined_glossary()
    except ValueError as exc:
        assert "TRANSLATION_GLOSSARY_SOURCE" in str(exc)
        assert "sql" in str(exc)
        assert "json" in str(exc)
    else:
        raise AssertionError("invalid translation glossary source must fail explicitly")


def test_sql_combined_glossary_feeds_required_term_wrapper_with_longest_match(app):
    _clear_department_glossary()
    library = glossary.get_or_create_default_department_glossary()
    glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="規範",
        target_term="Specification",
    )
    glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="製程規範",
        target_term="Process Specification",
    )

    application = glossary.apply_required_glossary_terms(
        "確認製程規範與規範。",
        glossary.load_combined_glossary(),
        source_lang="zh",
        target_lang="en",
    )

    assert application.text == (
        '確認<term id="0001">Process Specification</term>與'
        '<term id="0002">Specification</term>。'
    )
    assert [term.target for term in application.required_terms] == [
        "Process Specification",
        "Specification",
    ]


def test_combined_glossary_defaults_to_sql_department_glossary(app, tmp_path, monkeypatch):
    _clear_department_glossary()
    library = glossary.get_or_create_default_department_glossary()
    glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="批號",
        target_term="SQL Lot No.",
    )
    system_path = tmp_path / "system.json"
    global_path = tmp_path / "global.json"
    system_path.write_text(
        '[{"cn":"批號","en":"JSON Lot No."}]',
        encoding="utf-8",
    )
    global_path.write_text(
        '[{"cn":"外觀","en":"JSON Appearance"}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(glossary.state, "SYSTEM_GLOSSARY_PATH", str(system_path))
    monkeypatch.setattr(glossary.state, "GLOBAL_GLOSSARY_PATH", str(global_path))
    glossary.invalidate_glossary_cache()

    assert glossary.load_combined_glossary() == [("批號", "SQL Lot No.")]


def test_json_backed_combined_glossary_requires_explicit_legacy_mode(app, tmp_path, monkeypatch):
    _clear_department_glossary()
    system_path = tmp_path / "system.json"
    global_path = tmp_path / "global.json"
    system_path.write_text(
        '[{"cn":"批號","en":"Lot No."}]',
        encoding="utf-8",
    )
    global_path.write_text(
        '[{"cn":"批號","en":"Batch No."}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(glossary.state, "SYSTEM_GLOSSARY_PATH", str(system_path))
    monkeypatch.setattr(glossary.state, "GLOBAL_GLOSSARY_PATH", str(global_path))
    monkeypatch.setattr(glossary.state, "TRANSLATION_GLOSSARY_SOURCE", "json")
    glossary.invalidate_glossary_cache()

    assert glossary.load_combined_glossary() == [("批號", "Batch No.")]


def test_department_glossary_schema_migration_and_sql_init_stay_aligned(monkeypatch, tmp_path):
    library_table = job_store.DepartmentGlossaryLibraryRecord.__table__
    entry_table = job_store.DepartmentGlossaryEntryRecord.__table__

    assert schema_control.REQUIRED_COLUMNS["department_glossary_libraries"] == tuple(library_table.columns.keys())
    assert schema_control.REQUIRED_COLUMNS["department_glossary_entries"] == tuple(entry_table.columns.keys())
    assert schema_control.SCHEMA_GROUPS["department_glossary"] == (
        "department_glossary_libraries",
        "department_glossary_entries",
    )

    init_sql = (ROOT / "scripts" / "init_sqlserver_schema.sql").read_text(encoding="utf-8")
    assert "CREATE TABLE translation.department_glossary_libraries" in init_sql
    assert "CREATE TABLE translation.department_glossary_entries" in init_sql
    assert "IX_department_glossary_libraries_code" in init_sql
    assert "IX_department_glossary_entries_lookup" in init_sql
    assert "IX_department_glossary_entries_term" in init_sql
    assert "UQ_department_glossary_entries_term_status" in init_sql
    assert "FK_department_glossary_entries_libraries" in init_sql

    migration = (ROOT / "migrations" / "versions" / "0005_add_department_glossary.py").read_text(encoding="utf-8")
    assert "DepartmentGlossaryLibraryRecord.__table__" in migration
    assert "DepartmentGlossaryEntryRecord.__table__" in migration
    assert "table.create" in migration
    assert "index.create" in migration

    db_path = tmp_path / "department_glossary_schema.sqlite"
    monkeypatch.setenv("ALEMBIC_DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("ALEMBIC_CONFIG_NAME", "testing")
    cfg = Config(str(ROOT / "alembic.ini"))
    command.upgrade(cfg, "head")

    engine = create_engine(f"sqlite:///{db_path}")
    inspector = inspect(engine)
    assert tuple(column["name"] for column in inspector.get_columns("department_glossary_libraries")) == tuple(library_table.columns.keys())
    assert tuple(column["name"] for column in inspector.get_columns("department_glossary_entries")) == tuple(entry_table.columns.keys())
    migrated_indexes = {
        index["name"].lower()
        for table_name in ("department_glossary_libraries", "department_glossary_entries")
        for index in inspector.get_indexes(table_name)
    }
    expected_indexes = {
        str(index.name).lower()
        for table in (library_table, entry_table)
        for index in table.indexes
    }
    assert expected_indexes.issubset(migrated_indexes)

    foreign_keys = inspector.get_foreign_keys("department_glossary_entries")
    assert foreign_keys[0]["referred_table"] == "department_glossary_libraries"
    unique_constraints = {
        constraint["name"]: tuple(constraint["column_names"])
        for constraint in inspector.get_unique_constraints("department_glossary_entries")
    }
    assert unique_constraints["UQ_department_glossary_entries_term_status"] == (
        "library_id",
        "source_lang",
        "target_lang",
        "source_term",
        "status",
    )

