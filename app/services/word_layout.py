from __future__ import annotations

REPLACE_ORIGINAL = "replace_original"
BILINGUAL_BELOW = "bilingual_below"
MODES = {REPLACE_ORIGINAL, BILINGUAL_BELOW}


def normalize(value: object) -> str:
    mode = str(value or "").strip().lower()
    if mode in MODES:
        return mode
    return REPLACE_ORIGINAL
