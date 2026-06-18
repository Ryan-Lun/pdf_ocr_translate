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


def test_doc_translate_deployment_has_no_model_name_fallback(monkeypatch):
    monkeypatch.delenv("DOC_TRANSLATE_DEPLOYMENT", raising=False)
    monkeypatch.delenv("DOC_TRANSLATE_MODEL", raising=False)

    assert openai_config.get_doc_translate_deployment() == ""


def test_pdf_realtime_translate_deployment_has_no_model_name_fallback(monkeypatch):
    monkeypatch.delenv("PDF_REALTIME_TRANSLATE_DEPLOYMENT", raising=False)
    monkeypatch.delenv("DOC_TRANSLATE_DEPLOYMENT", raising=False)
    monkeypatch.delenv("DOC_TRANSLATE_MODEL", raising=False)

    assert openai_config.get_pdf_realtime_translate_deployment() == ""


def test_pdf_realtime_translate_deployment_falls_back_to_doc_deployment(monkeypatch):
    monkeypatch.delenv("PDF_REALTIME_TRANSLATE_DEPLOYMENT", raising=False)
    monkeypatch.setenv("DOC_TRANSLATE_DEPLOYMENT", "doc-deployment")
    monkeypatch.delenv("DOC_TRANSLATE_MODEL", raising=False)

    assert openai_config.get_pdf_realtime_translate_deployment() == "doc-deployment"


def test_format_request_error_includes_read_timeout_for_timeout(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_TIMEOUT_SECONDS", "12.5")

    assert openai_config.format_request_error(TimeoutError("Request timed out.")) == (
        "Request timed out. (read timeout=12.5s)"
    )


def test_format_request_error_allows_subsecond_timeout(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_TIMEOUT_SECONDS", "0.1")

    assert openai_config.get_openai_timeout_seconds() == 0.1
    assert openai_config.format_request_error(TimeoutError("Request timed out.")) == (
        "Request timed out. (read timeout=0.1s)"
    )


def test_format_request_error_hides_connection_pool_endpoint(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_TIMEOUT_SECONDS", "0.1")

    message = openai_config.format_request_error(
        TimeoutError("HTTPSConnectionPool(host='192.168.12.66', port=8080): Read timed out.")
    )

    assert message == "Request timed out. (read timeout=0.1s)"
    assert "192.168.12.66" not in message
    assert "port=8080" not in message


def test_format_request_error_leaves_non_timeout_error_unchanged(monkeypatch):
    monkeypatch.setenv("AZURE_OPENAI_TIMEOUT_SECONDS", "12.5")

    assert openai_config.format_request_error(RuntimeError("Bad request.")) == "Bad request."
