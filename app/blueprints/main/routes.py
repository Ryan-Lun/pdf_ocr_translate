from __future__ import annotations

import re
from pathlib import Path
from uuid import uuid4

from flask import Blueprint, abort, redirect, render_template, request, url_for
from flask_login import current_user

from ...services import audit_service, authz_service, doc_workspace, document_templates, jobs, pipeline, state, submit_quota, word_translate

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


def _current_creator_name() -> str:
    if not getattr(current_user, "is_authenticated", False):
        return ""
    display_name = _display_creator_name(getattr(current_user, "display_name", ""))
    work_id = " ".join(str(getattr(current_user, "work_id", "") or "").split()).strip()
    if display_name and work_id and display_name != work_id:
        # return f"{display_name} / {work_id}"
        return f"{work_id} / {display_name}"
    if display_name:
        return display_name
    return work_id


def _current_owner_work_id() -> str:
    if getattr(current_user, "is_authenticated", False):
        return " ".join(str(getattr(current_user, "work_id", "") or "").split()).strip()
    return ""


def _parse_page_numbers(value: str) -> list[int]:
    page_numbers: list[int] = []
    seen: set[int] = set()
    normalized = str(value or "").replace("，", ",")
    if not re.fullmatch(r"[\d,\-\s]*", normalized):
        raise ValueError("Invalid page selection.")
    for part in normalized.split(","):
        token = part.strip()
        if not token:
            continue
        if "-" in token:
            start_raw, end_raw = [item.strip() for item in token.split("-", 1)]
            if not start_raw or not end_raw:
                raise ValueError("Invalid page range.")
            start = int(start_raw)
            end = int(end_raw)
            if start < 1 or end < start:
                raise ValueError("Invalid page range.")
            values = range(start, end + 1)
        else:
            page = int(token)
            if page < 1:
                raise ValueError("Invalid page number.")
            values = [page]
        for page in values:
            if page not in seen:
                page_numbers.append(page)
                seen.add(page)
    return page_numbers


