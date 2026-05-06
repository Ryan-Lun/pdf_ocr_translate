from __future__ import annotations

import subprocess
from pathlib import Path


def _run_pandoc(args: list[str], cwd: Path | None = None) -> None:
    completed = subprocess.run(
        ["pandoc", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=False,
        cwd=str(cwd) if cwd else None,
    )
    if completed.returncode != 0:
        raise RuntimeError(completed.stderr.strip() or "pandoc export failed")


def export_markdown_to_html(markdown_path: Path, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run_pandoc(
        [
            markdown_path.as_posix(),
            "-f",
            "markdown",
            "-t",
            "html",
            "-o",
            out_path.as_posix(),
        ]
    )
    return out_path


def export_html_to_docx(html_path: Path, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _run_pandoc(
        [
            html_path.name,
            "-f",
            "html",
            "-t",
            "docx",
            "--resource-path",
            ".",
            "-o",
            out_path.as_posix(),
        ],
        cwd=html_path.parent,
    )
    return out_path


def export_markdown_to_docx(markdown_path: Path, out_path: Path, html_path: Path | None = None) -> Path:
    html_output_path = html_path or out_path.with_suffix(".html")
    export_markdown_to_html(markdown_path, html_output_path)
    export_html_to_docx(html_output_path, out_path)
    return out_path
