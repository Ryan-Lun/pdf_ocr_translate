from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable


CSV_COLUMNS = [
    "page",
    "number",
    "cn",
    "en",
    "raw_text",
    "source_file",
    "source_format",
    "confidence",
    "x0",
    "y0",
    "x1",
    "y1",
]

PAGE_PATTERN = re.compile(r"_p(?P<page>\d+)\.json$", re.IGNORECASE)
SECTION_NUMBER_PATTERN = r"(?:\d+\.|\d+\.\d+(?:\.\d+)*\.?)"
NUMBER_ONLY_PATTERN = re.compile(rf"^\s*(?P<number>{SECTION_NUMBER_PATTERN})\s*$")
NUMBERED_HEADING_PATTERN = re.compile(
    r"(?:^|\s)"
    rf"(?P<number>{SECTION_NUMBER_PATTERN})"
    r"\s*"
    r"(?P<cn>[\u3400-\u9fff][^()\r\n]*?)"
    r"\s*[\(（]"
    r"(?P<en>[^()（）]+?)"
    r"[\)）]"
    r"\s*[:：]?"
)
HEADING_WITHOUT_NUMBER_PATTERN = re.compile(
    r"^\s*"
    r"(?P<cn>[\u3400-\u9fff][^()\r\n]*?)"
    r"\s*[\(（]"
    r"(?P<en>[^()（）]+?)"
    r"[\)）]"
    r"\s*[:：]?"
)


@dataclass(frozen=True)
class OcrItem:
    text: str
    index: int
    page: int | None = None
    x0: int | None = None
    y0: int | None = None
    x1: int | None = None
    y1: int | None = None


@dataclass(frozen=True)
class HeadingCandidate:
    page: int | None
    number: str
    cn: str
    en: str
    raw_text: str
    source_file: str
    source_format: str
    confidence: str
    x0: int | None = None
    y0: int | None = None
    x1: int | None = None
    y1: int | None = None


def parse_excluded_pages(value: str | None) -> set[int]:
    if not value:
        return set()
    pages: set[int] = set()
    for raw_part in value.split(","):
        part = raw_part.strip()
        if not part:
            continue
        try:
            page = int(part)
        except ValueError as exc:
            raise argparse.ArgumentTypeError(f"invalid page number: {part}") from exc
        if page <= 0:
            raise argparse.ArgumentTypeError(f"page number must be positive: {part}")
        pages.add(page)
    return pages


def parse_page_number(path: Path) -> int | None:
    match = PAGE_PATTERN.search(path.name)
    if not match:
        return None
    return int(match.group("page"))


def _clean_cn(value: str) -> str:
    return value.strip(" \t\r\n:：")


def _clean_en(value: str) -> str:
    return " ".join(value.strip(" \t\r\n:：").split())


def _bbox_from_poly(poly: Any) -> tuple[int | None, int | None, int | None, int | None]:
    if not isinstance(poly, list) or not poly:
        return None, None, None, None
    points: list[tuple[float, float]] = []
    for point in poly:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                points.append((float(point[0]), float(point[1])))
            except (TypeError, ValueError):
                continue
    if not points:
        return None, None, None, None
    xs = [point[0] for point in points]
    ys = [point[1] for point in points]
    return round(min(xs)), round(min(ys)), round(max(xs)), round(max(ys))


def _combine_bbox(items: Iterable[OcrItem]) -> tuple[int | None, int | None, int | None, int | None]:
    x0s: list[int] = []
    y0s: list[int] = []
    x1s: list[int] = []
    y1s: list[int] = []
    for item in items:
        if item.x0 is not None:
            x0s.append(item.x0)
        if item.y0 is not None:
            y0s.append(item.y0)
        if item.x1 is not None:
            x1s.append(item.x1)
        if item.y1 is not None:
            y1s.append(item.y1)
    if not x0s or not y0s or not x1s or not y1s:
        return None, None, None, None
    return min(x0s), min(y0s), max(x1s), max(y1s)


def _bbox_from_opendataloader_box(box: Any) -> tuple[int | None, int | None, int | None, int | None]:
    if not isinstance(box, list) or len(box) < 4:
        return None, None, None, None
    try:
        return round(float(box[0])), round(float(box[1])), round(float(box[2])), round(float(box[3]))
    except (TypeError, ValueError):
        return None, None, None, None


def _flatten_opendataloader_items(payload: Any) -> list[OcrItem]:
    items: list[OcrItem] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            content = node.get("content")
            if isinstance(content, str) and content.strip():
                x0, y0, x1, y1 = _bbox_from_opendataloader_box(node.get("bounding box"))
                raw_page = node.get("page number")
                page = raw_page if isinstance(raw_page, int) else None
                items.append(
                    OcrItem(
                        text=content.strip(),
                        index=len(items),
                        page=page,
                        x0=x0,
                        y0=y0,
                        x1=x1,
                        y1=y1,
                    )
                )
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(payload)
    return items


def _load_ocr_items(path: Path) -> tuple[list[OcrItem], str]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, dict):
        ocr_result = payload.get("overall_ocr_res")
        if isinstance(ocr_result, dict) and "rec_texts" in ocr_result:
            texts = ocr_result.get("rec_texts", [])
            polys = ocr_result.get("rec_polys") or ocr_result.get("dt_polys") or []
            if not isinstance(texts, list):
                raise ValueError(f"{path} overall_ocr_res.rec_texts must be a list")

            page = parse_page_number(path)
            items: list[OcrItem] = []
            for index, raw_text in enumerate(texts):
                text = str(raw_text).strip()
                if not text:
                    continue
                x0, y0, x1, y1 = _bbox_from_poly(polys[index] if index < len(polys) else None)
                items.append(OcrItem(text=text, index=index, page=page, x0=x0, y0=y0, x1=x1, y1=y1))
            return items, "paddleocr_pp_json"
        if "kids" in payload:
            return _flatten_opendataloader_items(payload), "opendataloader_json"
    raise ValueError(f"{path} is not a supported pp_json or opendataloader JSON file")


