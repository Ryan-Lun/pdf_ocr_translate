from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path


MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "services" / "markdown_translate.py"


def _load_module():
    fake_app = types.ModuleType("app")
    fake_app.__path__ = []
    fake_services = types.ModuleType("app.services")
    fake_services.__path__ = []
    fake_glossary = types.ModuleType("app.services.glossary")
    fake_glossary.load_combined_glossary = lambda: []
    fake_glossary.apply_glossary_with_protection = lambda text, entries=None: text
    fake_glossary.restore_protected_glossary_terms = lambda text: text
    fake_openai_config = types.ModuleType("app.services.openai_config")
    fake_state = types.ModuleType("app.services.state")
    fake_translation_debug = types.ModuleType("app.services.translation_debug")
    fake_translation_debug.record_request = lambda **kwargs: None
    fake_translation_debug.record_response = lambda **kwargs: None
    fake_translation_debug.record_error = lambda **kwargs: None
    fake_translation_debug.record_parsed = lambda **kwargs: None
    fake_translation_debug.record_plan = lambda *args, **kwargs: None
    fake_state.DOC_TRANSLATE_MODEL = "fake-model"
    fake_state.DOC_TRANSLATE_MAX_CHARS = 4000
    fake_state.DOC_TRANSLATE_SYSTEM_PROMPT = "Translate HTML text nodes."

    sys.modules["app"] = fake_app
    sys.modules["app.services"] = fake_services
    sys.modules["app.services.glossary"] = fake_glossary
    sys.modules["app.services.openai_config"] = fake_openai_config
    sys.modules["app.services.state"] = fake_state
    sys.modules["app.services.translation_debug"] = fake_translation_debug

    spec = importlib.util.spec_from_file_location("app.services.markdown_translate", MODULE_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_translate_html_file_preserves_tags_and_image_src(tmp_path: Path):
    module = _load_module()
    source = tmp_path / "doc.html"
    output = tmp_path / "doc.translated.html"
    source.write_text(
        '<p>Hello</p><div><img src="images/pic.jpg" alt="Image" /></div><table><tr><td>World</td></tr></table>',
        encoding="utf-8",
    )

    translations = {"Hello": "Bonjour", "World": "Monde"}

    class FakeCompletions:
        def create(self, **kwargs):
            text = kwargs["messages"][-1]["content"].split("\n")[-1]
            translated = translations.get(text, text)
            message = types.SimpleNamespace(content=translated)
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(choices=[choice])

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    module._get_translation_client = lambda: (FakeClient(), "fake-model")

    module.translate_html_file(source, output, target_lang="fr")
    translated = output.read_text(encoding="utf-8")

    assert "<p>Bonjour</p>" in translated
    assert '<img src="images/pic.jpg" alt="Image" />' in translated
    assert "<td>Monde</td>" in translated
    assert "<table>" in translated


def test_translate_html_file_applies_glossary_protection(tmp_path: Path):
    module = _load_module()
    source = tmp_path / "doc.html"
    output = tmp_path / "doc.translated.html"
    source.write_text("<p>髖臼杯</p>", encoding="utf-8")

    module.glossary.load_combined_glossary = lambda: [("髖臼杯", "Acetabular Cup")]
    module.glossary.apply_glossary_with_protection = (
        lambda text, entries=None: text.replace("髖臼杯", "[[[GLOSSARY_TERM_0001::Acetabular Cup]]]")
    )
    module.glossary.restore_protected_glossary_terms = (
        lambda text: text.replace("[[[GLOSSARY_TERM_0001::Acetabular Cup]]]", "Acetabular Cup")
    )

    class FakeCompletions:
        def create(self, **kwargs):
            text = kwargs["messages"][-1]["content"].split("\n")[-1]
            message = types.SimpleNamespace(content=text)
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(choices=[choice])

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    module._get_translation_client = lambda: (FakeClient(), "fake-model")

    module.translate_html_file(source, output, target_lang="en")
    translated = output.read_text(encoding="utf-8")

    assert "<p>Acetabular Cup</p>" in translated


def test_translate_html_file_writes_realtime_debug(tmp_path: Path):
    module = _load_module()
    source = tmp_path / "doc.html"
    output = tmp_path / "doc.translated.html"
    debug_job_dir = tmp_path / "job"
    source.write_text("<p>Hello</p>", encoding="utf-8")

    def _write_json(path: Path, payload):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(__import__("json").dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    def _write_text(path: Path, payload: str):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload, encoding="utf-8")

    def record_request(**kwargs):
        chunk_dir = debug_job_dir / "realtime_debug" / "chunks" / kwargs["chunk_label"]
        mirror_dir = debug_job_dir / "output" / "realtime_debug" / "chunks" / kwargs["chunk_label"]
        for current in (chunk_dir, mirror_dir):
            _write_json(current / "request_meta.json", {"mode": kwargs["mode"], "expected_ids": kwargs["expected_ids"]})
            _write_text(current / "system_prompt.txt", kwargs["system_prompt"])
            _write_text(current / "payload.txt", kwargs["payload"])

    def record_response(**kwargs):
        chunk_dir = debug_job_dir / "realtime_debug" / "chunks" / kwargs["chunk_label"]
        mirror_dir = debug_job_dir / "output" / "realtime_debug" / "chunks" / kwargs["chunk_label"]
        for current in (chunk_dir, mirror_dir):
            _write_text(current / f"response_attempt_{kwargs['attempt']}.txt", kwargs["content"])

    def record_parsed(**kwargs):
        chunk_dir = debug_job_dir / "realtime_debug" / "chunks" / kwargs["chunk_label"]
        mirror_dir = debug_job_dir / "output" / "realtime_debug" / "chunks" / kwargs["chunk_label"]
        for current in (chunk_dir, mirror_dir):
            _write_json(current / "parsed_translations.json", kwargs["translations"])

    def record_plan(job_dir, items):
        _write_json(job_dir / "realtime_debug" / "chunk_plan.json", items)
        _write_json(job_dir / "output" / "realtime_debug" / "chunk_plan.json", items)

    module.translation_debug.record_request = record_request
    module.translation_debug.record_response = record_response
    module.translation_debug.record_parsed = record_parsed
    module.translation_debug.record_plan = record_plan

    class FakeCompletions:
        def create(self, **kwargs):
            message = types.SimpleNamespace(content="Bonjour")
            choice = types.SimpleNamespace(message=message)
            return types.SimpleNamespace(choices=[choice])

    class FakeChat:
        completions = FakeCompletions()

    class FakeClient:
        chat = FakeChat()

    module._get_translation_client = lambda: (FakeClient(), "fake-model")
    module.translate_html_file(source, output, target_lang="fr", debug_job_dir=debug_job_dir)

    request_meta = debug_job_dir / "realtime_debug" / "chunks" / "chunk_0001" / "request_meta.json"
    parsed = debug_job_dir / "realtime_debug" / "chunks" / "chunk_0001" / "parsed_translations.json"
    mirrored = debug_job_dir / "output" / "realtime_debug" / "chunks" / "chunk_0001" / "parsed_translations.json"

    assert request_meta.exists()
    assert parsed.exists()
    assert mirrored.exists()
