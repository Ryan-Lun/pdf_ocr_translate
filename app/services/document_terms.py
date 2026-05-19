from __future__ import annotations

import re
from typing import Any

from . import translation_memory

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3040-\u309F\u30A0-\u30FF]")
_SENTENCE_PUNCT_RE = re.compile(r"[。；;!?！？]")
_TRAILING_COLON_RE = re.compile(r"[:：]\s*$")
_NUMBER_PREFIX_RE = re.compile(
    r"^\s*(?:\d+[.)、]\s*|\(\d+\)\s*|[A-Za-z][.)]\s*|\([A-Za-z]\)\s*|[一二三四五六七八九十]+[、.]\s*)"
)


def normalize_term_key(text: str | None) -> str:
    normalized = translation_memory.normalize_source_text(text)
    if not normalized:
        return ""
    normalized = _TRAILING_COLON_RE.sub("", normalized).strip()
    return normalized


def _strip_for_scoring(text: str) -> str:
    normalized = translation_memory.normalize_source_text(text)
    if not normalized:
        return ""
    normalized = _NUMBER_PREFIX_RE.sub("", normalized)
    normalized = _TRAILING_COLON_RE.sub("", normalized)
    return normalized.strip()


def _looks_like_short_label(text: str) -> bool:
    stripped = _strip_for_scoring(text)
    if not stripped:
        return False
    if not _CJK_RE.search(stripped):
        return False
    if len(stripped) < 2 or len(stripped) > 24:
        return False
    if len(stripped.splitlines()) > 2:
        return False
    if _SENTENCE_PUNCT_RE.search(stripped):
        return False
    if stripped.count(",") + stripped.count("，") > 1:
        return False
    compact = re.sub(r"\s+", "", stripped)
    if not compact:
        return False
    digits = sum(ch.isdigit() for ch in compact)
    symbols = sum(not ch.isalnum() and not _CJK_RE.fullmatch(ch) for ch in compact)
    if (digits + symbols) / max(1, len(compact)) > 0.35:
        return False
    return True


def _score_candidate(
    text: str,
    *,
    source_type: str,
    label: str,
    occurrences: int,
) -> int:
    score = 0
    stripped = _strip_for_scoring(text)
    compact = re.sub(r"\s+", "", stripped)

    if source_type == "merged_cell":
        score += 35
    if label in {"header", "figure_title"}:
        score += 20
    if occurrences >= 2:
        score += 15
    if 2 <= len(compact) <= 12:
        score += 10
    if text.rstrip().endswith((":", "：")):
        score += 10
    if len(compact) > 20:
        score -= 25
    if _SENTENCE_PUNCT_RE.search(stripped):
        score -= 25
    if stripped.count(" ") >= 4:
        score -= 20

    digits = sum(ch.isdigit() for ch in compact)
    symbols = sum(not ch.isalnum() and not _CJK_RE.fullmatch(ch) for ch in compact)
    if (digits + symbols) / max(1, len(compact)) > 0.35:
        score -= 30
    return score


def _iter_raw_candidates(pp_pages: dict[int, dict[str, Any]] | None):
    for pp_page in (pp_pages or {}).values():
        if not isinstance(pp_page, dict):
            continue
        for table in pp_page.get("table_res_list", []) or []:
            if not isinstance(table, dict):
                continue
            for cell in table.get("merged_cells", []) or []:
                if not isinstance(cell, dict):
                    continue
                text = str(cell.get("merged_text") or "").strip()
                if not text or not bool(cell.get("should_translate")):
                    continue
                yield {
                    "text": text,
                    "source_type": "merged_cell",
                    "label": "merged_cell",
                }
        for block in pp_page.get("parsing_res_list", []) or []:
            if not isinstance(block, dict):
                continue
            label = str(block.get("block_label") or "").strip().lower()
            if label not in {"header", "figure_title"}:
                continue
            text = str(block.get("block_content") or "").strip()
            if not text or not bool(block.get("should_translate")):
                continue
            yield {
                "text": text,
                "source_type": "structured_block",
                "label": label,
            }


def build_document_term_map(
    pp_pages: dict[int, dict[str, Any]] | None,
    *,
    minimum_score: int = 55,
) -> dict[str, dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}

    for candidate in _iter_raw_candidates(pp_pages):
        text = str(candidate["text"] or "").strip()
        if not _looks_like_short_label(text):
            continue
        canonical_key = normalize_term_key(text)
        if not canonical_key:
            continue
        entry = grouped.setdefault(
            canonical_key,
            {
                "canonical_key": canonical_key,
                "occurrences": 0,
                "variants": {},
                "source_types": set(),
                "labels": set(),
            },
        )
        entry["occurrences"] += 1
        entry["source_types"].add(str(candidate["source_type"]))
        entry["labels"].add(str(candidate["label"]))
        variants = entry["variants"]
        variants[text] = int(variants.get(text, 0)) + 1

    result: dict[str, dict[str, Any]] = {}
    for canonical_key, entry in grouped.items():
        occurrences = int(entry["occurrences"])
        source_type = "merged_cell" if "merged_cell" in entry["source_types"] else "structured_block"
        label = "header" if "header" in entry["labels"] else "figure_title" if "figure_title" in entry["labels"] else source_type
        variant_items = list(entry["variants"].items())
        best_source_text = min(
            variant_items,
            key=lambda item: (
                item[0].rstrip().endswith((":", "：")),
                len(_strip_for_scoring(item[0])),
                -item[1],
                item[0],
            ),
        )[0]
        score = _score_candidate(
            best_source_text,
            source_type=source_type,
            label=label,
            occurrences=occurrences,
        )
        if score < minimum_score:
            continue
        result[canonical_key] = {
            "canonical_key": canonical_key,
            "best_source_text": best_source_text,
            "occurrences": occurrences,
            "score": score,
            "source_types": sorted(str(item) for item in entry["source_types"]),
            "labels": sorted(str(item) for item in entry["labels"]),
        }
    return result


def lookup_document_term(
    text: str | None,
    term_map: dict[str, dict[str, Any]] | None,
) -> dict[str, Any] | None:
    canonical_key = normalize_term_key(text)
    if not canonical_key:
        return None
    return (term_map or {}).get(canonical_key)


def restore_term_surface(source_text: str | None, translated_text: str | None) -> str:
    source = str(source_text or "").rstrip()
    translated = str(translated_text or "").rstrip()
    if not translated:
        return translated
    if not _looks_like_short_label(source):
        return translated
    if source.endswith((":", "：")) and not translated.endswith(":"):
        return f"{translated}:"
    return translated
