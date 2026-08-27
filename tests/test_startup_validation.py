from __future__ import annotations

import pytest

import app as app_pkg
from app import create_app
from app.config import ProductionConfig


def _configure_valid_production(monkeypatch):
    monkeypatch.setattr(ProductionConfig, "APP_ENV", "production")
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "production-secret-value")
    monkeypatch.setattr(ProductionConfig, "AUTH_ENABLED", True)
    monkeypatch.setattr(ProductionConfig, "AUTH_STUB_ENABLED", False)
    monkeypatch.setattr(ProductionConfig, "SESSION_COOKIE_SECURE", True)
    monkeypatch.setattr(ProductionConfig, "SESSION_COOKIE_HTTPONLY", True)
    monkeypatch.setattr(ProductionConfig, "LDAP_HOST", "ldap.example.com")
    monkeypatch.setattr(ProductionConfig, "LDAP_BASE_DN", "DC=example,DC=com")
    monkeypatch.setattr(ProductionConfig, "LDAP_BIND_DN", "CN=bind,DC=example,DC=com")
    monkeypatch.setattr(ProductionConfig, "LDAP_BIND_PASSWORD", "bind-password")
    monkeypatch.setattr(ProductionConfig, "LDAP_GROUP_GATE_ENABLED", False)
    monkeypatch.setattr(ProductionConfig, "ALLOWED_GROUP_DN", "")
    monkeypatch.setattr(
        ProductionConfig, "DATABASE_URL", "mssql+pyodbc://db-server/app"
    )
    monkeypatch.setattr(
        ProductionConfig, "OPENAI_BASE_URL", "https://azure.example.com/openai/v1/"
    )
    monkeypatch.setattr(ProductionConfig, "OPENAI_API_KEY", "test-key")
    monkeypatch.setattr(ProductionConfig, "AZURE_BATCH_MODEL", "batch-prod-deployment")
    monkeypatch.setattr(ProductionConfig, "DOC_TRANSLATE_MODEL", "doc-prod-deployment")
    monkeypatch.setattr(
        ProductionConfig, "PDF_REALTIME_TRANSLATE_MODEL", "realtime-prod-deployment"
    )
    monkeypatch.setattr(ProductionConfig, "WORD_TRANSLATE_MODEL", "word-prod-deployment")
    monkeypatch.setattr(
        ProductionConfig,
        "TABLE_RECOGNTION_V2_URL",
        "https://ocr.example.com/table-recognition",
    )
    monkeypatch.setattr(ProductionConfig, "TRITON_URL", "https://ocr.example.com/table-recognition")
    monkeypatch.setattr(ProductionConfig, "PP_STRUCTURE_URL", "https://ocr.example.com/layout-parsing")


def _disable_runtime_initializers(monkeypatch):
    calls = []

    def record(name):
        def _inner(app):
            calls.append(name)
        return _inner

    monkeypatch.setattr(app_pkg, "init_extensions", record("extensions"))
    monkeypatch.setattr(app_pkg, "register_operations_cli", record("operations_cli"))
    monkeypatch.setattr(app_pkg, "init_auth", record("auth"))
    monkeypatch.setattr(app_pkg, "register_blueprints", record("blueprints"))
    monkeypatch.setattr(app_pkg, "register_error_handlers", record("errors"))
    monkeypatch.setattr(app_pkg, "register_before_request", record("hooks"))
    return calls


def test_production_startup_rejects_development_secret_key(monkeypatch):
    _configure_valid_production(monkeypatch)
    monkeypatch.setattr(ProductionConfig, "SECRET_KEY", "dev-secret")

    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("production")


@pytest.mark.parametrize(
    ("setting", "value", "message"),
    [
        ("AUTH_ENABLED", False, "AUTH_ENABLED"),
        ("AUTH_STUB_ENABLED", True, "AUTH_STUB_ENABLED"),
        ("SESSION_COOKIE_SECURE", False, "SESSION_COOKIE_SECURE"),
        ("SESSION_COOKIE_HTTPONLY", False, "SESSION_COOKIE_HTTPONLY"),
    ],
)
def test_production_startup_rejects_unsafe_auth_and_cookie_settings(
    monkeypatch, setting, value, message
):
    _configure_valid_production(monkeypatch)
    monkeypatch.setattr(ProductionConfig, setting, value)

    with pytest.raises(RuntimeError, match=message):
        create_app("production")


