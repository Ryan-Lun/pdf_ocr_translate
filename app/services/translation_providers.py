from __future__ import annotations

CLOUD_TRANSLATION_PROVIDER = "cloud"
LOCAL_TRANSLATION_PROVIDER = "local"

_SUPPORTED_TRANSLATION_PROVIDERS = {
    CLOUD_TRANSLATION_PROVIDER,
    LOCAL_TRANSLATION_PROVIDER,
}


def normalize_translation_provider(value: object) -> str:
    provider = str(value or "").strip().lower() or CLOUD_TRANSLATION_PROVIDER
    if provider not in _SUPPORTED_TRANSLATION_PROVIDERS:
        raise ValueError("Unsupported Translation Provider.")
    return provider


def word_translation_provider_is_available(
    provider: object,
    *,
    local_enabled: bool,
) -> bool:
    normalized = normalize_translation_provider(provider)
    return (
        normalized == CLOUD_TRANSLATION_PROVIDER
        or (
            normalized == LOCAL_TRANSLATION_PROVIDER
            and local_enabled
        )
    )


def local_word_language_direction_is_supported(
    source_lang: object,
    target_lang: object,
) -> bool:
    normalized_source = str(source_lang or "auto").strip().lower() or "auto"
    normalized_target = str(target_lang or "en").strip().lower() or "en"
    return (
        normalized_source in {"auto", "zh", "zh-tw", "zh-hant"}
        and normalized_target == "en"
    )


def local_word_request_extra_body(*, enable_thinking: bool) -> dict[str, object]:
    return {
        "chat_template_kwargs": {
            "enable_thinking": bool(enable_thinking),
        }
    }


def word_translation_model_snapshot(
    provider: object,
    *,
    cloud_model: object,
    local_model: object,
) -> str:
    normalized = normalize_translation_provider(provider)
    selected = (
        local_model
        if normalized == LOCAL_TRANSLATION_PROVIDER
        else cloud_model
    )
    return str(selected or "").strip()
