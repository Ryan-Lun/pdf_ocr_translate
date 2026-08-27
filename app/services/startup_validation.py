from __future__ import annotations

import os
from typing import Any
from urllib.parse import urlsplit


DEFAULT_TABLE_RECOGNTION_V2_URL = (
    "https://racks-editing-norm-timber.trycloudflare.com/table-recognition"
)
DEFAULT_PP_STRUCTURE_URL = (
    "https://writing-coordination-farm-approximately.trycloudflare.com/layout-parsing"
)
DEFAULT_BATCH_TRANSLATE_DEPLOYMENT = "batch-o3-mini"
DEFAULT_WORD_TRANSLATE_MODEL = "gpt-4o-mini"


def _clean(value: object) -> str:
    return str(value or "").strip()


def _is_production(config: Any) -> bool:
    return _clean(config.get("APP_ENV")).lower() == "production"


def _is_enabled(config: Any, key: str) -> bool:
    return bool(config.get(key, False))


def _has_explicit_env(*keys: str) -> bool:
    return any(_clean(os.getenv(key)) for key in keys)


def _is_development_endpoint(value: str) -> bool:
    hostname = (urlsplit(value).hostname or "").lower()
    return hostname == "trycloudflare.com" or hostname.endswith(".trycloudflare.com")


def validate_startup_config(config: Any) -> None:
    """Validate startup configuration shared by web and worker processes."""

    if not _is_production(config):
        return

    errors: list[str] = []

    secret_key = _clean(config.get("SECRET_KEY"))
    if not secret_key or secret_key == "dev-secret":
        errors.append("SECRET_KEY must be set to a production value.")

    if not _is_enabled(config, "AUTH_ENABLED"):
        errors.append("AUTH_ENABLED must be true in production.")
    if _is_enabled(config, "AUTH_STUB_ENABLED"):
        errors.append("AUTH_STUB_ENABLED must be false in production.")
    if not _is_enabled(config, "SESSION_COOKIE_SECURE"):
        errors.append("SESSION_COOKIE_SECURE must be true in production.")
    if not bool(config.get("SESSION_COOKIE_HTTPONLY", False)):
        errors.append("SESSION_COOKIE_HTTPONLY must be true in production.")

    for key in ("LDAP_HOST", "LDAP_BASE_DN", "LDAP_BIND_DN", "LDAP_BIND_PASSWORD"):
        if not _clean(config.get(key)):
            errors.append(f"{key} is required when production authentication is enabled.")
    if _is_enabled(config, "LDAP_GROUP_GATE_ENABLED") and not _clean(
        config.get("ALLOWED_GROUP_DN")
    ):
        errors.append("ALLOWED_GROUP_DN is required when LDAP_GROUP_GATE_ENABLED is true.")

    database_url = _clean(config.get("DATABASE_URL"))
    if not database_url:
        errors.append("DATABASE_URL is required in production.")
    elif not database_url.lower().startswith("mssql"):
        errors.append("DATABASE_URL must point to SQL Server in production.")

    if not _clean(config.get("OPENAI_BASE_URL")):
        errors.append("OPENAI_BASE_URL is required in production.")
    if not _clean(config.get("OPENAI_API_KEY")):
        errors.append("OPENAI_API_KEY is required in production.")
    for key in (
        "AZURE_BATCH_MODEL",
        "DOC_TRANSLATE_MODEL",
        "PDF_REALTIME_TRANSLATE_MODEL",
        "WORD_TRANSLATE_MODEL",
    ):
        if not _clean(config.get(key)):
            errors.append(f"{key} is required in production.")
    if _clean(config.get("AZURE_BATCH_MODEL")) == DEFAULT_BATCH_TRANSLATE_DEPLOYMENT:
        if not _has_explicit_env("BATCH_TRANSLATE_DEPLOYMENT", "AZURE_BATCH_MODEL"):
            errors.append(
                "AZURE_BATCH_MODEL must not use the implicit development default in production."
            )
    if _clean(config.get("WORD_TRANSLATE_MODEL")) == DEFAULT_WORD_TRANSLATE_MODEL:
        if not _has_explicit_env(
            "WORD_TRANSLATE_DEPLOYMENT",
            "WORD_TRANSLATE_MODEL",
            "AZURE_OPENAI_TRANSLATION_DEPLOYMENT",
            "AZURE_OPENAI_CHAT_DEPLOYMENT",
        ):
            errors.append(
                "WORD_TRANSLATE_MODEL must not use the implicit development default in production."
            )

    table_url = _clean(config.get("TABLE_RECOGNTION_V2_URL"))
    if not table_url:
        errors.append("TABLE_RECOGNTION_V2_URL is required in production.")
    elif table_url.rstrip("/") == DEFAULT_TABLE_RECOGNTION_V2_URL.rstrip("/"):
        errors.append(
            "TABLE_RECOGNTION_V2_URL must not use the development tunnel default in production."
        )
    elif _is_development_endpoint(table_url):
        errors.append(
            "TABLE_RECOGNTION_V2_URL must not use a development tunnel endpoint in production."
        )

    pp_structure_url = _clean(config.get("PP_STRUCTURE_URL"))
    if not pp_structure_url:
        errors.append("PP_STRUCTURE_URL is required in production.")
    elif pp_structure_url.rstrip("/") == DEFAULT_PP_STRUCTURE_URL.rstrip("/"):
        errors.append(
            "PP_STRUCTURE_URL must not use the development tunnel default in production."
        )
    elif _is_development_endpoint(pp_structure_url):
        errors.append(
            "PP_STRUCTURE_URL must not use a development tunnel endpoint in production."
        )

    if errors:
        raise RuntimeError(
            "Invalid production startup configuration: " + "; ".join(errors)
        )
