from __future__ import annotations

import csv
import importlib.util
import json
import os
from pathlib import Path

import pytest

from app.services import glossary, state, word_batch_runner, word_layout


def _touch(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("placeholder", encoding="utf-8")


def _fake_glossary_resolver(*args, **kwargs):
    del args, kwargs
    return glossary.SelectedDepartmentGlossary(
        library_id=7,
        code="quality-assurance",
        name="品保部",
        department_code="QA",
        is_active=True,
        entry_count=3,
    )


def _fake_smoke_tester(
    config: word_batch_runner.LocalModelConfig,
    *,
    stage_2_enabled: bool,
) -> word_batch_runner.WordBatchSmokeResult:
    assert config.base_url == "http://localhost:8000/v1"
    assert config.api_key == "local-key"
    assert config.model == "local-model"
    return word_batch_runner.WordBatchSmokeResult(
        ok=True,
        stage_1_checked=True,
        stage_2_checked=stage_2_enabled,
    )


def _load_word_batch_cli_module():
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
    return module


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
        local_model_base_url="http://localhost:8000/v1/",
        local_model_api_key="local-key",
        glossary_library_id=7,
        layout_mode=word_layout.BILINGUAL_BELOW,
        translate_tables=True,
        stage_2_enabled=True,
        executor=fake_executor,
        glossary_resolver=_fake_glossary_resolver,
        smoke_tester=_fake_smoke_tester,
    )

    assert summary.scanned == 2
    assert summary.planned == 1
    assert summary.skipped == 1
    assert len(executed) == 1
    assert executed[0].input_path == input_dir.resolve() / "a.doc"
    assert executed[0].model == "local-model"
    assert executed[0].local_model_base_url == "http://localhost:8000/v1"
    assert executed[0].local_model_api_key == "local-key"
    assert [row.status for row in summary.rows] == ["planned", "skipped_existing"]


def test_run_word_batch_writes_json_and_csv_reports_when_no_files_processed(tmp_path):
    input_dir = tmp_path / "input"
    input_dir.mkdir()

    summary = word_batch_runner.run_word_batch(
        input_dir=input_dir,
        output_dir=tmp_path / "output",
        report_dir=tmp_path / "reports",
        model="local-model",
        local_model_base_url="http://localhost:8000/v1",
        local_model_api_key="local-key",
        glossary_library_id="12",
        stage_2_enabled=True,
        glossary_resolver=_fake_glossary_resolver,
        smoke_tester=_fake_smoke_tester,
    )

    assert summary.scanned == 0
    assert summary.report_json_path.exists()
    assert summary.report_csv_path.exists()
    report = json.loads(summary.report_json_path.read_text(encoding="utf-8"))
    assert report["preflight"]["smoke_test"] == {
        "ok": True,
        "stage_1_checked": True,
        "stage_2_checked": True,
        "error": "",
    }
    assert report["rows"] == []
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
            "glossary_code",
            "glossary_name",
            "glossary_department_code",
            "glossary_is_active",
            "glossary_entry_count",
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
        model="local-model",
        local_model_base_url="http://localhost:8000/v1",
        local_model_api_key="local-key",
        executor=fake_executor,
        glossary_resolver=_fake_glossary_resolver,
        smoke_tester=_fake_smoke_tester,
    )

    assert summary.failed == 1
    assert summary.rows[0].status == "failed"
    assert summary.rows[0].error == "local model unavailable"
    report = json.loads(summary.report_json_path.read_text(encoding="utf-8"))
    assert report["rows"][0]["status"] == "failed"


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
        local_model_base_url="http://localhost:8000/v1",
        local_model_api_key="local-key",
        glossary_library_id="7",
        translate_tables=False,
        stage_2_enabled=True,
        executor=word_batch_runner.PlanningWordBatchExecutor(),
        glossary_resolver=_fake_glossary_resolver,
        smoke_tester=_fake_smoke_tester,
    )

    report_text = summary.report_json_path.read_text(encoding="utf-8")
    assert "local-key" not in report_text
    assert "local_model_api_key" not in report_text
    report = json.loads(report_text)
    rows = report["rows"]
    assert rows == [
        {
            "input_path": str((input_dir / "procedure.doc").resolve()),
            "output_path": str((output_dir / "procedure_bilingual_en.docx").resolve()),
            "status": "planned",
            "job_id": summary.rows[0].job_id,
            "error": "",
            "model": "local-model",
            "glossary_library_id": "7",
            "glossary_code": "quality-assurance",
            "glossary_name": "品保部",
            "glossary_department_code": "QA",
            "glossary_is_active": True,
            "glossary_entry_count": 3,
            "layout_mode": word_layout.BILINGUAL_BELOW,
            "translate_tables": False,
            "stage_2_enabled": True,
            "started_at": summary.rows[0].started_at,
            "finished_at": summary.rows[0].finished_at,
        }
    ]
    assert summary.rows[0].job_id


