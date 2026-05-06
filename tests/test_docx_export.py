from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


MODULE_PATH = Path(__file__).resolve().parents[1] / "app" / "services" / "docx_export.py"
SPEC = importlib.util.spec_from_file_location("docx_export_under_test", MODULE_PATH)
assert SPEC and SPEC.loader
docx_export = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(docx_export)


def test_export_markdown_to_docx_goes_through_html(monkeypatch, tmp_path: Path):
    source_md = tmp_path / "doc.md"
    source_md.write_text("| a |\n|---|\n| b |\n", encoding="utf-8")
    html_path = tmp_path / "output.html"
    docx_path = tmp_path / "output.docx"
    calls: list[list[str]] = []

    def fake_run(args, **kwargs):
        calls.append(list(args))
        out_path = Path(args[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("generated", encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(docx_export.subprocess, "run", fake_run)

    result = docx_export.export_markdown_to_docx(source_md, docx_path, html_path=html_path)

    assert result == docx_path
    assert html_path.exists()
    assert docx_path.exists()
    assert calls == [
        [
            "pandoc",
            source_md.as_posix(),
            "-f",
            "markdown",
            "-t",
            "html",
            "-o",
            html_path.as_posix(),
        ],
        [
            "pandoc",
            html_path.name,
            "-f",
            "html",
            "-t",
            "docx",
            "--resource-path",
            ".",
            "-o",
            docx_path.as_posix(),
        ],
    ]


def test_export_html_to_docx_uses_html_parent_as_resource_path(monkeypatch, tmp_path: Path):
    html_dir = tmp_path / "translated"
    html_dir.mkdir(parents=True, exist_ok=True)
    html_path = html_dir / "doc.translated.html"
    html_path.write_text('<img src="images/pic.jpg" />', encoding="utf-8")
    docx_path = tmp_path / "output" / "output.docx"
    captured: list[dict[str, object]] = []

    def fake_run(args, **kwargs):
        captured.append({"args": list(args), "cwd": kwargs.get("cwd")})
        out_path = Path(args[-1])
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text("generated", encoding="utf-8")
        return SimpleNamespace(returncode=0, stderr="", stdout="")

    monkeypatch.setattr(docx_export.subprocess, "run", fake_run)

    result = docx_export.export_html_to_docx(html_path, docx_path)

    assert result == docx_path
    assert captured == [
        {
            "args": [
                "pandoc",
                "doc.translated.html",
                "-f",
                "html",
                "-t",
                "docx",
                "--resource-path",
                ".",
                "-o",
                docx_path.as_posix(),
            ],
            "cwd": str(html_dir),
        }
    ]
