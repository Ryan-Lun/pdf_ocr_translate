from __future__ import annotations

import uuid

import docx

from app.services import (
    batch,
    doc_workspace,
    glossary,
    job_store,
    jobs,
    realtime_translate,
    word_translate,
)


def _clear_department_glossary() -> None:
    with job_store.session_scope() as session:
        session.query(job_store.DepartmentGlossaryEntryRecord).delete()
        session.query(job_store.DepartmentGlossaryLibraryRecord).delete()


def _create_library(
    *,
    code: str,
    name: str,
    department_code: str,
    is_active: bool = True,
    entries: list[tuple[str, str]] | None = None,
) -> glossary.DepartmentGlossaryLibrary:
    library = glossary.get_or_create_department_glossary_library(
        code=code,
        name=name,
        department_code=department_code,
        is_active=is_active,
    )
    for source_term, target_term in entries or []:
        glossary.upsert_department_glossary_entry(
            library_id=library.library_id,
            source_lang="zh",
            target_lang="en",
            source_term=source_term,
            target_term=target_term,
        )
    return library


def _selected_config(library: glossary.DepartmentGlossaryLibrary) -> dict[str, object]:
    return glossary.add_department_glossary_context_to_config(
        {},
        {
            "source": "sql",
            "library_id": library.library_id,
            "library_code": library.code,
            "library_name": library.name,
            "department_code": library.department_code,
            "entry_count": 0,
        },
    )


