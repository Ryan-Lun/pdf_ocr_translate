from __future__ import annotations

from app.services import openai_config


def test_create_sync_client_uses_timeout_env(monkeypatch):
    captured = {}

    class FakeOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.openai.azure.com")
    monkeypatch.setenv("AZURE_OPENAI_TIMEOUT_SECONDS", "45.5")
    monkeypatch.setattr(openai_config, "OpenAI", FakeOpenAI)
    openai_config.create_sync_client.cache_clear()

    openai_config.create_sync_client()

    assert captured["api_key"] == "test-key"
    assert captured["base_url"] == "https://example.openai.azure.com/openai/v1/"
    assert captured["timeout"] == 45.5


def test_create_async_client_uses_openai_timeout_fallback(monkeypatch):
    captured = {}

    class FakeAsyncOpenAI:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://example.openai.azure.com")
    monkeypatch.delenv("AZURE_OPENAI_TIMEOUT_SECONDS", raising=False)
    monkeypatch.setenv("OPENAI_TIMEOUT_SECONDS", "90")
    monkeypatch.setattr(openai_config, "AsyncOpenAI", FakeAsyncOpenAI)
    openai_config.create_async_client.cache_clear()

    openai_config.create_async_client()

    assert captured["timeout"] == 90.0


def test_openai_timeout_invalid_env_uses_default(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_TIMEOUT_SECONDS", "not-a-number")

    assert openai_config.get_openai_timeout_seconds() == openai_config.DEFAULT_OPENAI_TIMEOUT_SECONDS
