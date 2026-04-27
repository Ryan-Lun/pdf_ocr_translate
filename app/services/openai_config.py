from __future__ import annotations

import os

from openai import AsyncOpenAI, OpenAI


def get_openai_api_key() -> str:
    return (
        os.getenv("OPENAI_API_KEY")
        or os.getenv("AZURE_OPENAI_API_KEY")
        or os.getenv("UO_AZURE_OPENAI_API_KEY")
        or ""
    ).strip()


def get_openai_base_url() -> str:
    endpoint = (
        os.getenv("OPENAI_BASE_URL")
        or os.getenv("AZURE_OPENAI_ENDPOINT")
        or os.getenv("AZURE_OPENAI_BASE_URL")
        or ""
    ).strip().rstrip("/")
    if not endpoint:
        return ""
    if endpoint.endswith("/openai/v1"):
        return f"{endpoint}/"
    return f"{endpoint}/openai/v1/"


def get_batch_translate_deployment() -> str:
    return (
        os.getenv("BATCH_TRANSLATE_DEPLOYMENT")
        or os.getenv("AZURE_BATCH_MODEL")
        or "batch-o3-mini"
    ).strip()


def get_doc_translate_deployment() -> str:
    return (
        os.getenv("DOC_TRANSLATE_DEPLOYMENT")
        or os.getenv("DOC_TRANSLATE_MODEL")
        or "gpt-4.1-mini"
    ).strip()


def get_word_translate_deployment() -> str:
    return (
        os.getenv("WORD_TRANSLATE_DEPLOYMENT")
        or os.getenv("WORD_TRANSLATE_MODEL")
        or os.getenv("AZURE_OPENAI_TRANSLATION_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
        or "gpt-4o-mini"
    ).strip()


def get_word_quality_deployment() -> str:
    return (
        os.getenv("WORD_QUALITY_DEPLOYMENT")
        or os.getenv("WORD_TRANSLATE_QUALITY_MODEL")
        or os.getenv("AZURE_OPENAI_QUALITY_DEPLOYMENT")
        or os.getenv("AZURE_OPENAI_CHAT_DEPLOYMENT")
        or "gpt-4o"
    ).strip()


def create_sync_client() -> OpenAI:
    api_key = get_openai_api_key()
    base_url = get_openai_base_url()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    if not base_url:
        raise RuntimeError("OPENAI_BASE_URL is not configured.")
    return OpenAI(api_key=api_key, base_url=base_url)


def create_async_client() -> AsyncOpenAI:
    api_key = get_openai_api_key()
    base_url = get_openai_base_url()
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY is not configured.")
    if not base_url:
        raise RuntimeError("OPENAI_BASE_URL is not configured.")
    return AsyncOpenAI(api_key=api_key, base_url=base_url)
