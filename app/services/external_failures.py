from __future__ import annotations


def classify_failure_kind(exc: Exception) -> str:
    exc_name = exc.__class__.__name__.lower()
    message = str(exc or "").lower()
    combined = f"{exc_name} {message}"
    if "timeout" in combined or "timed out" in combined:
        return "timeout"
    if "ratelimit" in combined or ("rate" in combined and "limit" in combined):
        return "rate_limit"
    if any(token in combined for token in ("auth", "unauthorized", "forbidden", "401", "403")):
        return "auth"
    if "quota" in combined:
        return "quota"
    if any(token in combined for token in ("request", "connection", "connect", "network")):
        return "request_failed"
    return "unknown"


def openai_system_error_detail(
    *,
    stage: str,
    deployment: str,
    failure_kind: str,
    job_type: str = "pdf_translate",
) -> dict[str, str]:
    return {
        "stage": stage,
        "job_type": job_type,
        "external_service": "openai",
        "deployment": deployment,
        "failure_kind": failure_kind,
    }
