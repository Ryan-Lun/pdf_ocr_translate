from __future__ import annotations

from typing import Optional
from urllib.parse import urlparse



def sanitize_next_url(raw_next: Optional[str]) -> Optional[str]:
    if not raw_next:
        return None
    candidate = str(raw_next).strip()
    if candidate.endswith("?"):
        candidate = candidate[:-1]
    if not candidate.startswith("/") or candidate.startswith("//"):
        return None
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc:
        return None
    return candidate
