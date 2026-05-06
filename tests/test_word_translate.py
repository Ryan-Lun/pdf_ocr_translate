from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import docx

from app.services import state, translation_memory
from app.services.word_translate import EnhancedWordTranslator, ensure_docx_source


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
    target_language: str = "en",
) -> None:
    async for _progress, _quality in translator.process_translation(
        source_path=source_path,
        output_path=output_path,
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

    async def fake_translate_text_with_quality(text, target_lang, user_terms, cancel_event=None):
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
