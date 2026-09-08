from __future__ import annotations

import csv
import importlib.util
import json
from pathlib import Path

from app.services import word_batch_runner, word_layout


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("placeholder", encoding="utf-8")


def test_discover_doc_files_recursively_ignores_docx(tmp_path):
    _touch(tmp_path / "a.doc")
    _touch(tmp_path / "nested" / "b.DOC")
    _touch(tmp_path / "nested" / "c.docx")
    _touch(tmp_path / "notes.txt")

    assert [
        path.relative_to(tmp_path).as_posix()
        for path in word_batch_runner.discover_doc_files(tmp_path)
    ] == ["a.doc", "nested/b.DOC"]


def test_output_path_preserves_relative_directories_with_bilingual_suffix(tmp_path):
    source_path = tmp_path / "input" / "dept" / "procedure.doc"
    output_path = word_batch_runner.output_path_for_doc(
        source_path,
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        target_lang="en",
    )

    assert output_path == tmp_path / "output" / "dept" / "procedure_bilingual_en.docx"


def test_run_word_batch_skips_existing_outputs_and_uses_fake_executor(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    _touch(input_dir / "a.doc")
    _touch(input_dir / "nested" / "b.doc")
    existing_output = output_dir / "nested" / "b_bilingual_en.docx"
    _touch(existing_output)
    executed: list[word_batch_runner.WordBatchItem] = []

    def fake_executor(
        item: word_batch_runner.WordBatchItem,
    ) -> word_batch_runner.WordBatchExecutionResult:
        executed.append(item)
        return word_batch_runner.WordBatchExecutionResult(
            status="planned",
            job_id="job-a",
            started_at="2026-09-08T00:00:00+00:00",
            finished_at="2026-09-08T00:00:01+00:00",
        )

    summary = word_batch_runner.run_word_batch(
        input_dir=input_dir,
        output_dir=output_dir,
        model="local-model",
        glossary_library_id=7,
        layout_mode=word_layout.BILINGUAL_BELOW,
        translate_tables=True,
        stage_2_enabled=True,
        executor=fake_executor,
    )

    assert summary.scanned == 2
    assert summary.planned == 1
    assert summary.skipped == 1
    assert len(executed) == 1
    assert executed[0].input_path == input_dir.resolve() / "a.doc"
    assert [row.status for row in summary.rows] == ["planned", "skipped_existing"]


def test_run_word_batch_writes_json_and_csv_reports_when_no_files_processed(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    summary = word_batch_runner.run_word_batch(
        input_dir=input_dir,
        output_dir=tmp_path / "output",
        report_dir=tmp_path / "reports",
        model="local-model",
        glossary_library_id="12",
        stage_2_enabled=True,
    )

    assert summary.scanned == 0
    assert summary.report_json_path.exists()
    assert summary.report_csv_path.exists()
    assert json.loads(summary.report_json_path.read_text(encoding="utf-8")) == []
    with summary.report_csv_path.open(encoding="utf-8-sig", newline="") as csv_file:
        reader = csv.DictReader(csv_file)
        assert reader.fieldnames == [
            "input_path",
            "output_path",
            "status",
            "job_id",
            "error",
            "model",
            "glossary_library_id",
            "layout_mode",
            "translate_tables",
            "stage_2_enabled",
            "started_at",
            "finished_at",
        ]
        assert list(reader) == []


def test_run_word_batch_records_fake_executor_failure(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    _touch(input_dir / "procedure.doc")

    def fake_executor(
        item: word_batch_runner.WordBatchItem,
    ) -> word_batch_runner.WordBatchExecutionResult:
        del item
        raise RuntimeError("local model unavailable")

    summary = word_batch_runner.run_word_batch(
        input_dir=input_dir,
        output_dir=output_dir,
        executor=fake_executor,
    )

    assert summary.failed == 1
    assert summary.rows[0].status == "failed"
    assert summary.rows[0].error == "local model unavailable"
    rows = json.loads(summary.report_json_path.read_text(encoding="utf-8"))
    assert rows[0]["status"] == "failed"


def test_report_content_includes_execution_context(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    _touch(input_dir / "procedure.doc")

    summary = word_batch_runner.run_word_batch(
        input_dir=input_dir,
        output_dir=output_dir,
        source_lang="zh",
        target_lang="en",
        model="local-model",
        glossary_library_id="7",
        translate_tables=False,
        stage_2_enabled=True,
    )

    rows = json.loads(summary.report_json_path.read_text(encoding="utf-8"))
    assert rows == [
        {
            "input_path": str((input_dir / "procedure.doc").resolve()),
            "output_path": str((output_dir / "procedure_bilingual_en.docx").resolve()),
            "status": "planned",
            "job_id": summary.rows[0].job_id,
            "error": "",
            "model": "local-model",
            "glossary_library_id": "7",
            "layout_mode": word_layout.BILINGUAL_BELOW,
            "translate_tables": False,
            "stage_2_enabled": True,
            "started_at": summary.rows[0].started_at,
            "finished_at": summary.rows[0].finished_at,
        }
    ]
    assert summary.rows[0].job_id


def test_cli_entry_point_writes_reports(tmp_path):
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    _touch(input_dir / "procedure.doc")
    script_path = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "word_local_batch_translate.py"
    )
    spec = importlib.util.spec_from_file_location(
        "word_local_batch_translate",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    exit_code = module.main(
        [
            str(input_dir),
            str(output_dir),
            "--model",
            "local-model",
            "--glossary-library-id",
            "7",
            "--stage-2-enabled",
            "true",
        ]
    )

    assert exit_code == 0
    report_path = output_dir / word_batch_runner.DEFAULT_WORD_BATCH_REPORT_JSON
    rows = json.loads(report_path.read_text(encoding="utf-8"))
    assert rows[0]["model"] == "local-model"
    assert rows[0]["glossary_library_id"] == "7"
    assert rows[0]["stage_2_enabled"] is True