def test_cli_entry_point_writes_reports(app, tmp_path):
    library = glossary.get_or_create_department_glossary_library(
        code="cli-quality-assurance",
        name="品保部",
        department_code="QA",
    )
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    _touch(input_dir / "procedure.doc")
    module = _load_word_batch_cli_module()

    exit_code = module.main(
        [
            str(input_dir),
            str(output_dir),
            "--base-url",
            "http://localhost:8000/v1",
            "--api-key",
            "local-key",
            "--model",
            "local-model",
            "--glossary-library-id",
            str(library.library_id),
            "--stage-2-enabled",
            "true",
        ],
        init_database=False,
        smoke_tester=_fake_smoke_tester,
        executor=word_batch_runner.PlanningWordBatchExecutor(),
    )

    assert exit_code == 0
    report_path = output_dir / word_batch_runner.DEFAULT_WORD_BATCH_REPORT_JSON
    report = json.loads(report_path.read_text(encoding="utf-8"))
    rows = report["rows"]
    assert rows[0]["model"] == "local-model"
    assert rows[0]["glossary_library_id"] == str(library.library_id)
    assert rows[0]["glossary_code"] == "cli-quality-assurance"
    assert rows[0]["glossary_name"] == "品保部"
    assert rows[0]["glossary_department_code"] == "QA"
    assert rows[0]["glossary_is_active"] is True
    assert rows[0]["glossary_entry_count"] == 0
    assert rows[0]["stage_2_enabled"] is True


def test_word_batch_requires_selected_department_glossary_id(app, tmp_path):
    input_dir = tmp_path / "input"
    _touch(input_dir / "procedure.doc")
    executed = False

    def fake_executor(
        item: word_batch_runner.WordBatchItem,
    ) -> word_batch_runner.WordBatchExecutionResult:
        nonlocal executed
        executed = True
        return word_batch_runner.WordBatchExecutionResult(status="planned")

    try:
        word_batch_runner.run_word_batch(
            input_dir=input_dir,
            output_dir=tmp_path / "output",
            glossary_library_id="",
            executor=fake_executor,
        )
    except glossary.DepartmentGlossarySelectionError as exc:
        assert exc.code == "missing_department_glossary"
    else:
        raise AssertionError("missing glossary library id must fail preflight")
    assert executed is False


def test_word_batch_rejects_unknown_department_glossary_before_execution(app, tmp_path):
    input_dir = tmp_path / "input"
    _touch(input_dir / "procedure.doc")
    executed = False

    def fake_executor(
        item: word_batch_runner.WordBatchItem,
    ) -> word_batch_runner.WordBatchExecutionResult:
        nonlocal executed
        executed = True
        return word_batch_runner.WordBatchExecutionResult(status="planned")

    try:
        word_batch_runner.run_word_batch(
            input_dir=input_dir,
            output_dir=tmp_path / "output",
            glossary_library_id="999999",
            executor=fake_executor,
        )
    except glossary.DepartmentGlossarySelectionError as exc:
        assert exc.code == "department_glossary_not_found"
    else:
        raise AssertionError("unknown glossary library id must fail preflight")
    assert executed is False


