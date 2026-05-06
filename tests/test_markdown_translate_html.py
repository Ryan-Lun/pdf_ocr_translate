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
    fake_openai_config = types.ModuleType("app.services.openai_config")
    fake_state = types.ModuleType("app.services.state")
    fake_state.DOC_TRANSLATE_MODEL = "fake-model"
    fake_state.DOC_TRANSLATE_MAX_CHARS = 4000
    fake_state.DOC_TRANSLATE_SYSTEM_PROMPT = "Translate HTML text nodes."

    sys.modules["app"] = fake_app
    sys.modules["app.services"] = fake_services
    sys.modules["app.services.glossary"] = fake_glossary
    sys.modules["app.services.openai_config"] = fake_openai_config
    sys.modules["app.services.state"] = fake_state

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