def _parse_positive_int_field(name: str, default: int | None = None) -> int | None:
    raw = str(request.form.get(name, "") or "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError:
        abort(400, f"Invalid {name} value.")
    if value < 1:
        abort(400, f"Invalid {name} value.")
    return value


def _enforce_submit_quota(creator_name: str = "") -> None:
    allowed, limit, retry_after = submit_quota.check_and_record_submission(
        creator_name,
        request.remote_addr,
    )
    if allowed:
        return
    abort(
        429,
        f"Submission limit exceeded. Max {limit} submissions per minute per user. Retry after {int(retry_after)}s.",
    )


@main_bp.route("/", methods=["GET"], endpoint="index")
def index() -> str:
    return render_template("main/index.html")


@main_bp.route("/workspace/pdf-overlay", methods=["GET"], endpoint="overlay_workspace")
def overlay_workspace() -> str:
    return render_template(
        "main/overlay_workspace.html",
        batch_model=state.AZURE_BATCH_MODEL,
        realtime_model=state.PDF_REALTIME_TRANSLATE_MODEL,
    )


@main_bp.route("/workspace/pdf-overlay/templates", methods=["GET"], endpoint="overlay_templates_page")
def overlay_templates_page() -> str:
    return render_template("main/overlay_templates.html")


@main_bp.route("/workspace/glossary", methods=["GET"], endpoint="glossary_page")
def glossary_page() -> str:
    return render_template("main/glossary_manager.html")


@main_bp.route(
    "/workspace/pdf-overlay/templates/<job_id>",
    methods=["GET"],
    endpoint="template_editor_page",
)
def template_editor_page(job_id: str) -> str:
    if not jobs.safe_job_id(job_id):
        abort(404)
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)
    template_record = document_templates.get_document_template_by_job(
        job_id,
        include_all=True,
    )
    if template_record is None and not authz_service.can_access_job(current_user, job_id):
        abort(403)
    return render_template(
        "main/template_editor.html",
        job_id=job_id,
        template_record=template_record,
        job_name=jobs.get_job_name(job_dir),
        debug_pdf_url=url_for("jobs.job_file", job_id=job_id, filename="overlay_debug.pdf"),
    )


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
    upload_files = [f for f in files if f and f.filename]

    jobs.job_root_for_type("ocr_overlay").mkdir(parents=True, exist_ok=True)
    state.UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

    dpi = 200
    start_page = _parse_positive_int_field("start", 1) or 1
    end_page = _parse_positive_int_field("end")
    pages_raw = request.form.get("pages", "").strip()
    try:
        page_numbers = _parse_page_numbers(pages_raw) if pages_raw else []
    except ValueError:
        abort(400, "Invalid page selection. Use comma-separated pages or ranges, for example 1,3,5-7.")
    if len(upload_files) > 1:
        start_page = 1
        end_page = None
        page_numbers = []
    enable_translate = request.form.get("translate") == "on"
    translate_source_lang = request.form.get("source_lang", "auto").strip() or "auto"
    translate_target_lang = request.form.get("target_lang", "en").strip() or "en"
    translate_mode = jobs.normalize_translate_mode(request.form.get("translate_mode"))
    default_translate_model = (
        state.PDF_REALTIME_TRANSLATE_MODEL
        if translate_mode == "realtime"
        else state.AZURE_BATCH_MODEL
    )
    translate_model = request.form.get("model", default_translate_model).strip() or default_translate_model
    keep_lang = request.form.get("keep_lang", "all").strip().lower() or "all"
    document_mode = jobs.normalize_document_mode(request.form.get("document_mode"))
    if document_mode != "other":
        translate_source_lang = "auto"
    creator_name = _current_creator_name()
    owner_work_id = _current_owner_work_id()
    _enforce_submit_quota(creator_name)
    if keep_lang not in {"all", "zh", "en"}:
        keep_lang = "all"

    for file in upload_files:
        if not file or file.filename == "":
            continue
        ext = Path(file.filename).suffix.lower()
        if ext not in state.ALLOWED_EXTENSIONS:
            continue
        tmp_path = state.UPLOAD_ROOT / _safe_upload_name(file.filename or "", ".pdf")
        file.save(tmp_path)
        display_name = _display_name_from_filename(file.filename or "", "job")
        enqueue_options = {}
        if owner_work_id:
            enqueue_options["owner_work_id"] = owner_work_id
        if page_numbers:
            enqueue_options["page_numbers"] = page_numbers
        created_job_id = pipeline.enqueue_job_from_upload(
            tmp_path,
            display_name,
            dpi,
            start_page,
            end_page,
            translate_source_lang,
            translate_target_lang,
            translate_model,
            translate_mode,
            keep_lang,
            enable_translate,
            document_mode,
            creator_name,
            **enqueue_options,
        )
        audit_service.record_audit(
            "job_upload",
            detail={
                "job_type": "ocr_overlay",
                "job_name": display_name,
                "filename": file.filename or "",
                "enable_translate": enable_translate,
                "target_lang": translate_target_lang if enable_translate else "",
                "document_mode": document_mode,
            },
            job_id=created_job_id,
        )
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    jobs.notify_jobs_update()

    return redirect(url_for(".overlay_workspace"))


@main_bp.route("/upload-template-source", methods=["POST"], endpoint="upload_template_source")
def upload_template_source() -> str:
    files = request.files.getlist("pdf")
    if not files or all(f.filename == "" for f in files):
        abort(400, "Missing PDF file.")

    state.TEMPLATE_JOB_ROOT.mkdir(parents=True, exist_ok=True)
    state.UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

    dpi = 200
    template_page = max(1, int(request.form.get("page", 1)))
    translate_source_lang = "auto"
    translate_target_lang = "en"
    translate_mode = "batch"
    translate_model = state.AZURE_BATCH_MODEL
    keep_lang = "all"
    enable_translate = False
    document_mode = "scanned"
    creator_name = _current_creator_name()
    owner_work_id = _current_owner_work_id()
    _enforce_submit_quota(creator_name)
    created_job_id = ""

    for file in files:
        if not file or file.filename == "":
            continue
        ext = Path(file.filename).suffix.lower()
        if ext not in state.ALLOWED_EXTENSIONS:
            continue
        tmp_path = state.UPLOAD_ROOT / _safe_upload_name(file.filename or "", ".pdf")
        file.save(tmp_path)
        display_name = _display_name_from_filename(file.filename or "", "template")
        created_job_id = pipeline.enqueue_job_from_upload(
            tmp_path,
            display_name,
            dpi,
            template_page,
            template_page,
            translate_source_lang,
            translate_target_lang,
            translate_model,
            translate_mode,
            keep_lang,
            enable_translate,
            document_mode,
            creator_name,
            owner_work_id,
            job_root=state.TEMPLATE_JOB_ROOT,
            job_type="template_source",
        )
        document_templates.create_template_draft(
            source_job_id=created_job_id,
            display_name=display_name,
            owner_work_id=owner_work_id,
        )
        audit_service.record_audit(
            "job_upload",
            detail={
                "job_type": "template_source",
                "job_name": display_name,
                "filename": file.filename or "",
                "template_page": template_page,
            },
            job_id=created_job_id,
        )
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    jobs.notify_jobs_update()
    return redirect(url_for(".overlay_templates_page"))


