from __future__ import annotations

from pathlib import Path
from uuid import uuid4

from flask import Blueprint, abort, redirect, render_template, request, url_for

from ...services import doc_workspace, jobs, pipeline, state, word_translate

main_bp = Blueprint(
    "main",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static/main",
)


def _safe_upload_name(filename: str, fallback_ext: str) -> str:
    ext = Path(filename or "").suffix.lower() or fallback_ext
    return f"{uuid4().hex}{ext}"


def _display_name_from_filename(filename: str, fallback: str) -> str:
    raw_stem = Path(filename or "").stem
    return jobs.sanitize_unicode_filename(raw_stem, fallback=fallback)


def _display_creator_name(value: str, fallback: str = "") -> str:
    cleaned = " ".join(str(value or "").split()).strip()
    return jobs.sanitize_unicode_filename(cleaned, fallback=fallback) if cleaned else fallback


@main_bp.route("/", methods=["GET"], endpoint="index")
def index() -> str:
    return render_template("main/index.html")


@main_bp.route("/workspace/pdf-overlay", methods=["GET"], endpoint="overlay_workspace")
def overlay_workspace() -> str:
    return render_template("main/overlay_workspace.html", batch_model=state.AZURE_BATCH_MODEL)


@main_bp.route("/workspace/pdf-doc", methods=["GET"], endpoint="doc_workspace_page")
def doc_workspace_page() -> str:
    return render_template("main/doc_workspace.html")


@main_bp.route("/workspace/word", methods=["GET"], endpoint="word_workspace_page")
def word_workspace_page() -> str:
    return render_template("main/word_workspace.html")


@main_bp.route("/upload", methods=["POST"], endpoint="upload")
def upload() -> str:
    files = request.files.getlist("pdf")
    if not files or all(f.filename == "" for f in files):
        abort(400, "Missing PDF file.")

    state.JOB_ROOT.mkdir(parents=True, exist_ok=True)
    state.UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

    dpi = 200
    start_page = int(request.form.get("start", 1))
    end_page_raw = request.form.get("end", "").strip()
    end_page = int(end_page_raw) if end_page_raw else None
    enable_translate = request.form.get("translate") == "on"
    translate_target_lang = request.form.get("target_lang", "en").strip() or "en"
    translate_model = request.form.get("model", state.AZURE_BATCH_MODEL).strip() or state.AZURE_BATCH_MODEL
    keep_lang = request.form.get("keep_lang", "all").strip().lower() or "all"
    document_mode = jobs.normalize_document_mode(request.form.get("document_mode"))
    creator_name = _display_creator_name(request.form.get("creator_name", ""))
    if keep_lang not in {"all", "zh", "en"}:
        keep_lang = "all"

    for file in files:
        if not file or file.filename == "":
            continue
        ext = Path(file.filename).suffix.lower()
        if ext not in state.ALLOWED_EXTENSIONS:
            continue
        tmp_path = state.UPLOAD_ROOT / _safe_upload_name(file.filename or "", ".pdf")
        file.save(tmp_path)
        display_name = _display_name_from_filename(file.filename or "", "job")
        pipeline.enqueue_job_from_upload(
            tmp_path,
            display_name,
            dpi,
            start_page,
            end_page,
            translate_target_lang,
            translate_model,
            keep_lang,
            enable_translate,
            document_mode,
            creator_name,
        )
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    jobs.notify_jobs_update()

    return redirect(url_for(".overlay_workspace"))


@main_bp.route("/upload-doc-workspace", methods=["POST"], endpoint="upload_doc_workspace")
def upload_doc_workspace() -> str:
    files = request.files.getlist("pdf")
    if not files or all(f.filename == "" for f in files):
        abort(400, "Missing PDF file.")

    state.JOB_ROOT.mkdir(parents=True, exist_ok=True)
    state.UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

    target_lang = request.form.get("target_lang", "en").strip() or "en"

    for file in files:
        if not file or file.filename == "":
            continue
        ext = Path(file.filename).suffix.lower()
        if ext not in state.ALLOWED_EXTENSIONS:
            continue
        tmp_path = state.UPLOAD_ROOT / _safe_upload_name(file.filename or "", ".pdf")
        file.save(tmp_path)
        display_name = _display_name_from_filename(file.filename or "", "document")
        doc_workspace.enqueue_doc_job_from_upload(
            tmp_path,
            display_name,
            target_lang,
        )
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    jobs.notify_jobs_update()
    return redirect(url_for(".doc_workspace_page"))


@main_bp.route("/upload-word-workspace", methods=["POST"], endpoint="upload_word_workspace")
def upload_word_workspace() -> str:
    files = request.files.getlist("docx")
    if not files or all(f.filename == "" for f in files):
        abort(400, "Missing Word file.")

    state.JOB_ROOT.mkdir(parents=True, exist_ok=True)
    state.UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

    target_lang = request.form.get("target_lang", "en").strip() or "en"
    retain_terms = request.form.get("retain_terms", "")

    for file in files:
        if not file or file.filename == "":
            continue
        ext = Path(file.filename).suffix.lower()
        if ext not in word_translate.WORD_ALLOWED_EXTENSIONS:
            continue
        tmp_path = state.UPLOAD_ROOT / _safe_upload_name(file.filename or "", ".docx")
        file.save(tmp_path)
        display_name = _display_name_from_filename(file.filename or "", "document")
        word_translate.enqueue_word_job_from_upload(
            tmp_path,
            display_name,
            target_lang,
            retain_terms_raw=retain_terms,
        )
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    jobs.notify_jobs_update()
    return redirect(url_for(".word_workspace_page"))
