from __future__ import annotations

import threading
import time
from collections import deque

from . import state

_LOCK = threading.Lock()
_SUBMISSIONS: dict[str, deque[float]] = {}


def normalize_submitter_key(creator_name: str | None, remote_addr: str | None) -> str:
    creator = " ".join(str(creator_name or "").split()).strip()
    if creator:
        return f"creator:{creator.lower()}"
    remote = str(remote_addr or "").strip() or "unknown"
    return f"ip:{remote}"


def check_and_record_submission(
    creator_name: str | None,
    remote_addr: str | None,
) -> tuple[bool, int, float]:
    limit = max(1, int(state.USER_SUBMISSIONS_PER_MINUTE))
    now_ts = time.time()
    cutoff = now_ts - 60.0
    key = normalize_submitter_key(creator_name, remote_addr)
    with _LOCK:
        events = _SUBMISSIONS.setdefault(key, deque())
        while events and events[0] <= cutoff:
            events.popleft()
        if len(events) >= limit:
            retry_after = max(1.0, 60.0 - (now_ts - events[0])) if events else 60.0
            return False, limit, retry_after
        events.append(now_ts)
        return True, limit, 0.0
