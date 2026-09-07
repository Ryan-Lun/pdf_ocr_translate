from __future__ import annotations

import json
import uuid
from pathlib import Path

from app.services import batch, doc_workspace, glossary, job_store, jobs, state, translation_memory, word_translate


def _seed_default_glossary(entries: list[tuple[str, str]]):
    library = glossary.get_or_create_default_department_glossary()
    for source_term, target_term in entries:
        glossary.upsert_department_glossary_entry(
            library_id=library.library_id,
            source_lang="zh",
            target_lang="en",
            source_term=source_term,
            target_term=target_term,
        )
    return library


def test_glossary_context_artifact_is_disabled_by_default(app, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GLOSSARY_CONTEXT_ARTIFACT_ENABLED", False)
    _seed_default_glossary([("外觀", "Appearance")])
    job_dir = tmp_path / ("a" * 32)
    job_dir.mkdir()

    context = glossary.current_department_glossary_context(
        glossary_entries=glossary.load_combined_glossary(),
    )
    path = glossary.write_department_glossary_context_artifact(job_dir, context)

    assert path is None
    assert not (job_dir / "glossary_context.json").exists()


def test_glossary_context_artifact_is_human_readable_when_enabled(app, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GLOSSARY_CONTEXT_ARTIFACT_ENABLED", True)
    library = _seed_default_glossary([("外觀", "Appearance")])
    job_dir = tmp_path / ("a" * 32)
    job_dir.mkdir()

    context = glossary.current_department_glossary_context(
        glossary_entries=glossary.load_combined_glossary(),
    )
    path = glossary.write_department_glossary_context_artifact(job_dir, context)

    assert path is not None
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert payload == {
        "source": "sql",
        "library_id": library.library_id,
        "library_code": glossary.DEFAULT_DEPARTMENT_GLOSSARY_CODE,
        "library_name": "法規文管部",
        "department_code": "法規文管部",
        "entry_count": 1,
        "entries": [{"source_term": "外觀", "target_term": "Appearance"}],
    }


def test_batch_translate_job_records_glossary_context_and_keeps_hits_artifact(app, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "GLOSSARY_CONTEXT_ARTIFACT_ENABLED", False)
    monkeypatch.setattr(state, "PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY", True)
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_ENABLED", True)
    library = _seed_default_glossary([("外觀", "Appearance")])
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
        },
    )
    monkeypatch.setattr(
        batch.ocr,
        "load_ocr_pages",
        lambda current_job_dir: [
            {"page_index_0based": 0, "rec_texts": ["外觀"], "rec_polys": []}
        ],
    )
    monkeypatch.setattr(batch.ocr, "load_pp_pages", lambda current_job_dir: {})
    monkeypatch.setattr(
        translation_memory,
        "retrieve_sql",
        lambda source_text, **kwargs: translation_memory.TranslationMemoryRetrievalResult(
            source_text=str(source_text),
            source_normalized=translation_memory.normalize_source_text(str(source_text)),
            source_lang="zh",
            target_lang="en",
            document_mode="form",
            exact_match=translation_memory.TranslationMemoryMatch(
                entry_id=68,
                match_type="byte_exact",
                source_text=str(source_text),
                source_normalized=translation_memory.normalize_source_text(str(source_text)),
                target_text="Appearance",
                source_lang="zh",
                target_lang="en",
                document_mode="form",
                score=1.0,
            ),
            fuzzy_references=[],
            semantic_references=[],
        ),
    )
    monkeypatch.setattr(translation_memory, "record_exact_reuse", lambda entry_ids: None)
    monkeypatch.setattr(batch.jobs, "set_job_state", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch.jobs, "write_batch_status", lambda *args, **kwargs: None)
    monkeypatch.setattr(batch, "_finalize_batch_translate_job", lambda **kwargs: None)

    assert batch.run_batch_translate_job(job_id, job_dir, jobs.load_batch_config(job_dir)) is True

    config = jobs.load_batch_config(job_dir)
    assert config["department_glossary_library_id"] == library.library_id
    assert config["department_glossary_library_code"] == glossary.DEFAULT_DEPARTMENT_GLOSSARY_CODE
    assert not (job_dir / "glossary_context.json").exists()
    hits = json.loads((job_dir / "glossary_hits.json").read_text(encoding="utf-8"))
    assert hits == []


def test_jobs_list_exposes_glossary_context_artifact_url(app, monkeypatch, tmp_path):
    monkeypatch.setattr(state, "PDF_OVERLAY_JOB_ROOT", tmp_path)
    job_id = uuid.uuid4().hex
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "glossary_context.json").write_text("{}", encoding="utf-8")
    job_store.create_job(
        job_id=job_id,
        job_type="ocr_overlay",
        status="completed",
        stage="completed",
        job_name="sample",
        owner_work_id="NE025",
        payload={"owner_work_id": "NE025"},
    )
    job_store.register_artifact(job_id, "glossary_context", "glossary_context.json")

    with app.test_request_context():
        items = jobs.build_jobs_list("ocr_overlay", owner_work_id="NE025")

    assert items[0]["glossary_context_url"].endswith(f"/jobs/{job_id}/glossary_context.json")