def test_word_batch_rejects_inactive_department_glossary_before_execution(app, tmp_path):
    library = glossary.get_or_create_department_glossary_library(
        code="inactive-batch",
        name="停用部門",
        department_code="OFF",
        is_active=False,
    )
    input_dir = tmp_path / "input"
    _touch(input_dir / "procedure.doc")
    executed = False

    def fake_executor(
        item: word_batch_runner.WordBatchItem,
    ) -> word_batch_runner.WordBatchExecutionResult:
        nonlocal executed
        executed = True
        return word_batch_runner.WordBatchExecutionResult(status="planned")

    try:
        word_batch_runner.run_word_batch(
            input_dir=input_dir,
            output_dir=tmp_path / "output",
            glossary_library_id=library.library_id,
            executor=fake_executor,
        )
    except glossary.DepartmentGlossarySelectionError as exc:
        assert exc.code == "department_glossary_inactive"
    else:
        raise AssertionError("inactive glossary library id must fail preflight")
    assert executed is False


def test_word_batch_valid_department_glossary_allows_execution_and_reports_metadata(app, tmp_path):
    library = glossary.get_or_create_department_glossary_library(
        code="quality-assurance",
        name="品保部",
        department_code="QA",
    )
    glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="外觀",
        target_term="Appearance",
    )
    input_dir = tmp_path / "input"
    _touch(input_dir / "procedure.doc")
    executed: list[word_batch_runner.WordBatchItem] = []

    def fake_executor(
        item: word_batch_runner.WordBatchItem,
    ) -> word_batch_runner.WordBatchExecutionResult:
        executed.append(item)
        return word_batch_runner.WordBatchExecutionResult(status="planned", job_id="job-1")

    summary = word_batch_runner.run_word_batch(
        input_dir=input_dir,
        output_dir=tmp_path / "output",
        model="local-model",
        local_model_base_url="http://localhost:8000/v1",
        local_model_api_key="local-key",
        glossary_library_id=str(library.library_id),
        executor=fake_executor,
        smoke_tester=_fake_smoke_tester,
    )

    assert len(executed) == 1
    assert executed[0].glossary_library_id == str(library.library_id)
    assert summary.glossary == word_batch_runner.WordBatchGlossaryMetadata(
        library_id=library.library_id,
        code="quality-assurance",
        name="品保部",
        department_code="QA",
        is_active=True,
        entry_count=1,
    )
    report = json.loads(summary.report_json_path.read_text(encoding="utf-8"))
    assert report["preflight"]["glossary"] == {
        "library_id": library.library_id,
        "code": "quality-assurance",
        "name": "品保部",
        "department_code": "QA",
        "is_active": True,
        "entry_count": 1,
    }
    assert report["rows"][0]["glossary_library_id"] == str(library.library_id)
    assert report["rows"][0]["glossary_code"] == "quality-assurance"
    assert report["rows"][0]["glossary_name"] == "品保部"
    assert report["rows"][0]["glossary_department_code"] == "QA"
    assert report["rows"][0]["glossary_is_active"] is True
    assert report["rows"][0]["glossary_entry_count"] == 1



def test_local_model_smoke_uses_larger_token_budget_for_reasoning_models():
    requests: list[dict[str, object]] = []

    class _Completions:
        def create(self, **kwargs):
            requests.append(kwargs)
            message = type("Message", (), {"content": "OK"})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    word_batch_runner._smoke_chat_completion(
        _Client(),
        model="local-model",
        messages=[{"role": "user", "content": "Return exactly: OK"}],
    )

    assert requests[0]["max_tokens"] == 512
    assert requests[0]["extra_body"] == word_batch_runner.LOCAL_MODEL_DISABLE_THINKING_EXTRA_BODY

