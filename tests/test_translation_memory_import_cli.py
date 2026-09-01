from __future__ import annotations

from pathlib import Path

import pytest
from flask import Flask
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.services import job_store, translation_memory


@pytest.fixture
def tm_cli_app(monkeypatch):
    original_schema = job_store.current_database_schema()
    job_store.configure_database_schema("dbo")
    engine = create_engine("sqlite:///:memory:", future=True)
    job_store.Base.metadata.create_all(bind=engine, checkfirst=True)
    monkeypatch.setattr(job_store, "_engine", engine)
    monkeypatch.setattr(
        job_store,
        "_session_factory",
        sessionmaker(bind=engine, future=True, expire_on_commit=False),
    )

    app = Flask(__name__)
    translation_memory.register_translation_memory_cli(app)
    try:
        yield app
    finally:
        job_store.configure_database_schema(original_schema)


def _write_csv(path: Path, rows: list[dict[str, str]], *, columns: list[str] | None = None) -> None:
    columns = columns or [
        "source_text",
        "target_text",
        "source_lang",
        "target_lang",
        "document_mode",
        "status",
        "notes",
    ]
    lines = [",".join(columns)]
    for row in rows:
        lines.append(",".join(row.get(column, "") for column in columns))
    path.write_text("\n".join(lines), encoding="utf-8")


def test_tm_import_defaults_to_dry_run_without_writing(tm_cli_app, tmp_path):
    csv_path = tmp_path / "tm.csv"
    _write_csv(
        csv_path,
        [
            {
                "source_text": "確認設備是否正常。",
                "target_text": "Confirm whether the equipment is normal.",
                "source_lang": "zh-tw",
                "target_lang": "en",
                "document_mode": "word",
                "status": "approved",
                "notes": "seed",
            }
        ],
    )

    result = tm_cli_app.test_cli_runner().invoke(args=["tm-import", str(csv_path)])

    assert result.exit_code == 0
    assert "dry_run=1" in result.output
    assert "scanned=1" in result.output
    assert "would_create=1" in result.output
    assert translation_memory.find_sql_entry(
        "確認設備是否正常。",
        source_lang="zh-tw",
        target_lang="en",
        document_mode="word",
    ) is None


def test_tm_import_apply_creates_approved_entry(tm_cli_app, tmp_path):
    csv_path = tmp_path / "tm.csv"
    _write_csv(
        csv_path,
        [
            {
                "source_text": "確認設備是否正常。",
                "target_text": "Confirm whether the equipment is normal.",
                "source_lang": "zh-tw",
                "target_lang": "en",
                "document_mode": "word",
                "status": "approved",
                "notes": "seed",
            }
        ],
    )

    result = tm_cli_app.test_cli_runner().invoke(args=["tm-import", str(csv_path), "--apply"])

    assert result.exit_code == 0
    assert "dry_run=0" in result.output
    assert "created=1" in result.output
    entry = translation_memory.find_sql_entry(
        "確認設備是否正常。",
        source_lang="zh-tw",
        target_lang="en",
        document_mode="word",
    )
    assert entry is not None
    assert entry.target_text == "Confirm whether the equipment is normal."
    assert entry.notes == "seed"


def test_tm_import_conflict_skips_without_overwrite(tm_cli_app, tmp_path):
    translation_memory.upsert_sql_entry(
        source_text="確認設備是否正常。",
        target_text="Old approved translation.",
        source_lang="zh-tw",
        target_lang="en",
        document_mode="word",
        status="approved",
    )
    csv_path = tmp_path / "tm.csv"
    _write_csv(
        csv_path,
        [
            {
                "source_text": "確認設備是否正常。",
                "target_text": "New approved translation.",
                "source_lang": "zh-tw",
                "target_lang": "en",
                "document_mode": "word",
                "status": "approved",
            }
        ],
    )

    result = tm_cli_app.test_cli_runner().invoke(args=["tm-import", str(csv_path), "--apply"])

    assert result.exit_code == 0
    assert "created=0" in result.output
    assert "skipped=1" in result.output
    entry = translation_memory.find_sql_entry(
        "確認設備是否正常。",
        source_lang="zh-tw",
        target_lang="en",
        document_mode="word",
    )
    assert entry is not None
    assert entry.target_text == "Old approved translation."


def test_tm_import_overwrite_updates_conflict(tm_cli_app, tmp_path):
    translation_memory.upsert_sql_entry(
        source_text="確認設備是否正常。",
        target_text="Old approved translation.",
        source_lang="zh-tw",
        target_lang="en",
        document_mode="word",
        status="approved",
    )
    csv_path = tmp_path / "tm.csv"
    _write_csv(
        csv_path,
        [
            {
                "source_text": "確認設備是否正常。",
                "target_text": "New approved translation.",
                "source_lang": "zh-tw",
                "target_lang": "en",
                "document_mode": "word",
                "status": "approved",
            }
        ],
    )

    result = tm_cli_app.test_cli_runner().invoke(
        args=["tm-import", str(csv_path), "--apply", "--overwrite"]
    )

    assert result.exit_code == 0
    assert "updated=1" in result.output
    entry = translation_memory.find_sql_entry(
        "確認設備是否正常。",
        source_lang="zh-tw",
        target_lang="en",
        document_mode="word",
    )
    assert entry is not None
    assert entry.target_text == "New approved translation."


def test_tm_import_rejects_missing_required_columns(tm_cli_app, tmp_path):
    csv_path = tmp_path / "tm.csv"
    _write_csv(
        csv_path,
        [
            {
                "source_text": "確認設備是否正常。",
                "target_text": "Confirm whether the equipment is normal.",
                "source_lang": "zh-tw",
                "target_lang": "en",
                "status": "approved",
            }
        ],
        columns=["source_text", "target_text", "source_lang", "target_lang", "status"],
    )

    result = tm_cli_app.test_cli_runner().invoke(args=["tm-import", str(csv_path), "--apply"])

    assert result.exit_code != 0
    assert "missing required CSV columns" in result.output
    assert "document_mode" in result.output


def test_tm_import_only_accepts_approved_status(tm_cli_app, tmp_path):
    csv_path = tmp_path / "tm.csv"
    _write_csv(
        csv_path,
        [
            {
                "source_text": "確認設備是否正常。",
                "target_text": "Confirm whether the equipment is normal.",
                "source_lang": "zh-tw",
                "target_lang": "en",
                "document_mode": "word",
                "status": "disabled",
            }
        ],
    )

    result = tm_cli_app.test_cli_runner().invoke(args=["tm-import", str(csv_path), "--apply"])

    assert result.exit_code != 0
    assert "errors=1" in result.output
    assert "status_must_be_approved" in result.output
    assert translation_memory.find_sql_entry(
        "確認設備是否正常。",
        source_lang="zh-tw",
        target_lang="en",
        document_mode="word",
    ) is None


def test_tm_import_reports_unsupported_status(tm_cli_app, tmp_path):
    csv_path = tmp_path / "tm.csv"
    _write_csv(
        csv_path,
        [
            {
                "source_text": "確認設備是否異常。",
                "target_text": "Confirm whether the equipment is abnormal.",
                "source_lang": "zh-tw",
                "target_lang": "en",
                "document_mode": "word",
                "status": "draft",
            }
        ],
    )

    result = tm_cli_app.test_cli_runner().invoke(args=["tm-import", str(csv_path)])

    assert result.exit_code != 0
    assert "errors=1" in result.output
    assert "unsupported_status" in result.output