def test_pdf_batch_worker_loads_selected_library_at_execution_time(app, tmp_path, monkeypatch):
    _clear_department_glossary()
    _create_library(
        code=glossary.DEFAULT_DEPARTMENT_GLOSSARY_CODE,
        name="法規文管部",
        department_code="DOC",
        entries=[("外觀", "Default Appearance")],
    )
    selected = _create_library(
        code="qa",
        name="品保部",
        department_code="QA",
        entries=[("外觀", "QA Appearance")],
    )
    job_id = "a" * 32
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    config = {
        "target_lang": "en",
        "source_lang": "auto",
        "model": "dummy-model",
        "document_mode": "form",
        "translate_mode": "batch",
        **_selected_config(selected),
    }
    jobs.write_batch_config(job_dir, config)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        batch.ocr,
        "load_ocr_pages",
        lambda current_job_dir: [
            {"page_index_0based": 0, "rec_texts": ["外觀"], "rec_polys": []}
        ],
    )
    monkeypatch.setattr(batch.ocr, "load_pp_pages", lambda current_job_dir: {})

    def fake_build_batch_items(*args, **kwargs):
        captured["glossary_entries"] = kwargs["glossary_entries"]
        return [], {}, {}, {"p0-l0": "QA Appearance"}

    monkeypatch.setattr(batch, "build_batch_items", fake_build_batch_items)
    monkeypatch.setattr(batch, "_finalize_batch_translate_job", lambda **kwargs: None)
    monkeypatch.setattr(batch.jobs, "set_job_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch.jobs, "write_batch_status", lambda *args, **kwargs: None)

    assert batch.run_batch_translate_job(job_id, job_dir, jobs.load_batch_config(job_dir)) is True

    assert captured["glossary_entries"] == [("外觀", "QA Appearance")]
    saved_config = jobs.load_batch_config(job_dir)
    assert saved_config["department_glossary_library_id"] == selected.library_id
    assert saved_config["department_glossary_entry_count"] == 1


def test_pdf_batch_worker_fails_when_selected_library_is_inactive(app, tmp_path, monkeypatch):
    _clear_department_glossary()
    inactive = _create_library(
        code="inactive",
        name="停用部門",
        department_code="OFF",
        is_active=False,
        entries=[("外觀", "Inactive Appearance")],
    )
    job_id = "b" * 32
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    jobs.write_batch_config(
        job_dir,
        {
            "target_lang": "en",
            "source_lang": "zh",
            "model": "dummy-model",
            "document_mode": "form",
            "translate_mode": "batch",
            **_selected_config(inactive),
        },
    )
    monkeypatch.setattr(batch.jobs, "set_job_state", lambda *args, **kwargs: None)

    assert batch.run_batch_translate_job(job_id, job_dir, jobs.load_batch_config(job_dir)) is False

    status = jobs.load_batch_status(job_dir) or {}
    assert status["status"] == "failed"
    assert "選擇的部門詞彙庫已停用" in status["error"]


def test_word_worker_passes_selected_library_to_translator(app, tmp_path, monkeypatch):
    _clear_department_glossary()
    selected = _create_library(code="qa", name="品保部", department_code="QA")
    job_id = uuid.uuid4().hex
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    source_path = job_dir / "source.docx"
    source_path.write_bytes(b"docx")
    output_path = job_dir / "output" / "output.docx"
    selected_config = _selected_config(selected)
    jobs.create_job_state(
        job_dir,
        job_type="word_translate",
        stage="queued",
        job_name="word sample",
        target_lang="en",
        payload={"target_lang": "en", **selected_config},
        meta={"job_type": "word_translate", "target_lang": "en", **selected_config},
    )
    captured: dict[str, object] = {}

    class FakeTranslator:
        async def process_translation(self, **kwargs):
            captured["department_glossary_library_id"] = kwargs.get("department_glossary_library_id")
            yield 100.0, 0.0

    monkeypatch.setattr(word_translate, "EnhancedWordTranslator", FakeTranslator)
    monkeypatch.setattr(
        word_translate.jobs.job_store,
        "register_artifact",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        word_translate.translation_memory,
        "record_artifact_usage_from_files",
        lambda job_dir: None,
    )

    word_translate.run_word_translate_job(
        job_id=job_id,
        job_dir=job_dir,
        source_path=source_path,
        processing_source_path=source_path,
        output_path=output_path,
        source_lang="zh",
        target_lang="en",
        retain_terms=[],
    )

    assert captured["department_glossary_library_id"] == selected.library_id


def test_pdf_rebuild_worker_passes_selected_library_to_markdown_translate(app, tmp_path, monkeypatch):
    _clear_department_glossary()
    selected = _create_library(code="qa", name="品保部", department_code="QA")
    job_id = uuid.uuid4().hex
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True)
    source_pdf = job_dir / "source.pdf"
    source_pdf.write_bytes(b"pdf")
    selected_config = _selected_config(selected)
    jobs.create_job_state(
        job_dir,
        job_type="doc_workspace",
        stage="queued",
        job_name="pdf rebuild sample",
        target_lang="en",
        payload={"target_lang": "en", **selected_config},
        meta={"job_type": "doc_workspace", "target_lang": "en", **selected_config},
    )
    captured: dict[str, object] = {}

    def fake_extract_pdf_to_markdown(pdf_path, structure_dir, warning_callback=None):
        structure_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = structure_dir / "doc.md"
        markdown_path.write_text("外觀", encoding="utf-8")
        return markdown_path, {}

    def fake_export_markdown_to_html(markdown_path, html_path):
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<p>外觀</p>", encoding="utf-8")

    def fake_translate_html_file(source_path, output_path, **kwargs):
        captured["department_glossary_library_id"] = kwargs.get("department_glossary_library_id")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("<p>QA Appearance</p>", encoding="utf-8")

    def fake_export_html_to_docx(html_path, docx_path):
        docx_path.parent.mkdir(parents=True, exist_ok=True)
        docx_path.write_bytes(b"docx")

    monkeypatch.setattr(
        doc_workspace.pp_structure,
        "extract_pdf_to_markdown",
        fake_extract_pdf_to_markdown,
    )
    monkeypatch.setattr(
        doc_workspace.docx_export,
        "export_markdown_to_html",
        fake_export_markdown_to_html,
    )
    monkeypatch.setattr(
        doc_workspace.markdown_translate,
        "translate_html_file",
        fake_translate_html_file,
    )
    monkeypatch.setattr(
        doc_workspace.docx_export,
        "export_html_to_docx",
        fake_export_html_to_docx,
    )
    monkeypatch.setattr(
        doc_workspace.jobs.job_store,
        "register_artifact",
        lambda *args, **kwargs: None,
    )

    doc_workspace.run_doc_workspace_job(job_id, job_dir, source_pdf, source_lang="zh", target_lang="en")

    assert captured["department_glossary_library_id"] == selected.library_id