def test_word_batch_smoke_test_runs_before_execution(app, tmp_path):
    library = glossary.get_or_create_department_glossary_library(
        code="smoke-success",
        name="品保部",
        department_code="QA",
    )
    input_dir = tmp_path / "input"
    _touch(input_dir / "procedure.doc")
    calls: list[str] = []

    def smoke_tester(
        config: word_batch_runner.LocalModelConfig,
        *,
        stage_2_enabled: bool,
    ) -> word_batch_runner.WordBatchSmokeResult:
        calls.append(f"smoke:{config.model}:{stage_2_enabled}")
        return word_batch_runner.WordBatchSmokeResult(
            ok=True,
            stage_1_checked=True,
            stage_2_checked=True,
        )

    def fake_executor(
        item: word_batch_runner.WordBatchItem,
    ) -> word_batch_runner.WordBatchExecutionResult:
        del item
        calls.append("execute")
        return word_batch_runner.WordBatchExecutionResult(status="planned")

    summary = word_batch_runner.run_word_batch(
        input_dir=input_dir,
        output_dir=tmp_path / "output",
        model="local-model",
        local_model_base_url="http://localhost:8000/v1",
        local_model_api_key="local-key",
        glossary_library_id=library.library_id,
        executor=fake_executor,
        smoke_tester=smoke_tester,
    )

    assert calls == ["smoke:local-model:True", "execute"]
    assert summary.smoke_test.stage_1_checked is True
    assert summary.smoke_test.stage_2_checked is True


def test_word_batch_stage_1_smoke_failure_stops_before_execution(app, tmp_path):
    library = glossary.get_or_create_department_glossary_library(
        code="smoke-stage-1-failure",
        name="品保部",
        department_code="QA",
    )
    input_dir = tmp_path / "input"
    _touch(input_dir / "procedure.doc")
    executed = False

    def smoke_tester(
        config: word_batch_runner.LocalModelConfig,
        *,
        stage_2_enabled: bool,
    ) -> word_batch_runner.WordBatchSmokeResult:
        del config, stage_2_enabled
        return word_batch_runner.WordBatchSmokeResult(
            ok=False,
            stage_1_checked=True,
            stage_2_checked=False,
            error="stage 1 unavailable",
        )

    def fake_executor(
        item: word_batch_runner.WordBatchItem,
    ) -> word_batch_runner.WordBatchExecutionResult:
        nonlocal executed
        del item
        executed = True
        return word_batch_runner.WordBatchExecutionResult(status="planned")

    try:
        word_batch_runner.run_word_batch(
            input_dir=input_dir,
            output_dir=tmp_path / "output",
            model="local-model",
            local_model_base_url="http://localhost:8000/v1",
            local_model_api_key="local-key",
            glossary_library_id=library.library_id,
            executor=fake_executor,
            smoke_tester=smoke_tester,
        )
    except RuntimeError as exc:
        assert "stage 1 unavailable" in str(exc)
    else:
        raise AssertionError("stage 1 smoke failure must stop the batch")
    assert executed is False


def test_word_batch_stage_2_smoke_failure_stops_before_execution(app, tmp_path):
    library = glossary.get_or_create_department_glossary_library(
        code="smoke-stage-2-failure",
        name="品保部",
        department_code="QA",
    )
    input_dir = tmp_path / "input"
    _touch(input_dir / "procedure.doc")
    executed = False

    def smoke_tester(
        config: word_batch_runner.LocalModelConfig,
        *,
        stage_2_enabled: bool,
    ) -> word_batch_runner.WordBatchSmokeResult:
        del config
        assert stage_2_enabled is True
        return word_batch_runner.WordBatchSmokeResult(
            ok=False,
            stage_1_checked=True,
            stage_2_checked=True,
            error="stage 2 unavailable",
        )

    def fake_executor(
        item: word_batch_runner.WordBatchItem,
    ) -> word_batch_runner.WordBatchExecutionResult:
        nonlocal executed
        del item
        executed = True
        return word_batch_runner.WordBatchExecutionResult(status="planned")

    try:
        word_batch_runner.run_word_batch(
            input_dir=input_dir,
            output_dir=tmp_path / "output",
            model="local-model",
            local_model_base_url="http://localhost:8000/v1",
            local_model_api_key="local-key",
            glossary_library_id=library.library_id,
            executor=fake_executor,
            smoke_tester=smoke_tester,
        )
    except RuntimeError as exc:
        assert "stage 2 unavailable" in str(exc)
    else:
        raise AssertionError("stage 2 smoke failure must stop the batch")
    assert executed is False