@pytest.mark.parametrize(
    ("setting", "value", "message"),
    [
        ("LDAP_HOST", "", "LDAP_HOST"),
        ("LDAP_BASE_DN", "", "LDAP_BASE_DN"),
        ("LDAP_BIND_DN", "", "LDAP_BIND_DN"),
        ("LDAP_BIND_PASSWORD", "", "LDAP_BIND_PASSWORD"),
    ],
)
def test_production_startup_rejects_incomplete_real_auth_settings(
    monkeypatch, setting, value, message
):
    _configure_valid_production(monkeypatch)
    monkeypatch.setattr(ProductionConfig, setting, value)

    with pytest.raises(RuntimeError, match=message):
        create_app("production")


def test_production_startup_rejects_enabled_group_gate_without_allowed_group(monkeypatch):
    _configure_valid_production(monkeypatch)
    monkeypatch.setattr(ProductionConfig, "LDAP_GROUP_GATE_ENABLED", True)
    monkeypatch.setattr(ProductionConfig, "ALLOWED_GROUP_DN", "")

    with pytest.raises(RuntimeError, match="ALLOWED_GROUP_DN"):
        create_app("production")


@pytest.mark.parametrize(
    ("setting", "value", "message"),
    [
        ("DATABASE_URL", "", "DATABASE_URL"),
        ("DATABASE_URL", "sqlite:///dev.db", "SQL Server"),
        ("OPENAI_BASE_URL", "", "OPENAI_BASE_URL"),
        ("OPENAI_API_KEY", "", "OPENAI_API_KEY"),
        ("AZURE_BATCH_MODEL", "", "AZURE_BATCH_MODEL"),
        ("DOC_TRANSLATE_MODEL", "", "DOC_TRANSLATE_MODEL"),
        ("PDF_REALTIME_TRANSLATE_MODEL", "", "PDF_REALTIME_TRANSLATE_MODEL"),
        ("WORD_TRANSLATE_MODEL", "", "WORD_TRANSLATE_MODEL"),
        ("TABLE_RECOGNTION_V2_URL", "", "TABLE_RECOGNTION_V2_URL"),
        ("PP_STRUCTURE_URL", "", "PP_STRUCTURE_URL"),
    ],
)
def test_production_startup_rejects_missing_external_service_settings(
    monkeypatch, setting, value, message
):
    _configure_valid_production(monkeypatch)
    monkeypatch.setattr(ProductionConfig, setting, value)

    with pytest.raises(RuntimeError, match=message):
        create_app("production")


def test_production_startup_rejects_implicit_default_batch_deployment(monkeypatch):
    _configure_valid_production(monkeypatch)
    monkeypatch.delenv("BATCH_TRANSLATE_DEPLOYMENT", raising=False)
    monkeypatch.delenv("AZURE_BATCH_MODEL", raising=False)
    monkeypatch.setattr(ProductionConfig, "AZURE_BATCH_MODEL", "batch-o3-mini")

    with pytest.raises(RuntimeError, match="AZURE_BATCH_MODEL"):
        create_app("production")


def test_production_startup_allows_explicit_batch_deployment_named_like_default(
    monkeypatch,
):
    _configure_valid_production(monkeypatch)
    _disable_runtime_initializers(monkeypatch)
    monkeypatch.setenv("BATCH_TRANSLATE_DEPLOYMENT", "batch-o3-mini")
    monkeypatch.setattr(ProductionConfig, "AZURE_BATCH_MODEL", "batch-o3-mini")

    app = create_app("production")

    assert app.config["AZURE_BATCH_MODEL"] == "batch-o3-mini"