def test_word_worker_fails_when_selected_library_is_inactive(app, tmp_path, monkeypatch):
    _clear_department_glossary()
    inactive = _create_library(
        code="inactive-word",
        name="停用 Word 部門",
        department_code="OFF",
        is_active=False,
        entries=[("外觀", "Inactive Appearance")],
    )
    job_id = uuid.uuid4().hex
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    source_path = job_dir / "source.docx"
    source_doc = docx.Document()
    source_doc.add_paragraph("外觀")
    source_doc.save(source_path)
    output_path = job_dir / "output" / "output.docx"
    selected_config = _selected_config(inactive)
    jobs.create_job_state(
        job_dir,
        job_type="word_translate",
        stage="queued",
        job_name="inactive word sample",
        target_lang="en",
        payload={"target_lang": "en", **selected_config},
        meta={"job_type": "word_translate", "target_lang": "en", **selected_config},
    )

    def fail_create_async_client():
        raise AssertionError("Word OpenAI request must not start for inactive selected glossary")

    monkeypatch.setattr(word_translate.openai_config, "create_async_client", fail_create_async_client)

    word_translate.run_word_translate_job(
        job_id=job_id,
        job_dir=job_dir,
        source_path=source_path,
        processing_source_path=source_path,
        output_path=output_path,
        source_lang="zh",
        target_lang="en",
        retain_terms=[],
    )

    record = job_store.get_job(job_id)
    assert record is not None
    assert record.status == "failed"
    assert "選擇的部門詞彙庫已停用" in str(record.error_message)


def test_pdf_rebuild_worker_fails_when_selected_library_is_inactive(app, tmp_path, monkeypatch):
    _clear_department_glossary()
    inactive = _create_library(
        code="inactive-rebuild",
        name="停用 PDF 重建部門",
        department_code="OFF",
        is_active=False,
        entries=[("外觀", "Inactive Appearance")],
    )
    job_id = uuid.uuid4().hex
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True)
    source_pdf = job_dir / "source.pdf"
    source_pdf.write_bytes(b"pdf")
    selected_config = _selected_config(inactive)
    jobs.create_job_state(
        job_dir,
        job_type="doc_workspace",
        stage="queued",
        job_name="inactive pdf rebuild sample",
        target_lang="en",
        payload={"target_lang": "en", **selected_config},
        meta={"job_type": "doc_workspace", "target_lang": "en", **selected_config},
    )

    def fake_extract_pdf_to_markdown(pdf_path, structure_dir, warning_callback=None):
        structure_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = structure_dir / "doc.md"
        markdown_path.write_text("外觀", encoding="utf-8")
        return markdown_path, {}

    def fake_export_markdown_to_html(markdown_path, html_path):
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<p>外觀</p>", encoding="utf-8")

    def fail_get_translation_client():
        raise AssertionError("PDF rebuild OpenAI request must not start for inactive selected glossary")

    monkeypatch.setattr(
        doc_workspace.pp_structure,
        "extract_pdf_to_markdown",
        fake_extract_pdf_to_markdown,
    )
    monkeypatch.setattr(
        doc_workspace.docx_export,
        "export_markdown_to_html",
        fake_export_markdown_to_html,
    )
    monkeypatch.setattr(doc_workspace.markdown_translate, "_get_translation_client", fail_get_translation_client)

    doc_workspace.run_doc_workspace_job(job_id, job_dir, source_pdf, source_lang="zh", target_lang="en")

    record = job_store.get_job(job_id)
    assert record is not None
    assert record.status == "failed"
    assert "選擇的部門詞彙庫已停用" in str(record.error_message)