def test_word_batch_stage_2_can_be_disabled_for_smoke_test(app, tmp_path):
    library = glossary.get_or_create_department_glossary_library(
        code="smoke-stage-2-disabled",
        name="品保部",
        department_code="QA",
    )
    input_dir = tmp_path / "input"
    _touch(input_dir / "procedure.doc")
    captured_stage_2: list[bool] = []

    def smoke_tester(
        config: word_batch_runner.LocalModelConfig,
        *,
        stage_2_enabled: bool,
    ) -> word_batch_runner.WordBatchSmokeResult:
        del config
        captured_stage_2.append(stage_2_enabled)
        return word_batch_runner.WordBatchSmokeResult(
            ok=True,
            stage_1_checked=True,
            stage_2_checked=stage_2_enabled,
        )

    summary = word_batch_runner.run_word_batch(
        input_dir=input_dir,
        output_dir=tmp_path / "output",
        model="local-model",
        local_model_base_url="http://localhost:8000/v1",
        local_model_api_key="local-key",
        glossary_library_id=library.library_id,
        stage_2_enabled=False,
        executor=word_batch_runner.PlanningWordBatchExecutor(),
        smoke_tester=smoke_tester,
    )

    assert captured_stage_2 == [False]
    assert summary.rows[0].stage_2_enabled is False
    assert summary.smoke_test.stage_1_checked is True
    assert summary.smoke_test.stage_2_checked is False