def _is_same_row(left: OcrItem, right: OcrItem) -> bool:
    if left.y0 is None or left.y1 is None or right.y0 is None or right.y1 is None:
        return right.index == left.index + 1
    left_center = (left.y0 + left.y1) / 2
    right_center = (right.y0 + right.y1) / 2
    left_height = max(1, left.y1 - left.y0)
    right_height = max(1, right.y1 - right.y0)
    return abs(left_center - right_center) <= max(left_height, right_height, 24) * 0.75


def _is_to_the_right(left: OcrItem, right: OcrItem) -> bool:
    if left.x0 is None or right.x0 is None:
        return right.index == left.index + 1
    return right.x0 >= left.x0


def _candidate_from_match(
    *,
    page: int | None,
    source_file: Path,
    source_format: str,
    raw_text: str,
    number: str,
    cn: str,
    en: str,
    items: Iterable[OcrItem],
) -> HeadingCandidate:
    x0, y0, x1, y1 = _combine_bbox(items)
    return HeadingCandidate(
        page=page,
        number=number.strip(),
        cn=_clean_cn(cn),
        en=_clean_en(en),
        raw_text=" ".join(raw_text.split()),
        source_file=str(source_file),
        source_format=source_format,
        confidence="high",
        x0=x0,
        y0=y0,
        x1=x1,
        y1=y1,
    )


def extract_candidates_from_file(path: Path) -> list[HeadingCandidate]:
    file_page = parse_page_number(path)
    items, source_format = _load_ocr_items(path)
    candidates: list[HeadingCandidate] = []
    used_indexes: set[int] = set()

    for position, item in enumerate(items):
        if item.index in used_indexes:
            continue
        matches = list(NUMBERED_HEADING_PATTERN.finditer(item.text))
        if matches:
            for match in matches:
                candidates.append(
                    _candidate_from_match(
                        page=item.page or file_page,
                        source_file=path,
                        source_format=source_format,
                        raw_text=item.text,
                        number=match.group("number"),
                        cn=match.group("cn"),
                        en=match.group("en"),
                        items=[item],
                    )
                )
            used_indexes.add(item.index)
            continue

        number_match = NUMBER_ONLY_PATTERN.match(item.text)
        if not number_match or position + 1 >= len(items):
            continue
        next_item = items[position + 1]
        heading_match = HEADING_WITHOUT_NUMBER_PATTERN.match(next_item.text)
        if (
            not heading_match
            or item.page != next_item.page
            or not _is_same_row(item, next_item)
            or not _is_to_the_right(item, next_item)
        ):
            continue
        raw_text = f"{item.text} {next_item.text}"
        candidates.append(
            _candidate_from_match(
                page=item.page or file_page,
                source_file=path,
                source_format=source_format,
                raw_text=raw_text,
                number=number_match.group("number"),
                cn=heading_match.group("cn"),
                en=heading_match.group("en"),
                items=[item, next_item],
            )
        )
        used_indexes.add(item.index)
        used_indexes.add(next_item.index)

    return candidates


def iter_pp_json_files(path: Path, *, exclude_pages: set[int] | None = None) -> list[Path]:
    exclude_pages = exclude_pages or set()
    if not path.exists():
        raise ValueError(f"input path does not exist: {path}")
    if path.is_file():
        candidates = [path]
    else:
        candidates = sorted(candidate for candidate in path.rglob("*.json") if candidate.is_file())
    return [
        candidate
        for candidate in candidates
        if parse_page_number(candidate) not in exclude_pages
    ]


def extract_candidates(path: Path, *, exclude_pages: set[int] | None = None) -> list[HeadingCandidate]:
    candidates: list[HeadingCandidate] = []
    for file_path in iter_pp_json_files(path, exclude_pages=exclude_pages):
        candidates.extend(extract_candidates_from_file(file_path))
    return candidates


def write_csv(path: Path, candidates: list[HeadingCandidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8-sig") as handle:
        writer = csv.DictWriter(handle, fieldnames=CSV_COLUMNS)
        writer.writeheader()
        for candidate in candidates:
            writer.writerow(asdict(candidate))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Extract bilingual numbered-heading glossary candidates from PaddleOCR pp_json or opendataloader JSON files."
    )
    parser.add_argument("pp_json_path", type=Path, help="A pp_json/opendataloader directory or a single JSON file.")
    parser.add_argument("--output", "-o", type=Path, required=True, help="CSV output path.")
    parser.add_argument(
        "--exclude-pages",
        type=parse_excluded_pages,
        default=None,
        help="Comma-separated page numbers to skip, for example: 1,7.",
    )
    args = parser.parse_args(argv)

    try:
        exclude_pages = args.exclude_pages or set()
        candidates = extract_candidates(args.pp_json_path, exclude_pages=exclude_pages)
        write_csv(args.output, candidates)
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(f"numbered_heading_glossary_extract_error error={exc}", file=sys.stderr)
        return 1

    print(
        "numbered_heading_glossary_extract "
        f"input={args.pp_json_path} "
        f"output={args.output} "
        f"files={len(iter_pp_json_files(args.pp_json_path, exclude_pages=exclude_pages))} "
        f"candidates={len(candidates)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
