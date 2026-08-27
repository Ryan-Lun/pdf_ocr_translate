from __future__ import annotations

from .shared import (
    _current_access_scope,
    api_bp,
    jobs,
    jsonify,
    request,
    send_file,
)


@api_bp.route("/jobs/download-translated", methods=["GET", "POST"], endpoint="download_translated_batch")
def download_translated_batch():
    owner_work_id, include_all = _current_access_scope()
    accessible_job_ids = jobs.list_accessible_job_ids(
        job_type="ocr_overlay",
        owner_work_id=owner_work_id,
        include_all=include_all,
    )
    job_ids: set[str] | None = None
    if request.method == "POST":
        payload = request.get_json(force=True, silent=True) or {}
        raw_ids = payload.get("job_ids")
        if not isinstance(raw_ids, list):
            return jsonify({"ok": False, "error": "Invalid job_ids payload."}), 400
        job_ids = {
            str(item)
            for item in raw_ids
            if isinstance(item, str) and jobs.safe_job_id(item) and str(item) in accessible_job_ids
        }
        if not job_ids:
            return jsonify({"ok": False, "error": "No authorized job IDs selected."}), 403
    else:
        job_ids = accessible_job_ids

    buf, count = jobs.build_translated_zip(job_ids)
    if count == 0:
        msg = "No translated PDFs found for selected jobs." if job_ids else "No translated PDFs found."
        return jsonify({"ok": False, "error": msg}), 400
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name="translated_pdfs.zip",
    )


def _selected_job_ids_from_request() -> set[str] | tuple[Response, int]:
    payload = request.get_json(force=True, silent=True) or {}
    raw_ids = payload.get("job_ids")
    if not isinstance(raw_ids, list):
        return jsonify({"ok": False, "error": "Invalid job_ids payload."}), 400
    job_ids = {str(item) for item in raw_ids if isinstance(item, str) and jobs.safe_job_id(item)}
    if not job_ids:
        return jsonify({"ok": False, "error": "No valid job IDs selected."}), 400
    return job_ids


def _download_docx_batch(job_type: str, empty_message: str, download_name: str):
    owner_work_id, include_all = _current_access_scope()
    accessible_job_ids = jobs.list_accessible_job_ids(
        job_type=job_type,
        owner_work_id=owner_work_id,
        include_all=include_all,
    )
    selected = _selected_job_ids_from_request()
    if isinstance(selected, tuple):
        return selected
    selected = {job_id for job_id in selected if job_id in accessible_job_ids}
    if not selected:
        return jsonify({"ok": False, "error": "No authorized job IDs selected."}), 403
    buf, count = jobs.build_docx_zip(selected, job_type)
    if count == 0:
        return jsonify({"ok": False, "error": empty_message}), 400
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=download_name,
    )


@api_bp.route("/doc-jobs/download-docx", methods=["POST"], endpoint="download_doc_jobs_docx")
def download_doc_jobs_docx():
    return _download_docx_batch(
        "doc_workspace",
        "No Word files found for selected document jobs.",
        "document_workspace_docx.zip",
    )


@api_bp.route("/word-jobs/download-docx", methods=["POST"], endpoint="download_word_jobs_docx")
def download_word_jobs_docx():
    return _download_docx_batch(
        "word_translate",
        "No translated Word files found for selected jobs.",
        "translated_word_docx.zip",
    )