def test_pdf_realtime_worker_loads_selected_library_at_execution_time(app, tmp_path, monkeypatch):
    _clear_department_glossary()
    _create_library(
        code=glossary.DEFAULT_DEPARTMENT_GLOSSARY_CODE,
        name="法規文管部",
        department_code="DOC",
        entries=[("外觀", "Default Appearance")],
    )
    selected = _create_library(
        code="qa-realtime",
        name="品保部 Realtime",
        department_code="QA",
        entries=[("外觀", "QA Realtime Appearance")],
    )
    job_id = uuid.uuid4().hex
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    config = {
        "target_lang": "en",
        "source_lang": "auto",
        "model": "dummy-model",
        "document_mode": "form",
        "translate_mode": "realtime",
        **_selected_config(selected),
    }
    jobs.write_batch_config(job_dir, config)
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        realtime_translate.batch.ocr,
        "load_ocr_pages",
        lambda current_job_dir: [
            {"page_index_0based": 0, "rec_texts": ["外觀"], "rec_polys": []}
        ],
    )
    monkeypatch.setattr(realtime_translate.batch.ocr, "load_pp_pages", lambda current_job_dir: {})

    def fake_build_batch_items(*args, **kwargs):
        captured["glossary_entries"] = kwargs["glossary_entries"]
        return [], {}, {}, {"p0-l0": "QA Realtime Appearance"}

    monkeypatch.setattr(realtime_translate.batch, "build_batch_items", fake_build_batch_items)
    monkeypatch.setattr(
        realtime_translate.batch.translation_memory,
        "write_tm_artifacts",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        realtime_translate.jobs,
        "write_batch_alias_map",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        realtime_translate.jobs,
        "write_batch_prefill_map",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        realtime_translate.batch,
        "_write_batch_key_map",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        realtime_translate.batch,
        "_write_required_glossary_hits_from_key_map",
        lambda *args, **kwargs: None,
    )

    plan = realtime_translate._prepare_realtime_plan(job_dir, jobs.load_batch_config(job_dir))

    assert captured["glossary_entries"] == [("外觀", "QA Realtime Appearance")]
    assert plan["prefilled"] == {"p0-l0": "QA Realtime Appearance"}
    saved_config = jobs.load_batch_config(job_dir)
    assert saved_config["department_glossary_library_id"] == selected.library_id
    assert saved_config["department_glossary_entry_count"] == 1


def test_pdf_realtime_worker_fails_when_selected_library_is_inactive(app, tmp_path, monkeypatch):
    _clear_department_glossary()
    inactive = _create_library(
        code="inactive-realtime",
        name="停用 Realtime 部門",
        department_code="OFF",
        is_active=False,
        entries=[("外觀", "Inactive Realtime Appearance")],
    )
    job_id = uuid.uuid4().hex
    job_dir = tmp_path / job_id
    job_dir.mkdir()
    config = {
        "target_lang": "en",
        "source_lang": "zh",
        "model": "dummy-model",
        "document_mode": "form",
        "translate_mode": "realtime",
        **_selected_config(inactive),
    }
    jobs.write_batch_config(job_dir, config)
    jobs.create_job_state(
        job_dir,
        job_type="ocr_overlay",
        stage="queued",
        job_name="inactive realtime sample",
        target_lang="en",
        payload=config,
        meta={"job_type": "ocr_overlay", "target_lang": "en", **config},
    )

    def fail_load_ocr_pages(current_job_dir):
        raise AssertionError("Realtime OCR loading must not start for inactive selected glossary")

    monkeypatch.setattr(realtime_translate.batch.ocr, "load_ocr_pages", fail_load_ocr_pages)
    monkeypatch.setattr(
        realtime_translate.audit_service,
        "record_system_error",
        lambda *args, **kwargs: None,
    )

    assert (
        realtime_translate.run_realtime_translate_job(
            job_id,
            job_dir,
            config=jobs.load_batch_config(job_dir),
        )
        is False
    )

    status = jobs.load_batch_status(job_dir) or {}
    assert status["status"] == "failed"
    assert "選擇的部門詞彙庫已停用" in status["error"]
    record = job_store.get_job(job_id)
    assert record is not None
    assert record.status == "failed"
    assert "選擇的部門詞彙庫已停用" in str(record.error_message)