def test_word_batch_local_model_config_does_not_mutate_environment(app, tmp_path, monkeypatch):
    library = glossary.get_or_create_department_glossary_library(
        code="smoke-env",
        name="品保部",
        department_code="QA",
    )
    monkeypatch.setenv("OPENAI_BASE_URL", "https://production.example/openai/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "production-key")
    input_dir = tmp_path / "input"
    _touch(input_dir / "procedure.doc")

    word_batch_runner.run_word_batch(
        input_dir=input_dir,
        output_dir=tmp_path / "output",
        model="local-model",
        local_model_base_url="http://localhost:8000/v1",
        local_model_api_key="local-key",
        glossary_library_id=library.library_id,
        executor=word_batch_runner.PlanningWordBatchExecutor(),
        smoke_tester=_fake_smoke_tester,
    )

    assert os.environ["OPENAI_BASE_URL"] == "https://production.example/openai/v1"
    assert os.environ["OPENAI_API_KEY"] == "production-key"


def test_word_batch_missing_input_dir_stops_before_smoke(app, tmp_path):
    library = glossary.get_or_create_department_glossary_library(
        code="smoke-input-dir",
        name="品保部",
        department_code="QA",
    )
    calls = []

    def smoke_tester(
        config: word_batch_runner.LocalModelConfig,
        *,
        stage_2_enabled: bool,
    ) -> word_batch_runner.WordBatchSmokeResult:
        del config, stage_2_enabled
        calls.append("smoke")
        return word_batch_runner.WordBatchSmokeResult(ok=True, stage_1_checked=True)

    with pytest.raises(NotADirectoryError):
        word_batch_runner.run_word_batch(
            input_dir=tmp_path / "missing",
            output_dir=tmp_path / "output",
            model="local-model",
            local_model_base_url="http://localhost:8000/v1",
            local_model_api_key="local-key",
            glossary_library_id=library.library_id,
            smoke_tester=smoke_tester,
        )

    assert calls == []

def test_synchronous_word_pipeline_executor_passes_expected_job_configuration(
    app, tmp_path, monkeypatch
):
    monkeypatch.setattr(state, "WORD_TRANSLATE_JOB_ROOT", tmp_path / "word_jobs")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://production.example/openai/v1")
    monkeypatch.setenv("OPENAI_API_KEY", "production-key")
    library = glossary.get_or_create_department_glossary_library(
        code="sync-pipeline",
        name="品保部",
        department_code="QA",
    )
    glossary.upsert_department_glossary_entry(
        library_id=library.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="外觀",
        target_term="Appearance",
    )
    input_dir = tmp_path / "input"
    _touch(input_dir / "nested" / "procedure.doc")
    captured: dict[str, object] = {}

    def fake_run_word_translate_job(**kwargs):
        captured.update(kwargs)
        job_dir = kwargs["job_dir"]
        meta = word_batch_runner.jobs.load_job_meta(job_dir) or {}
        captured["department_glossary_library_id"] = meta.get(
            "department_glossary_library_id"
        )
        processing_source_path = kwargs["processing_source_path"]
        processing_source_path.write_bytes(b"converted docx")
        job_dir = kwargs["job_dir"]
        output_path = kwargs["output_path"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"translated docx")
        word_batch_runner.jobs.set_job_state(
            job_dir,
            status="completed",
            stage="completed",
            progress=100.0,
        )
        word_batch_runner.jobs.set_job_state(
            job_dir,
            status="completed",
            stage="completed",
            progress=100.0,
        )

    monkeypatch.setattr(
        word_batch_runner.word_translate,
        "run_word_translate_job",
        fake_run_word_translate_job,
    )

    summary = word_batch_runner.run_word_batch(
        input_dir=input_dir,
        output_dir=tmp_path / "output",
        model="local-model",
        local_model_base_url="http://localhost:8000/v1",
        local_model_api_key="local-key",
        glossary_library_id=library.library_id,
        translate_tables=False,
        stage_2_enabled=True,
        smoke_tester=_fake_smoke_tester,
    )

    row = summary.rows[0]
    assert row.status == "completed"
    assert row.job_id
    assert row.output_path == str(
        (tmp_path / "output" / "nested" / "procedure_bilingual_en.docx").resolve()
    )
    assert Path(row.output_path).read_bytes() == b"translated docx"
    assert captured["source_lang"] == "auto"
    assert captured["target_lang"] == "en"
    assert captured["layout_mode"] == word_layout.BILINGUAL_BELOW
    assert captured["translate_tables"] is False
    assert captured["stage_2_enabled"] is True
    assert captured["translation_model"] == "local-model"
    assert captured["local_model_base_url"] == "http://localhost:8000/v1"
    assert captured["local_model_api_key"] == "local-key"
    assert captured["request_extra_body"] == word_batch_runner.LOCAL_MODEL_DISABLE_THINKING_EXTRA_BODY
    assert captured["department_glossary_library_id"] == library.library_id
    assert captured["source_path"].suffix == ".doc"
    assert captured["processing_source_path"].name == "procedure.converted.docx"
    assert captured["processing_source_path"].exists()
    assert captured["output_path"].name == "output.docx"
    assert os.environ["OPENAI_BASE_URL"] == "https://production.example/openai/v1"
    assert os.environ["OPENAI_API_KEY"] == "production-key"


def test_cli_entry_point_uses_synchronous_executor_by_default(app, tmp_path, monkeypatch):
    library = glossary.get_or_create_department_glossary_library(
        code="cli-sync-pipeline",
        name="品保部",
        department_code="QA",
    )
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    _touch(input_dir / "procedure.doc")
    captured: dict[str, object] = {}

    def fake_run_word_translate_job(**kwargs):
        captured.update(kwargs)
        job_dir = kwargs["job_dir"]
        output_path = kwargs["output_path"]
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"translated docx")
        word_batch_runner.jobs.set_job_state(
            job_dir,
            status="completed",
            stage="completed",
            progress=100.0,
        )

    monkeypatch.setattr(
        word_batch_runner.word_translate,
        "run_word_translate_job",
        fake_run_word_translate_job,
    )
    module = _load_word_batch_cli_module()

    exit_code = module.main(
        [
            str(input_dir),
            str(output_dir),
            "--base-url",
            "http://localhost:8000/v1",
            "--api-key",
            "local-key",
            "--model",
            "local-model",
            "--glossary-library-id",
            str(library.library_id),
            "--disable-stage-2",
        ],
        init_database=False,
        smoke_tester=_fake_smoke_tester,
    )

    assert exit_code == 0
    assert captured["source_lang"] == "auto"
    assert captured["target_lang"] == "en"
    assert captured["layout_mode"] == word_layout.BILINGUAL_BELOW
    assert captured["translate_tables"] is True
    assert captured["stage_2_enabled"] is False
    assert (output_dir / "procedure_bilingual_en.docx").exists()
