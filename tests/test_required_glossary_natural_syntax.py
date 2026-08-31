from __future__ import annotations

import asyncio
import json

import pytest

from app.services import batch, markdown_translate, realtime_translate
from app.services.word_translate import EnhancedWordTranslator


class _AsyncChoiceResponse:
    def __init__(self, content: str):
        self.choices = [type("Choice", (), {"message": type("Message", (), {"content": content})()})()]


class _AsyncCompletions:
    def __init__(self, responses: list[str], requests: list[dict]):
        self._responses = responses
        self._requests = requests

    async def create(self, **kwargs):
        self._requests.append(kwargs)
        return _AsyncChoiceResponse(self._responses.pop(0))


class _AsyncChat:
    def __init__(self, responses: list[str], requests: list[dict]):
        self.completions = _AsyncCompletions(responses, requests)


class _AsyncClient:
    def __init__(self, responses: list[str], requests: list[dict]):
        self.chat = _AsyncChat(responses, requests)


class _SyncChoiceResponse:
    def __init__(self, content: str):
        self.choices = [type("Choice", (), {"message": type("Message", (), {"content": content})()})()]


class _SyncCompletions:
    def __init__(self, responses: list[str], requests: list[dict]):
        self._responses = responses
        self._requests = requests

    def create(self, **kwargs):
        self._requests.append(kwargs)
        return _SyncChoiceResponse(self._responses.pop(0))


class _SyncChat:
    def __init__(self, responses: list[str], requests: list[dict]):
        self.completions = _SyncCompletions(responses, requests)


class _SyncClient:
    def __init__(self, responses: list[str], requests: list[dict]):
        self.chat = _SyncChat(responses, requests)


def test_case_1_word_required_glossary_allows_natural_reposition(monkeypatch):
    requests: list[dict] = []
    monkeypatch.setattr(
        "app.services.word_translate.openai_config.create_async_client",
        lambda: _AsyncClient(
            ['The shape of <term id="0001">Visual Appearance</term> was reviewed.'],
            requests,
        ),
    )

    translator = EnhancedWordTranslator()
    result = asyncio.run(
        translator.translate_text(
            "外觀形狀",
            "auto",
            "en",
            [],
            glossary_entries=[("外觀", "Appearance")],
        )
    )

    assert result == "The shape of Appearance was reviewed."
    payload = requests[0]["messages"][-1]["content"]
    assert '<term id="0001">Appearance</term>形狀' in payload
    assert "[[[GLOSSARY_TERM_" not in payload
    assert "<term" not in result


def test_case_2_batch_tracks_multiple_required_glossary_terms_in_one_item():
    ocr_pages = [
        {
            "page_index_0based": 0,
            "rec_texts": ["外觀與製程規範"],
            "rec_polys": [[[0, 0], [120, 0], [120, 20], [0, 20]]],
        }
    ]

    items, alias_map, key_map, prefilled = batch.build_batch_items(
        ocr_pages,
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=[("製程規範", "Process Specification"), ("外觀", "Appearance")],
        source_lang="zh",
        target_lang="en",
        document_mode="scanned",
    )

    assert alias_map == {}
    assert prefilled == {}
    payload = items[0]["body"]["messages"][-1]["content"]
    assert payload == '<term id="0001">Appearance</term>與<term id="0002">Process Specification</term>'
    assert key_map["p0000-l0000"]["required_glossary_terms"] == [
        {"id": "0001", "source": "外觀", "target": "Appearance"},
        {"id": "0002", "source": "製程規範", "target": "Process Specification"},
    ]


def test_case_3_markdown_fragment_stays_concise_and_writes_debug_payload(tmp_path):
    debug_job_dir = tmp_path / "job"
    requests: list[dict] = []
    system_prompt = markdown_translate._build_system_prompt(
        "en",
        [("外觀", "Appearance")],
        source_lang="zh",
    )

    result = markdown_translate._translate_text(
        "外觀",
        _SyncClient(['<term id="0001">Look</term>'], requests),
        "fake-model",
        system_prompt,
        glossary_entries=[("外觀", "Appearance")],
        source_lang="zh",
        target_lang="en",
        debug_job_dir=debug_job_dir,
        debug_custom_id="chunk_0001",
    )

    assert result == "Appearance"
    assert "Required glossary terms use this format" in system_prompt
    payload = (debug_job_dir / "realtime_debug" / "chunks" / "chunk_0001" / "payload.txt").read_text(encoding="utf-8")
    parsed = json.loads(
        (debug_job_dir / "realtime_debug" / "chunks" / "chunk_0001" / "parsed_translations.json").read_text(
            encoding="utf-8"
        )
    )
    assert '<term id="0001">Appearance</term>' in payload
    assert "[[[GLOSSARY_TERM_" not in payload
    assert parsed == {"chunk_0001": "Appearance"}
    assert "<term" not in parsed["chunk_0001"]


def test_case_4_region_required_glossary_can_move_around_adjacent_english(monkeypatch):
    requests: list[dict] = []

    class _FakeResponse:
        output_text = 'shape of <term id="0001">Appearance</term>'

    class _FakeResponses:
        @staticmethod
        def create(**kwargs):
            requests.append(kwargs)
            return _FakeResponse()

    class _FakeClient:
        responses = _FakeResponses()

    monkeypatch.setattr("app.services.batch.get_azure_client", lambda: _FakeClient())

    outputs = batch.translate_texts_for_region(
        ["外觀 shape"],
        target_lang="en",
        source_lang="zh",
        model_name="fake-model",
        system_prompt="translate",
        glossary_entries=[("外觀", "Appearance")],
    )

    assert outputs == ["shape of Appearance"]
    assert requests[0]["input"] == '<term id="0001">Appearance</term> shape'
    assert "You may reposition the entire required glossary term" in requests[0]["instructions"]


def test_case_5_word_required_glossary_keeps_exact_protected_identifier(monkeypatch):
    requests: list[dict] = []
    monkeypatch.setattr(
        "app.services.word_translate.openai_config.create_async_client",
        lambda: _AsyncClient(['<term id="0001">Appearance</term> for <<UT0>>'], requests),
    )

    translator = EnhancedWordTranslator()
    result = asyncio.run(
        translator.translate_text(
            "外觀 ABC-123",
            "auto",
            "en",
            ["ABC-123"],
            glossary_entries=[("外觀", "Appearance")],
        )
    )

    assert result == "Appearance for ABC-123"
    payload = requests[0]["messages"][-1]["content"]
    assert '<term id="0001">Appearance</term> <<UT0>>' in payload
    assert "ABC-123" not in payload


def test_case_6_realtime_rejects_synonym_for_required_glossary_term():
    with pytest.raises(RuntimeError, match="missing required glossary terms"):
        realtime_translate._parse_translation_chunk_output(
            "<<<p0000-l0000>>>\nThe look was checked.",
            ["p0000-l0000"],
            {"p0000-l0000": {"0001": "Appearance"}},
        )
