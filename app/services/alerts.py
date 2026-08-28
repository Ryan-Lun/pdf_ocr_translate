from __future__ import annotations

import logging
import socket
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable, Mapping
from urllib.parse import urlsplit

import requests

from . import state

logger = logging.getLogger(__name__)

DEFAULT_TEAMS_ALERT_TIMEOUT_SECONDS = 2.0
DEFAULT_TEAMS_ALERT_DEDUP_SECONDS = 900.0
SAFE_DETAIL_FIELDS = (
    "stage",
    "job_type",
    "path",
    "method",
    "endpoint",
    "worker_id",
    "external_service",
    "deployment",
    "failure_kind",
)


@dataclass(frozen=True)
class AlertResult:
    sent: bool
    reason: str = ""
    status_code: int | None = None
    response_text: str = ""


class AlertDedupCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._sent_at: dict[tuple[str, str, str, str], float] = {}

    def should_send(
        self,
        key: tuple[str, str, str, str],
        *,
        now_ts: float,
        ttl_seconds: float,
    ) -> bool:
        if ttl_seconds <= 0:
            return True
        with self._lock:
            previous_ts = self._sent_at.get(key)
            if previous_ts is not None and now_ts - previous_ts < ttl_seconds:
                return False
            self._sent_at[key] = now_ts
            self._prune(now_ts, ttl_seconds)
            return True

    def _prune(self, now_ts: float, ttl_seconds: float) -> None:
        stale_keys = [
            key
            for key, sent_at in self._sent_at.items()
            if now_ts - sent_at >= ttl_seconds
        ]
        for key in stale_keys:
            self._sent_at.pop(key, None)


_DEFAULT_DEDUP_CACHE = AlertDedupCache()


def send_teams_alert(
    config: Mapping[str, Any],
    *,
    source: str,
    message: str,
    exception_type: str = "",
    job_id: str | None = None,
    detail: Mapping[str, Any] | None = None,
    post: Callable[..., Any] | None = None,
    dedup_cache: AlertDedupCache | None = None,
    now: Callable[[], float] | None = None,
    bypass_dedup: bool = False,
) -> AlertResult:
    if not teams_alert_enabled(config):
        return AlertResult(sent=False, reason="disabled")

    now_fn = now or _default_now
    now_ts = float(now_fn())
    ttl_seconds = _float_config(
        config,
        "TEAMS_ALERT_DEDUP_SECONDS",
        DEFAULT_TEAMS_ALERT_DEDUP_SECONDS,
        minimum=0.0,
    )
    cleaned_source = _clean_text(source) or "unknown"
    cleaned_message = _clean_text(message) or "System error"
    cleaned_exception_type = _clean_text(exception_type)
    cleaned_job_id = _clean_text(job_id)
    cache_key = (
        cleaned_source,
        cleaned_exception_type,
        cleaned_message,
        cleaned_job_id,
    )
    cache = dedup_cache or _DEFAULT_DEDUP_CACHE
    if not bypass_dedup and not cache.should_send(
        cache_key,
        now_ts=now_ts,
        ttl_seconds=ttl_seconds,
    ):
        return AlertResult(sent=False, reason="deduplicated")

    webhook_url = _clean_text(config.get("TEAMS_ALERT_WEBHOOK_URL"))
    payload = build_teams_alert_payload(
        config,
        source=cleaned_source,
        message=cleaned_message,
        exception_type=cleaned_exception_type,
        job_id=cleaned_job_id,
        detail=detail,
        now_ts=now_ts,
    )
    post_fn = post or requests.post
    timeout_seconds = _float_config(
        config,
        "TEAMS_ALERT_TIMEOUT_SECONDS",
        DEFAULT_TEAMS_ALERT_TIMEOUT_SECONDS,
        minimum=0.1,
    )
    try:
        response = post_fn(webhook_url, json=payload, timeout=timeout_seconds)
        status_code = int(getattr(response, "status_code", 0) or 0)
        response_text = _clean_text(getattr(response, "text", ""))[:500]
        if 200 <= status_code <= 299:
            return AlertResult(sent=True, status_code=status_code, response_text=response_text)
        logger.warning(
            "Teams Alert delivery failed status_code=%s response=%s",
            status_code,
            response_text,
        )
        return AlertResult(
            sent=False,
            reason="delivery_failed",
            status_code=status_code,
            response_text=response_text,
        )
    except requests.exceptions.Timeout as exc:
        error_text = _clean_text(f"{type(exc).__name__}: {exc}")[:500]
        logger.warning("Teams Alert delivery timed out error=%s", exc)
        return AlertResult(sent=False, reason="timeout", response_text=error_text)
    except requests.exceptions.RequestException as exc:
        error_text = _clean_text(f"{type(exc).__name__}: {exc}")[:500]
        logger.warning("Teams Alert delivery request failed error=%s", exc)
        return AlertResult(sent=False, reason="request_failed", response_text=error_text)
    except Exception as exc:
        logger.warning("Teams Alert delivery failed error=%s", exc)
        return AlertResult(sent=False, reason="delivery_failed")


