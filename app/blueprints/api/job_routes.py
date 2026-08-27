from __future__ import annotations

from .shared import (
    _can_view_active_editors,
    _current_access_scope,
    _document_template_source_jobs,
    _forbidden_json,
    _job_access_denied,
    abort,
    api_bp,
    audit_service,
    doc_workspace,
    jobs,
    jsonify,
    request,
    url_for,
    word_translate,
)


@api_bp.route("/jobs", methods=["GET"], endpoint="list_jobs")
def list_jobs():
    owner_work_id, include_all = _current_access_scope()
    can_view_active_editors = _can_view_active_editors()
    jobs_list = jobs.build_jobs_list(
        job_type="ocr_overlay",
        owner_work_id=owner_work_id,
        include_all=include_all,
        include_active_editors=can_view_active_editors,
    )
    return jsonify(
        {
            "jobs": jobs_list,
            "can_view_active_editors": can_view_active_editors,
        }
    )


@api_bp.route("/template-jobs", methods=["GET"], endpoint="list_template_jobs")
def list_template_jobs():
    owner_work_id, include_all = _current_access_scope()
    can_view_active_editors = _can_view_active_editors()
    jobs_list = jobs.build_jobs_list(
        job_type="template_source",
        owner_work_id=owner_work_id,
        include_all=include_all,
        include_active_editors=can_view_active_editors,
    )
    return jsonify({"jobs": jobs_list, "can_view_active_editors": can_view_active_editors})


@api_bp.route("/document-templates/source-jobs", methods=["GET"], endpoint="document_template_source_jobs")
def document_template_source_jobs():
    return jsonify({"jobs": _document_template_source_jobs()})


@api_bp.route("/doc-jobs", methods=["GET"], endpoint="list_doc_jobs")
def list_doc_jobs():
    owner_work_id, include_all = _current_access_scope()
    can_view_active_editors = _can_view_active_editors()
    jobs_list = jobs.build_jobs_list(
        job_type="doc_workspace",
        owner_work_id=owner_work_id,
        include_all=include_all,
        include_active_editors=can_view_active_editors,
    )
    return jsonify({"jobs": jobs_list, "can_view_active_editors": can_view_active_editors})


@api_bp.route("/word-jobs", methods=["GET"], endpoint="list_word_jobs")
def list_word_jobs():
    owner_work_id, include_all = _current_access_scope()
    can_view_active_editors = _can_view_active_editors()
    jobs_list = jobs.build_jobs_list(
        job_type="word_translate",
        owner_work_id=owner_work_id,
        include_all=include_all,
        include_active_editors=can_view_active_editors,
    )
    return jsonify({"jobs": jobs_list, "can_view_active_editors": can_view_active_editors})

@api_bp.route("/job/<job_id>", methods=["DELETE"], endpoint="delete_job")
def delete_job(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id, allow_global_template_source=False):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    record = jobs.job_store.get_job(job_id)
    if not job_dir.exists() and record is None:
        return jsonify({"ok": True, "deleted": False})
    deleted, error = jobs.delete_job_dir(job_id)
    audit_service.record_audit(
        "job_delete",
        detail={
            "deleted": deleted,
            "error": error or "",
            "job_type": record.job_type if record is not None else "",
        },
        job_id=job_id,
    )
    if not deleted:
        return jsonify({"ok": False, "error": error}), 500
    return jsonify({"ok": True, "deleted": True})

