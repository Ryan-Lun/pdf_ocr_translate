from __future__ import annotations

import base64
import json
import logging
import random
import time
from pathlib import Path
from typing import Callable

import fitz
import requests

from . import state

logger = logging.getLogger(__name__)
PP_STRUCTURE_MAX_RETRIES = 3


def _format_pp_structure_error(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    lowered = message.lower()
    exc_name = exc.__class__.__name__.lower()
    if isinstance(exc, requests.exceptions.Timeout) or "timed out" in lowered or "timeout" in exc_name:
        return f"Request timed out. (read timeout={state.PP_STRUCTURE_TIMEOUT_SECONDS:g}s)"
    if "connectionpool(" in lowered:
        return "API connection failed."
    return message


def render_pdf_pages(pdf_path: Path, out_dir: Path, dpi: int = 150) -> list[Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    scale = max(1.0, float(dpi) / 72.0)
    matrix = fitz.Matrix(scale, scale)
    doc = fitz.open(pdf_path)
    image_paths: list[Path] = []
    try:
        for page_idx in range(doc.page_count):
            page = doc.load_page(page_idx)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            out_path = out_dir / f"page_{page_idx + 1:04d}.png"
            pix.save(out_path.as_posix())
            image_paths.append(out_path)
    finally:
        doc.close()
    return image_paths


def _request_layout_parsing(
    image_path: Path,
    *,
    page_number: int | None = None,
    failure_counter: dict[str, int] | None = None,
    warning_callback: Callable[[str], None] | None = None,
) -> dict:
    image_data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload = {
        "file": image_data,
        "fileType": 1,
    }
    for attempt in range(PP_STRUCTURE_MAX_RETRIES):
        try:
            response = requests.post(
                state.PP_STRUCTURE_URL,
                json=payload,
                timeout=state.PP_STRUCTURE_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            return response.json()
        except Exception as exc:
            logger.warning("PP structure attempt failed attempt=%s error=%s", attempt + 1, exc)
            error_detail = _format_pp_structure_error(exc)
            page_prefix = f"第 {page_number} 頁" if page_number is not None else ""
            if failure_counter is not None:
                failure_counter["count"] = int(failure_counter.get("count") or 0) + 1
                total_failures = failure_counter["count"]
                total_suffix = f"（累計 {total_failures}/{PP_STRUCTURE_MAX_RETRIES}）"
            else:
                total_failures = attempt + 1
                total_suffix = ""
            if warning_callback is not None:
                warning_callback(f"{page_prefix}第 {attempt + 1} 次 PDF 重建結構 API 請求失敗{total_suffix}：{error_detail}")
            if total_failures >= PP_STRUCTURE_MAX_RETRIES:
                failure_scope = "累計" if failure_counter is not None else "連續"
                raise RuntimeError(
                    f"PDF 重建結構 API 請求{failure_scope}失敗 {PP_STRUCTURE_MAX_RETRIES} 次，已中斷任務：{error_detail} 請向系統管理員回報此問題。"
                ) from exc
            time.sleep((2**attempt) + random.uniform(0, 0.5))


def extract_pdf_to_markdown(
    pdf_path: Path,
    out_dir: Path,
    dpi: int = 150,
    warning_callback: Callable[[str], None] | None = None,
) -> tuple[Path, list[Path]]:
    render_dir = out_dir / "rendered"
    images_dir = out_dir / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    rendered_pages = render_pdf_pages(pdf_path, render_dir, dpi=dpi)
    markdown_pages: list[str] = []
    pruned_paths: list[Path] = []
    failure_counter = {"count": 0}

    for page_idx, rendered_path in enumerate(rendered_pages):
        logger.info("PP-StructureV3 processing page=%s file=%s", page_idx, rendered_path.name)
        result = _request_layout_parsing(
            rendered_path,
            page_number=page_idx + 1,
            failure_counter=failure_counter,
            warning_callback=warning_callback,
        ).get("result", {}) or {}
        layout_results = result.get("layoutParsingResults") or []
        if not layout_results:
            markdown_pages.append("")
            continue

        page_result = layout_results[0]
        pruned = page_result.get("prunedResult")
        pruned_path = out_dir / f"pruned_result_page_{page_idx}.json"
        pruned_path.write_text(
            json.dumps(pruned, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        pruned_paths.append(pruned_path)

        markdown = page_result.get("markdown") or {}
        page_md = str(markdown.get("text") or "")
        page_images = markdown.get("images") or {}
        for original_rel, image_b64 in page_images.items():
            original_name = Path(original_rel).name or f"image_{len(page_images)}.png"
            new_rel = Path("images") / f"page_{page_idx + 1:04d}" / original_name
            abs_path = out_dir / new_rel
            abs_path.parent.mkdir(parents=True, exist_ok=True)
            abs_path.write_bytes(base64.b64decode(image_b64))
            page_md = page_md.replace(original_rel, new_rel.as_posix())
        markdown_pages.append(page_md.strip())

    markdown_path = out_dir / "doc.md"
    markdown_path.write_text(
        "\n\n".join(page for page in markdown_pages if page),
        encoding="utf-8",
    )
    return markdown_path, pruned_paths
