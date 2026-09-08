from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

from app.services import glossary, job_store, state


def _clear_department_glossary() -> None:
    with job_store.session_scope() as session:
        session.query(job_store.GlossaryAuditEventRecord).delete()
        session.query(job_store.DepartmentGlossaryEntryRecord).delete()
        session.query(job_store.DepartmentGlossaryLibraryRecord).delete()


def _run_import_cli(path, *, apply: bool = False, work_id: str | None = None, env: dict[str, str]):
    command = [sys.executable, "scripts/import_department_glossary.py", str(path)]
    if apply:
        command.append("--apply")
    if work_id:
        command.extend(["--work-id", work_id])
    return subprocess.run(
        command,
        cwd=Path(__file__).resolve().parents[1],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )


def _cli_env() -> dict[str, str]:
    env = os.environ.copy()
    env["DATABASE_URL"] = state.DATABASE_URL
    env["DATABASE_SCHEMA"] = job_store.current_database_schema()
    env["AUTO_SCHEMA_MANAGEMENT"] = "true"
    return env


def _detail_payloads(stdout: str) -> list[dict[str, object]]:
    payloads = []
    prefix = "department_glossary_import_detail "
    for line in stdout.splitlines():
        if line.startswith(prefix):
            payloads.append(json.loads(line[len(prefix):]))
    return payloads


def test_department_glossary_import_dry_run_reports_without_writing(app, tmp_path):
    _clear_department_glossary()
    source_path = tmp_path / "glossary.json"
    original_payload = [
        {"cn": "外觀", "en": "Appearance"},
        {"cn": "製程規範", "en": "Process Specification"},
    ]
    source_path.write_text(json.dumps(original_payload, ensure_ascii=False), encoding="utf-8")

    result = _run_import_cli(source_path, env=_cli_env())

    assert result.returncode == 0, result.stderr
    assert "department_glossary_import dry_run=1" in result.stdout
    assert "scanned=2" in result.stdout
    assert "would_create=2" in result.stdout
    assert "created=0" in result.stdout
    assert glossary.list_department_glossary_libraries() == []
    assert json.loads(source_path.read_text(encoding="utf-8")) == original_payload


def test_department_glossary_import_apply_is_idempotent_and_updates_existing(app, tmp_path):
    _clear_department_glossary()
    source_path = tmp_path / "glossary.json"
    source_path.write_text(
        json.dumps(
            [
                {"cn": "外觀", "en": "Appearance"},
                {"cn": "製程規範", "en": "Process Specification"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    first = _run_import_cli(source_path, apply=True, env=_cli_env())
    second = _run_import_cli(source_path, apply=True, env=_cli_env())
    source_path.write_text(
        json.dumps([{"cn": "外觀", "en": "Appearance Characteristics"}], ensure_ascii=False),
        encoding="utf-8",
    )
    third = _run_import_cli(source_path, apply=True, env=_cli_env())

    assert first.returncode == 0, first.stderr
    assert "created=2" in first.stdout
    assert second.returncode == 0, second.stderr
    assert "unchanged=2" in second.stdout
    assert "created=0" in second.stdout
    assert third.returncode == 0, third.stderr
    assert "updated=1" in third.stdout

    libraries = glossary.list_department_glossary_libraries()
    assert len(libraries) == 1
    library = libraries[0]
    assert library.code == glossary.DEFAULT_DEPARTMENT_GLOSSARY_CODE
    assert library.name == "法規文管部"
    assert library.department_code == "法規文管部"
    entries = glossary.list_department_glossary_entries(library.library_id, active_only=True)
    assert len(entries) == 2
    assert {entry.source_term: entry.target_term for entry in entries} == {
        "外觀": "Appearance Characteristics",
        "製程規範": "Process Specification",
    }


def test_department_glossary_import_dry_run_reports_update_and_unchanged(app, tmp_path):
    _clear_department_glossary()
    library = glossary.get_or_create_default_department_glossary()
    glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="外觀",
        target_term="Appearance",
    )
    glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="製程規範",
        target_term="Process Specification",
    )
    source_path = tmp_path / "glossary.json"
    source_path.write_text(
        json.dumps(
            [
                {"cn": "外觀", "en": "Appearance"},
                {"cn": "製程規範", "en": "Manufacturing Process Standard"},
                {"cn": "批號", "en": "Lot No."},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = _run_import_cli(source_path, env=_cli_env())

    assert result.returncode == 0, result.stderr
    assert "dry_run=1" in result.stdout
    assert "unchanged=1" in result.stdout
    assert "would_update=1" in result.stdout
    assert "would_create=1" in result.stdout
    entries = glossary.list_department_glossary_entries(library.library_id, active_only=True)
    assert {entry.source_term: entry.target_term for entry in entries} == {
        "外觀": "Appearance",
        "製程規範": "Process Specification",
    }


def test_department_glossary_import_reports_invalid_and_duplicate_items(app, tmp_path):
    _clear_department_glossary()
    source_path = tmp_path / "glossary.json"
    source_path.write_text(
        json.dumps(
            [
                {"cn": "外觀", "en": "Appearance"},
                {"cn": "外觀", "en": "Appearance Shape"},
                {"cn": "", "en": "Missing Source"},
                {"cn": "缺少英文", "en": ""},
                "not an object",
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    result = _run_import_cli(source_path, env=_cli_env())

    assert result.returncode == 1
    assert "scanned=5" in result.stdout
    assert "would_create=1" in result.stdout
    assert "duplicates=1" in result.stdout
    assert "invalid=3" in result.stdout
    details = _detail_payloads(result.stdout)
    assert {
        (detail["row"], detail["action"], detail["reason"])
        for detail in details
    } >= {
        (3, "duplicate", "duplicate_source_term"),
        (4, "invalid", "missing_source_term"),
        (5, "invalid", "missing_target_term"),
        (6, "invalid", "item_must_be_object"),
    }
    assert glossary.list_department_glossary_libraries() == []


def test_department_glossary_import_apply_records_cli_work_id_in_audit(app, tmp_path):
    _clear_department_glossary()
    source_path = tmp_path / "glossary.json"
    source_path.write_text(
        json.dumps([{"cn": "外觀", "en": "Appearance"}], ensure_ascii=False),
        encoding="utf-8",
    )

    result = _run_import_cli(source_path, apply=True, work_id="CLI99", env=_cli_env())

    assert result.returncode == 0, result.stderr
    events = glossary.list_glossary_audit_events(actor_work_id="CLI99")
    created_targets = {(event["action"], event["target_type"]) for event in events}

    assert ("create", "library") in created_targets
    assert ("create", "entry") in created_targets