@main_bp.route("/upload-doc-workspace", methods=["POST"], endpoint="upload_doc_workspace")
def upload_doc_workspace() -> str:
    files = request.files.getlist("pdf")
    if not files or all(f.filename == "" for f in files):
        abort(400, "Missing PDF file.")

    jobs.job_root_for_type("doc_workspace").mkdir(parents=True, exist_ok=True)
    state.UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

    source_lang = request.form.get("source_lang", "auto").strip() or "auto"
    target_lang = request.form.get("target_lang", "en").strip() or "en"
    system_prompt = request.form.get("system_prompt", "").strip()
    creator_name = _current_creator_name()
    owner_work_id = _current_owner_work_id()
    _enforce_submit_quota(creator_name)

    for file in files:
        if not file or file.filename == "":
            continue
        ext = Path(file.filename).suffix.lower()
        if ext not in state.ALLOWED_EXTENSIONS:
            continue
        tmp_path = state.UPLOAD_ROOT / _safe_upload_name(file.filename or "", ".pdf")
        file.save(tmp_path)
        display_name = _display_name_from_filename(file.filename or "", "document")
        created_job_id = doc_workspace.enqueue_doc_job_from_upload(
            tmp_path,
            display_name,
            source_lang,
            target_lang,
            creator_name,
            owner_work_id,
            system_prompt=system_prompt,
        )
        audit_service.record_audit(
            "job_upload",
            detail={
                "job_type": "doc_workspace",
                "job_name": display_name,
                "filename": file.filename or "",
                "source_lang": source_lang,
                "target_lang": target_lang,
            },
            job_id=created_job_id,
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

    jobs.job_root_for_type("word_translate").mkdir(parents=True, exist_ok=True)
    state.UPLOAD_ROOT.mkdir(parents=True, exist_ok=True)

    source_lang = request.form.get("source_lang", "auto").strip() or "auto"
    target_lang = request.form.get("target_lang", "en").strip() or "en"
    retain_terms = request.form.get("retain_terms", "")
    system_prompt = request.form.get("system_prompt", "").strip()
    creator_name = _current_creator_name()
    owner_work_id = _current_owner_work_id()
    _enforce_submit_quota(creator_name)

    for file in files:
        if not file or file.filename == "":
            continue
        ext = Path(file.filename).suffix.lower()
        if ext not in word_translate.WORD_ALLOWED_EXTENSIONS:
            continue
        tmp_path = state.UPLOAD_ROOT / _safe_upload_name(file.filename or "", ".docx")
        file.save(tmp_path)
        display_name = _display_name_from_filename(file.filename or "", "document")
        created_job_id = word_translate.enqueue_word_job_from_upload(
            tmp_path,
            display_name,
            source_lang,
            target_lang,
            creator_name=creator_name,
            owner_work_id=owner_work_id,
            retain_terms_raw=retain_terms,
            system_prompt=system_prompt,
        )
        audit_service.record_audit(
            "job_upload",
            detail={
                "job_type": "word_translate",
                "job_name": display_name,
                "filename": file.filename or "",
                "source_lang": source_lang,
                "target_lang": target_lang,
            },
            job_id=created_job_id,
        )
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass

    jobs.notify_jobs_update()
    return redirect(url_for(".word_workspace_page"))
