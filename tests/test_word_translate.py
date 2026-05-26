from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from zipfile import ZipFile

import docx
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

from app.services import jobs, state, translation_memory
from app.services.word_translate import (
    EnhancedWordTranslator,
    build_word_quality_prompt,
    build_word_system_prompt,
    build_word_system_prompt_with_source,
    enqueue_word_job_from_upload,
    ensure_docx_source,
)


class _FailingCompletions:
    async def create(self, **kwargs):
        raise AssertionError("model call should not happen when word TM hits")


class _FailingChat:
    completions = _FailingCompletions()


class _FailingClient:
    chat = _FailingChat()


async def _consume_translation(
    translator: EnhancedWordTranslator,
    source_path: Path,
    output_path: Path,
    *,
    source_language: str = "auto",
    target_language: str = "en",
) -> None:
    async for _progress, _quality in translator.process_translation(
        source_path=source_path,
        output_path=output_path,
        source_language=source_language,
        target_language=target_language,
        user_terms=[],
    ):
        pass


def test_word_translation_uses_tm_without_model_call(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_PATH", tmp_path / "translation_memory.json")
    monkeypatch.setattr(
        "app.services.word_translate.openai_config.create_async_client",
        lambda: _FailingClient(),
    )
    now_ts = time.time()
    memory = {
        translation_memory.make_tm_key("表格內容", "en", "word"): {
            "source_text": "表格內容",
            "source_normalized": "表格內容",
            "target_text": "table content",
            "target_lang": "en",
            "document_mode": "word",
            "created_at": now_ts,
            "last_used": now_ts,
            "source": "word",
            "count": 1,
        }
    }
    state.TRANSLATION_MEMORY_PATH.write_text(
        json.dumps(memory, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    source_path = tmp_path / "source.docx"
    output_path = tmp_path / "output.docx"
    source_doc = docx.Document()
    source_doc.add_paragraph("表格內容")
    source_doc.add_paragraph("表格內容")
    source_doc.save(source_path)

    translator = EnhancedWordTranslator()
    asyncio.run(_consume_translation(translator, source_path, output_path))

    translated_doc = docx.Document(output_path)
    assert [paragraph.text for paragraph in translated_doc.paragraphs] == [
        "table content",
        "table content",
    ]


def test_word_translation_writes_tm_after_model_translation(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_PATH", tmp_path / "translation_memory.json")
    monkeypatch.setattr(
        "app.services.word_translate.openai_config.create_async_client",
        lambda: _FailingClient(),
    )

    source_path = tmp_path / "source.docx"
    output_path = tmp_path / "output.docx"
    source_doc = docx.Document()
    source_doc.add_paragraph("表格內容")
    source_doc.save(source_path)

    translator = EnhancedWordTranslator()

    async def fake_translate_text_with_quality(
        text,
        source_lang,
        target_lang,
        user_terms,
        glossary_entries=None,
        debug_job_dir=None,
        debug_custom_id=None,
        cancel_event=None,
    ):
        return "table content", 35

    monkeypatch.setattr(translator, "translate_text_with_quality", fake_translate_text_with_quality)
    asyncio.run(_consume_translation(translator, source_path, output_path))

    memory = json.loads(state.TRANSLATION_MEMORY_PATH.read_text(encoding="utf-8"))
    entry = memory["word|en|表格內容"]
    assert entry["target_text"] == "table content"
    assert entry["document_mode"] == "word"
    assert entry["source"] == "word"


def test_ensure_docx_source_converts_doc_with_word_converter(tmp_path, monkeypatch):
    source_path = tmp_path / "legacy.doc"
    source_path.write_bytes(b"legacy")
    expected_path = tmp_path / "legacy.converted.docx"

    def fake_convert(source, out):
        assert source == source_path
        assert out == expected_path
        out.write_bytes(b"converted")
        return out

    monkeypatch.setattr("app.services.word_translate.os.name", "nt")
    monkeypatch.setattr("app.services.word_translate._convert_doc_with_word", fake_convert)
    monkeypatch.setattr(
        "app.services.word_translate._convert_doc_with_soffice",
        lambda source, out: (_ for _ in ()).throw(AssertionError("should not fallback to soffice")),
    )

    result = ensure_docx_source(source_path, expected_path)
    assert result == expected_path
    assert expected_path.read_bytes() == b"converted"


def test_word_zh_prompt_requires_traditional_chinese():
    system_prompt = build_word_system_prompt("zh")
    quality_prompt = build_word_quality_prompt("source", "translated", "zh")

    assert "Traditional Chinese" in system_prompt
    assert "Never use Simplified Chinese characters" in system_prompt
    assert "No Unnecessary Source-Language Leakage" in system_prompt
    assert "Do not output bilingual text" in system_prompt
    assert "Traditional Chinese" in quality_prompt
    assert "leaving unnecessary source-language text mixed into the output" in quality_prompt


def test_word_prompt_can_include_explicit_source_language():
    system_prompt = build_word_system_prompt_with_source("en", "zh")
    assert "Source language: English." in system_prompt


def test_word_prompt_requires_translating_translatable_segments():
    system_prompt = build_word_system_prompt_with_source("en", "zh")

    assert "Translate every translatable segment into Traditional Chinese" in system_prompt
    assert "Preserve source-language text only when it is clearly non-translatable" in system_prompt


def test_word_translation_applies_combined_glossary(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_PATH", tmp_path / "translation_memory.json")
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    monkeypatch.setattr(
        "app.services.word_translate.glossary.load_combined_glossary",
        lambda: [("表格內容", "table content")],
    )

    class _EchoProtectedCompletions:
        async def create(self, **kwargs):
            payload = kwargs["messages"][-1]["content"]
            protected_text = payload.split("<SOURCE_TEXT>\n", 1)[1].split("\n</SOURCE_TEXT>", 1)[0]
            message = type("Message", (), {"content": protected_text})()
            choice = type("Choice", (), {"message": message})()
            return type("Response", (), {"choices": [choice]})()

    class _EchoProtectedChat:
        completions = _EchoProtectedCompletions()

    class _EchoProtectedClient:
        chat = _EchoProtectedChat()

    monkeypatch.setattr(
        "app.services.word_translate.openai_config.create_async_client",
        lambda: _EchoProtectedClient(),
    )

    source_path = tmp_path / "source.docx"
    output_path = tmp_path / "output.docx"
    source_doc = docx.Document()
    source_doc.add_paragraph("表格內容")
    source_doc.save(source_path)

    translator = EnhancedWordTranslator()

    async def fake_validate_translation_quality(original, translated, target_lang):
        return 40

    monkeypatch.setattr(translator, "validate_translation_quality", fake_validate_translation_quality)
    asyncio.run(_consume_translation(translator, source_path, output_path))

    translated_doc = docx.Document(output_path)
    assert [paragraph.text for paragraph in translated_doc.paragraphs] == ["table content"]
    assert (tmp_path / "realtime_debug" / "chunk_plan.json").exists()
    assert (tmp_path / "realtime_debug" / "chunks" / "chunk_0001" / "parsed_translations.json").exists()


def test_enqueue_word_job_from_upload_stores_creator_name(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    captured: dict[str, object] = {}

    def fake_create_job(**kwargs):
        captured.update(kwargs)

    monkeypatch.setattr("app.services.word_translate.jobs.job_store.create_job", fake_create_job)
    monkeypatch.setattr("app.services.word_translate.jobs.notify_jobs_update", lambda: None)

    source_path = tmp_path / "source.docx"
    source_path.write_bytes(b"docx")

    job_id = enqueue_word_job_from_upload(
        source_path,
        "sample",
        "auto",
        "en",
        creator_name="alice",
    )

    meta = jobs.load_job_meta(state.JOB_ROOT / job_id)
    assert meta is not None
    assert meta["creator_name"] == "alice"
    assert captured["payload"]["creator_name"] == "alice"


def test_word_translation_preserves_header_field_code_paragraph(tmp_path, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_PATH", tmp_path / "translation_memory.json")
    monkeypatch.setattr(
        "app.services.word_translate.openai_config.create_async_client",
        lambda: _FailingClient(),
    )

    source_path = tmp_path / "source.docx"
    output_path = tmp_path / "output.docx"
    source_doc = docx.Document()
    source_doc.add_paragraph("表格內容")
    header = source_doc.sections[0].header
    paragraph = header.paragraphs[0]
    paragraph.add_run("頁次: ")
    begin = paragraph.add_run()
    begin._r.append(OxmlElement("w:fldChar"))
    begin._r[-1].set(qn("w:fldCharType"), "begin")
    instr = paragraph.add_run()
    instr_text = OxmlElement("w:instrText")
    instr_text.set(qn("xml:space"), "preserve")
    instr_text.text = " PAGE "
    instr._r.append(instr_text)
    separate = paragraph.add_run()
    separate._r.append(OxmlElement("w:fldChar"))
    separate._r[-1].set(qn("w:fldCharType"), "separate")
    result = paragraph.add_run("1")
    end = paragraph.add_run()
    end._r.append(OxmlElement("w:fldChar"))
    end._r[-1].set(qn("w:fldCharType"), "end")
    source_doc.save(source_path)

    translator = EnhancedWordTranslator()

    async def fake_translate_text_with_quality(
        text,
        source_lang,
        target_lang,
        user_terms,
        glossary_entries=None,
        debug_job_dir=None,
        debug_custom_id=None,
        cancel_event=None,
    ):
        return "table content", 35

    monkeypatch.setattr(translator, "translate_text_with_quality", fake_translate_text_with_quality)
    asyncio.run(_consume_translation(translator, source_path, output_path))

    translated_doc = docx.Document(output_path)
    assert translated_doc.paragraphs[0].text == "table content"
    assert translated_doc.sections[0].header.paragraphs[0].text == "頁次: 1"
    with ZipFile(output_path) as zf:
        header_xml = zf.read("word/header1.xml").decode("utf-8", "ignore")
    assert "instrText" in header_xml
    assert " PAGE " in header_xml
