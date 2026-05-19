from __future__ import annotations

import asyncio
import math
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

from . import state


def estimate_text_tokens(text: str) -> int:
    cleaned = str(text or "")
    if not cleaned:
        return 0
    return max(1, math.ceil(len(cleaned) / 4))


def estimate_messages_tokens(messages: list[dict[str, Any]]) -> int:
    total = 0
    for message in messages or []:
        total += estimate_text_tokens(str((message or {}).get("content") or ""))
        total += 6
    return max(1, total)


@dataclass
class _ModelQuotaState:
    rpm_limit: int
    tpm_limit: int
    request_events: deque[tuple[float, int]] = field(default_factory=deque)
    token_events: deque[tuple[float, int]] = field(default_factory=deque)
    header_remaining_requests: int | None = None
    header_remaining_tokens: int | None = None
    header_reset_requests_at: float | None = None
    header_reset_tokens_at: float | None = None
    reserved_requests_since_header: int = 0
    reserved_tokens_since_header: int = 0


class RealtimeRateLimiter:
    def __init__(self) -> None:
        self._lock = threading.Condition()
        self._states: dict[str, _ModelQuotaState] = {}

    def _limits_for_model(self, model_name: str) -> tuple[int, int]:
        cleaned = str(model_name or "").strip()
        if cleaned == state.PDF_REALTIME_TRANSLATE_MODEL:
            return (
                max(1, int(state.PDF_REALTIME_RATE_LIMIT_RPM * state.PDF_REALTIME_RATE_LIMIT_HEADROOM)),
                max(1, int(state.PDF_REALTIME_RATE_LIMIT_TPM * state.PDF_REALTIME_RATE_LIMIT_HEADROOM)),
            )
        return (
            max(1, int(state.DEFAULT_OPENAI_RATE_LIMIT_RPM * state.DEFAULT_OPENAI_RATE_LIMIT_HEADROOM)),
            max(1, int(state.DEFAULT_OPENAI_RATE_LIMIT_TPM * state.DEFAULT_OPENAI_RATE_LIMIT_HEADROOM)),
        )

    def _state_for(self, model_name: str) -> _ModelQuotaState:
        key = str(model_name or "").strip() or "default"
        state_obj = self._states.get(key)
        if state_obj is None:
            rpm_limit, tpm_limit = self._limits_for_model(key)
            state_obj = _ModelQuotaState(rpm_limit=rpm_limit, tpm_limit=tpm_limit)
            self._states[key] = state_obj
        return state_obj

    @staticmethod
    def _prune_events(state_obj: _ModelQuotaState, now_ts: float) -> None:
        cutoff = now_ts - 60.0
        while state_obj.request_events and state_obj.request_events[0][0] <= cutoff:
            state_obj.request_events.popleft()
        while state_obj.token_events and state_obj.token_events[0][0] <= cutoff:
            state_obj.token_events.popleft()
        if state_obj.header_reset_requests_at and now_ts >= state_obj.header_reset_requests_at:
            state_obj.header_remaining_requests = None
            state_obj.header_reset_requests_at = None
            state_obj.reserved_requests_since_header = 0
        if state_obj.header_reset_tokens_at and now_ts >= state_obj.header_reset_tokens_at:
            state_obj.header_remaining_tokens = None
            state_obj.header_reset_tokens_at = None
            state_obj.reserved_tokens_since_header = 0

    @staticmethod
    def _sum_events(events: deque[tuple[float, int]]) -> int:
        return sum(value for _, value in events)

    @staticmethod
    def _header_available(remaining: int | None, reserved: int) -> int | None:
        if remaining is None:
            return None
        return max(0, remaining - reserved)

    def acquire(self, model_name: str, estimated_tokens: int) -> None:
        token_cost = max(1, int(estimated_tokens))
        with self._lock:
            state_obj = self._state_for(model_name)
            while True:
                now_ts = time.time()
                self._prune_events(state_obj, now_ts)
                used_requests = self._sum_events(state_obj.request_events)
                used_tokens = self._sum_events(state_obj.token_events)
                static_available_requests = max(0, state_obj.rpm_limit - used_requests)
                static_available_tokens = max(0, state_obj.tpm_limit - used_tokens)
                header_available_requests = self._header_available(
                    state_obj.header_remaining_requests,
                    state_obj.reserved_requests_since_header,
                )
                header_available_tokens = self._header_available(
                    state_obj.header_remaining_tokens,
                    state_obj.reserved_tokens_since_header,
                )
                available_requests = static_available_requests
                if header_available_requests is not None:
                    available_requests = min(available_requests, header_available_requests)
                available_tokens = static_available_tokens
                if header_available_tokens is not None:
                    available_tokens = min(available_tokens, header_available_tokens)
                if available_requests >= 1 and available_tokens >= token_cost:
                    state_obj.request_events.append((now_ts, 1))
                    state_obj.token_events.append((now_ts, token_cost))
                    if state_obj.header_remaining_requests is not None:
                        state_obj.reserved_requests_since_header += 1
                    if state_obj.header_remaining_tokens is not None:
                        state_obj.reserved_tokens_since_header += token_cost
                    self._lock.notify_all()
                    return

                wait_seconds = 0.5
                candidates = []
                if state_obj.request_events:
                    candidates.append(max(0.05, state_obj.request_events[0][0] + 60.0 - now_ts))
                if state_obj.token_events:
                    candidates.append(max(0.05, state_obj.token_events[0][0] + 60.0 - now_ts))
                if state_obj.header_reset_requests_at:
                    candidates.append(max(0.05, state_obj.header_reset_requests_at - now_ts))
                if state_obj.header_reset_tokens_at:
                    candidates.append(max(0.05, state_obj.header_reset_tokens_at - now_ts))
                if candidates:
                    wait_seconds = min(candidates)
                self._lock.wait(timeout=min(wait_seconds, 5.0))

    async def acquire_async(self, model_name: str, estimated_tokens: int) -> None:
        await asyncio.to_thread(self.acquire, model_name, estimated_tokens)

    def update_from_headers(self, model_name: str, headers: Any) -> None:
        if headers is None:
            return
        with self._lock:
            state_obj = self._state_for(model_name)
            now_ts = time.time()
            self._prune_events(state_obj, now_ts)

            remaining_requests = _parse_header_int(headers, "x-ratelimit-remaining-requests")
            remaining_tokens = _parse_header_int(headers, "x-ratelimit-remaining-tokens")
            reset_requests = _parse_header_seconds(headers, "x-ratelimit-reset-requests")
            reset_tokens = _parse_header_seconds(headers, "x-ratelimit-reset-tokens")

            if remaining_requests is not None:
                state_obj.header_remaining_requests = remaining_requests
                state_obj.reserved_requests_since_header = 0
                state_obj.header_reset_requests_at = now_ts + reset_requests if reset_requests is not None else now_ts + 60.0
            if remaining_tokens is not None:
                state_obj.header_remaining_tokens = remaining_tokens
                state_obj.reserved_tokens_since_header = 0
                state_obj.header_reset_tokens_at = now_ts + reset_tokens if reset_tokens is not None else now_ts + 60.0
            self._lock.notify_all()


def _parse_header_int(headers: Any, name: str) -> int | None:
    try:
        value = headers.get(name) if hasattr(headers, "get") else None
    except Exception:
        value = None
    if value is None:
        return None
    try:
        return max(0, int(float(str(value).strip())))
    except (TypeError, ValueError):
        return None


def _parse_header_seconds(headers: Any, name: str) -> float | None:
    try:
        value = headers.get(name) if hasattr(headers, "get") else None
    except Exception:
        value = None
    if value is None:
        return None
    text = str(value).strip().lower()
    try:
        return max(0.0, float(text))
    except ValueError:
        pass
    match = None
    import re

    match = re.fullmatch(r"(\d+(?:\.\d+)?)(ms|s|m)?", text)
    if not match:
        return None
    number = float(match.group(1))
    unit = match.group(2) or "s"
    if unit == "ms":
        return max(0.0, number / 1000.0)
    if unit == "m":
        return max(0.0, number * 60.0)
    return max(0.0, number)


REALTIME_RATE_LIMITER = RealtimeRateLimiter()