def _glossary_context_payload(library):
    return {
        "source": "sql",
        "library_id": library.library_id,
        "library_code": glossary.DEFAULT_DEPARTMENT_GLOSSARY_CODE,
        "library_name": glossary.DEFAULT_DEPARTMENT_GLOSSARY_NAME,
        "department_code": glossary.DEFAULT_DEPARTMENT_GLOSSARY_NAME,
        "entry_count": 1,
        "entries": [{"source_term": "外觀", "target_term": "Appearance"}],
    }


def test_word_legacy_job_list_exposes_glossary_context_artifact_url(app, monkeypatch, tmp_path):
    monkeypatch.setattr(state, "WORD_TRANSLATE_JOB_ROOT", tmp_path)
    job_id = uuid.uuid4().hex
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True)
    (job_dir / "source.docx").write_bytes(b"docx")
    (job_dir / "glossary_context.json").write_text("{}", encoding="utf-8")
    jobs.write_job_meta(
        job_dir,
        {
            "job_type": "word_translate",
            "job_name": "word sample",
            "word_stage": "completed",
            "source_filename": "source.docx",
            "source_lang": "zh",
            "target_lang": "en",
            "owner_work_id": "NE025",
        },
    )

    with app.test_request_context():
        items = jobs.build_jobs_list("word_translate", owner_work_id="NE025")

    assert items[0]["legacy_state"] is True
    assert items[0]["glossary_context_url"].endswith(f"/jobs/{job_id}/glossary_context.json")


def test_word_translate_job_records_glossary_context_payload(app, tmp_path, monkeypatch):
    library = _seed_default_glossary([("外觀", "Appearance")])
    job_id = uuid.uuid4().hex
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True)
    source_path = job_dir / "source.docx"
    source_path.write_bytes(b"docx")
    output_path = job_dir / "output" / "output.docx"
    jobs.create_job_state(
        job_dir,
        job_type="word_translate",
        stage="queued",
        job_name="word sample",
        owner_work_id="NE025",
        target_lang="en",
        payload={"owner_work_id": "NE025", "target_lang": "en"},
        meta={"job_type": "word_translate", "owner_work_id": "NE025", "target_lang": "en"},
    )

    class FakeTranslator:
        async def process_translation(self, **kwargs):
            jobs.update_job_meta(
                kwargs["debug_job_dir"],
                **glossary.add_department_glossary_context_to_config(
                    {},
                    _glossary_context_payload(library),
                ),
            )
            yield 100.0, 0.0

    monkeypatch.setattr(word_translate, "EnhancedWordTranslator", FakeTranslator)
    monkeypatch.setattr(translation_memory, "record_artifact_usage_from_files", lambda job_dir: None)

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

    payload = job_store.deserialize_payload(job_store.get_job(job_id))
    assert payload["department_glossary_library_id"] == library.library_id
    assert payload["department_glossary_library_code"] == glossary.DEFAULT_DEPARTMENT_GLOSSARY_CODE
    assert payload["department_glossary_entry_count"] == 1


def test_doc_workspace_job_records_glossary_context_payload(app, tmp_path, monkeypatch):
    library = _seed_default_glossary([("外觀", "Appearance")])
    job_id = uuid.uuid4().hex
    job_dir = tmp_path / job_id
    job_dir.mkdir(parents=True)
    source_pdf = job_dir / "source.pdf"
    source_pdf.write_bytes(b"pdf")
    jobs.create_job_state(
        job_dir,
        job_type="doc_workspace",
        stage="queued",
        job_name="pdf rebuild sample",
        owner_work_id="NE025",
        target_lang="en",
        payload={"owner_work_id": "NE025", "target_lang": "en"},
        meta={"job_type": "doc_workspace", "owner_work_id": "NE025", "target_lang": "en"},
    )

    def fake_extract_pdf_to_markdown(pdf_path, structure_dir, warning_callback=None):
        structure_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = structure_dir / "doc.md"
        markdown_path.write_text("外觀", encoding="utf-8")
        return markdown_path, {}

    def fake_export_markdown_to_html(markdown_path, html_path):
        html_path.parent.mkdir(parents=True, exist_ok=True)
        html_path.write_text("<p>外觀</p>", encoding="utf-8")

    def fake_translate_html_file(source_path, output_path, **kwargs):
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text("<p>Appearance</p>", encoding="utf-8")

    def fake_export_html_to_docx(html_path, docx_path):
        docx_path.parent.mkdir(parents=True, exist_ok=True)
        docx_path.write_bytes(b"docx")

    monkeypatch.setattr(doc_workspace.pp_structure, "extract_pdf_to_markdown", fake_extract_pdf_to_markdown)
    monkeypatch.setattr(doc_workspace.docx_export, "export_markdown_to_html", fake_export_markdown_to_html)
    monkeypatch.setattr(doc_workspace.markdown_translate, "translate_html_file", fake_translate_html_file)
    monkeypatch.setattr(doc_workspace.docx_export, "export_html_to_docx", fake_export_html_to_docx)

    doc_workspace.run_doc_workspace_job(
        job_id,
        job_dir,
        source_pdf,
        source_lang="zh",
        target_lang="en",
    )

    payload = job_store.deserialize_payload(job_store.get_job(job_id))
    assert payload["department_glossary_library_id"] == library.library_id
    assert payload["department_glossary_library_code"] == glossary.DEFAULT_DEPARTMENT_GLOSSARY_CODE
    assert payload["department_glossary_entry_count"] == 1