@api_bp.route("/job/<job_id>/cancel-word", methods=["POST"], endpoint="cancel_word_job")
def cancel_word_job(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists() or jobs.get_job_type(job_dir) != "word_translate":
        abort(404)
    cancelled = word_translate.cancel_word_job(job_id) or jobs.request_job_cancel(job_id)
    audit_service.record_audit("job_cancel", detail={"job_type": "word_translate", "cancelled": cancelled}, job_id=job_id)
    jobs.notify_jobs_update()
    return jsonify({"ok": True, "cancelled": cancelled})


@api_bp.route("/job/<job_id>/cancel", methods=["POST"], endpoint="cancel_job")
def cancel_job(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    record = jobs.job_store.get_job(job_id)
    if record is None:
        abort(404)
    cancelled = False
    if record.job_type == "word_translate":
        cancelled = word_translate.cancel_word_job(job_id)
    cancelled = jobs.request_job_cancel(job_id) or cancelled
    audit_service.record_audit(
        "job_cancel",
        detail={"job_type": record.job_type, "cancelled": cancelled},
        job_id=job_id,
    )
    jobs.notify_jobs_update()
    return jsonify({"ok": True, "cancelled": cancelled})


@api_bp.route("/job/<job_id>/retry", methods=["POST"], endpoint="retry_job")
def retry_job(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    retried, error = jobs.retry_job(job_id)
    audit_service.record_audit("job_retry", detail={"retried": retried, "error": error or ""}, job_id=job_id)
    if not retried:
        return jsonify({"ok": False, "error": error}), 400
    return jsonify({"ok": True, "job_id": job_id})


@api_bp.route("/doc-job/<job_id>", methods=["GET"], endpoint="doc_job_data")
def doc_job_data(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists() or jobs.get_job_type(job_dir) != "doc_workspace":
        abort(404)
    job_name = jobs.get_job_name(job_dir)
    record = jobs.job_store.get_job(job_id)
    status_payload = doc_workspace.load_doc_status(job_dir) or {}
    if record is not None:
        status_payload["job_status"] = record.status
        status_payload["job_stage"] = record.stage
        status_payload["progress"] = record.progress
    payload = {
        "job_id": job_id,
        "job_name": job_name,
        "status": status_payload,
        "source_pdf_url": url_for("jobs.job_file", job_id=job_id, filename="source.pdf")
        if (job_dir / "source.pdf").exists()
        else None,
        "structure_md_url": url_for("jobs.job_file", job_id=job_id, filename="structure/doc.md")
        if (job_dir / "structure" / "doc.md").exists()
        else None,
        "structure_html_url": url_for("jobs.job_file", job_id=job_id, filename="structure/doc.html")
        if (job_dir / "structure" / "doc.html").exists()
        else None,
        "translated_html_url": url_for(
            "jobs.job_file", job_id=job_id, filename="translated/doc.translated.html"
        )
        if (job_dir / "translated" / "doc.translated.html").exists()
        else None,
        "docx_url": url_for("jobs.job_file", job_id=job_id, filename="output/output.docx")
        if (job_dir / "output" / "output.docx").exists()
        else None,
        "docx_download_name": jobs.build_docx_name(job_id, job_name),
        "structure_download_name": jobs.build_doc_markdown_name(job_id, job_name, translated=False),
        "structure_html_download_name": jobs.build_doc_html_name(job_id, job_name, translated=False),
        "translated_html_download_name": jobs.build_doc_html_name(job_id, job_name, translated=True),
    }
    return jsonify(payload)


@api_bp.route("/upload-cancel", methods=["POST"], endpoint="cancel_upload")
def cancel_upload():
    active = jobs.get_active_upload()
    if not active:
        owner_work_id, include_all = _current_access_scope()
        for item in jobs.job_store.list_jobs(job_type="ocr_overlay"):
            if not include_all and jobs.get_job_owner_work_id(item.job_id) != owner_work_id:
                continue
            if item.status in {"queued", "running", "cancel_requested"}:
                cancelled = jobs.request_job_cancel(item.job_id)
                updated = jobs.job_store.get_job(item.job_id)
                return jsonify(
                    {
                        "ok": cancelled,
                        "job_id": item.job_id,
                        "status": updated.status if cancelled and updated is not None else "idle",
                    }
                )
        return jsonify({"ok": False, "status": "idle"})
    event = active.get("event")
    active_job_id = str(active.get("job_id") or "")
    if jobs.safe_job_id(active_job_id) and _job_access_denied(active_job_id):
        return _forbidden_json()
    if event is not None:
        event.set()
    job_id = active_job_id
    if jobs.safe_job_id(job_id):
        jobs.request_job_cancel(job_id)
    jobs.notify_jobs_update()
    return jsonify({"ok": True, "job_id": active.get("job_id")})
