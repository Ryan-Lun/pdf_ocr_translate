from __future__ import annotations

import base64
import json
import logging
from pathlib import Path

import fitz
import requests

from . import state

logger = logging.getLogger(__name__)


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


def _request_layout_parsing(image_path: Path) -> dict:
    image_data = base64.b64encode(image_path.read_bytes()).decode("ascii")
    payload = {
        "file": image_data,
        "fileType": 1,
    }
    response = requests.post(state.PP_STRUCTURE_URL, json=payload, timeout=300)
    response.raise_for_status()
    return response.json()


def extract_pdf_to_markdown(
    pdf_path: Path,
    out_dir: Path,
    dpi: int = 150,
) -> tuple[Path, list[Path]]:
    render_dir = out_dir / "rendered"
    images_dir = out_dir / "images"
    out_dir.mkdir(parents=True, exist_ok=True)
    images_dir.mkdir(parents=True, exist_ok=True)

    rendered_pages = render_pdf_pages(pdf_path, render_dir, dpi=dpi)
    markdown_pages: list[str] = []
    pruned_paths: list[Path] = []

    for page_idx, rendered_path in enumerate(rendered_pages):
        logger.info("PP-StructureV3 processing page=%s file=%s", page_idx, rendered_path.name)
        result = _request_layout_parsing(rendered_path).get("result", {}) or {}
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