def test_production_startup_rejects_implicit_default_word_model(monkeypatch):
    _configure_valid_production(monkeypatch)
    monkeypatch.delenv("WORD_TRANSLATE_DEPLOYMENT", raising=False)
    monkeypatch.delenv("WORD_TRANSLATE_MODEL", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_TRANSLATION_DEPLOYMENT", raising=False)
    monkeypatch.delenv("AZURE_OPENAI_CHAT_DEPLOYMENT", raising=False)
    monkeypatch.setattr(ProductionConfig, "WORD_TRANSLATE_MODEL", "gpt-4o-mini")

    with pytest.raises(RuntimeError, match="WORD_TRANSLATE_MODEL"):
        create_app("production")


def test_production_startup_allows_explicit_word_deployment_named_like_default(
    monkeypatch,
):
    _configure_valid_production(monkeypatch)
    _disable_runtime_initializers(monkeypatch)
    monkeypatch.setenv("WORD_TRANSLATE_DEPLOYMENT", "gpt-4o-mini")
    monkeypatch.setattr(ProductionConfig, "WORD_TRANSLATE_MODEL", "gpt-4o-mini")

    app = create_app("production")

    assert app.config["WORD_TRANSLATE_MODEL"] == "gpt-4o-mini"


def test_production_startup_rejects_default_ocr_tunnel_urls(monkeypatch):
    _configure_valid_production(monkeypatch)
    monkeypatch.setattr(
        ProductionConfig,
        "TABLE_RECOGNTION_V2_URL",
        "https://racks-editing-norm-timber.trycloudflare.com/table-recognition",
    )

    with pytest.raises(RuntimeError, match="TABLE_RECOGNTION_V2_URL"):
        create_app("production")


def test_production_startup_rejects_implicit_default_pp_structure_url(monkeypatch):
    _configure_valid_production(monkeypatch)
    monkeypatch.delenv("PP_STRUCTURE_URL", raising=False)
    monkeypatch.delenv("TRITON_LAYOUT_URL", raising=False)
    monkeypatch.setattr(
        ProductionConfig,
        "PP_STRUCTURE_URL",
        "https://writing-coordination-farm-approximately.trycloudflare.com/layout-parsing",
    )

    with pytest.raises(RuntimeError, match="PP_STRUCTURE_URL"):
        create_app("production")


def test_production_startup_rejects_ocr_development_tunnel_endpoint(monkeypatch):
    _configure_valid_production(monkeypatch)
    monkeypatch.setattr(
        ProductionConfig,
        "TABLE_RECOGNTION_V2_URL",
        "https://stale-service.trycloudflare.com/table-recognition",
    )

    with pytest.raises(RuntimeError, match="TABLE_RECOGNTION_V2_URL"):
        create_app("production")


def test_production_startup_allows_explicit_pp_structure_tunnel_endpoint(monkeypatch):
    _configure_valid_production(monkeypatch)
    _disable_runtime_initializers(monkeypatch)
    monkeypatch.setenv(
        "PP_STRUCTURE_URL",
        "https://old-layout.trycloudflare.com/layout-parsing",
    )
    monkeypatch.setattr(
        ProductionConfig,
        "PP_STRUCTURE_URL",
        "https://old-layout.trycloudflare.com/layout-parsing",
    )

    app = create_app("production")

    assert app.config["PP_STRUCTURE_URL"] == (
        "https://old-layout.trycloudflare.com/layout-parsing"
    )


def test_production_startup_has_no_insecure_bypass(monkeypatch):
    _configure_valid_production(monkeypatch)
    monkeypatch.setenv("ALLOW_INSECURE_PRODUCTION", "1")
    monkeypatch.setattr(ProductionConfig, "AUTH_STUB_ENABLED", True)

    with pytest.raises(RuntimeError, match="AUTH_STUB_ENABLED"):
        create_app("production")


def test_valid_production_config_reaches_web_and_worker_initializers(monkeypatch):
    _configure_valid_production(monkeypatch)
    calls = _disable_runtime_initializers(monkeypatch)

    monkeypatch.setenv("APP_RUNTIME_ROLE", "web")
    web_app = create_app("production")
    monkeypatch.setenv("APP_RUNTIME_ROLE", "worker")
    worker_app = create_app("production")

    assert web_app.config["APP_ENV"] == "production"
    assert worker_app.config["APP_ENV"] == "production"
    assert calls == [
        "extensions",
        "operations_cli",
        "auth",
        "blueprints",
        "errors",
        "hooks",
        "extensions",
        "operations_cli",
        "auth",
        "blueprints",
        "errors",
        "hooks",
    ]