def log_startup_warning(config: Mapping[str, Any]) -> None:
    if _bool_config(config, "TEAMS_ALERT_ENABLED", False) and not _clean_text(
        config.get("TEAMS_ALERT_WEBHOOK_URL")
    ):
        logger.warning(
            "Teams Alert is enabled but TEAMS_ALERT_WEBHOOK_URL is empty; "
            "Teams Alert delivery is disabled."
        )


def state_alert_config() -> dict[str, Any]:
    return {
        "TEAMS_ALERT_ENABLED": state.TEAMS_ALERT_ENABLED,
        "TEAMS_ALERT_WEBHOOK_URL": state.TEAMS_ALERT_WEBHOOK_URL,
        "TEAMS_ALERT_TIMEOUT_SECONDS": state.TEAMS_ALERT_TIMEOUT_SECONDS,
        "TEAMS_ALERT_DEDUP_SECONDS": state.TEAMS_ALERT_DEDUP_SECONDS,
        "TEAMS_ALERT_HOST": state.TEAMS_ALERT_HOST,
    }


def teams_alert_enabled(config: Mapping[str, Any]) -> bool:
    return _bool_config(config, "TEAMS_ALERT_ENABLED", False) and bool(
        _clean_text(config.get("TEAMS_ALERT_WEBHOOK_URL"))
    )


def build_teams_alert_payload(
    config: Mapping[str, Any],
    *,
    source: str,
    message: str,
    exception_type: str = "",
    job_id: str | None = None,
    detail: Mapping[str, Any] | None = None,
    now_ts: float | None = None,
) -> dict[str, Any]:
    timestamp = datetime.fromtimestamp(_default_now() if now_ts is None else now_ts)
    payload: dict[str, Any] = {
        "status": "ERROR",
        "host": _clean_text(config.get("TEAMS_ALERT_HOST")) or socket.gethostname(),
        "time": timestamp.strftime("%Y-%m-%d %H:%M:%S"),
        "message": _clean_text(message)[:500],
        "source": _clean_text(source) or "unknown",
        "environment": _clean_text(config.get("APP_ENV")) or "unknown",
    }
    cleaned_job_id = _clean_text(job_id)
    if cleaned_job_id:
        payload["job_id"] = cleaned_job_id
    cleaned_exception_type = _clean_text(exception_type)
    if cleaned_exception_type:
        payload["exception_type"] = cleaned_exception_type
    for field in SAFE_DETAIL_FIELDS:
        value = _clean_text((detail or {}).get(field))
        if not value:
            continue
        if field == "path":
            value = _path_without_query(value)
        if value:
            payload[field] = value
    return payload


def _default_now() -> float:
    return datetime.now().timestamp()


def _bool_config(config: Mapping[str, Any], name: str, default: bool) -> bool:
    value = config.get(name, default)
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    text = str(value).strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "on"}


def _float_config(
    config: Mapping[str, Any],
    name: str,
    default: float,
    *,
    minimum: float,
) -> float:
    value = config.get(name, default)
    try:
        return max(minimum, float(value))
    except (TypeError, ValueError):
        return default


def _clean_text(value: Any) -> str:
    return " ".join(str(value or "").split()).strip()


def _path_without_query(value: str) -> str:
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc:
        return parsed.path
    return value.split("?", 1)[0].split("#", 1)[0]
