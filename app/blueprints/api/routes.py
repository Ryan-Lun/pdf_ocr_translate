from __future__ import annotations

import json
import logging
import threading

from flask import Blueprint, Response, abort, jsonify, request, send_file, stream_with_context, url_for

from ...services import batch, doc_workspace, glossary, jobs, ocr, state, word_translate

logger = logging.getLogger(__name__)

api_bp = Blueprint(
    "api",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static/api",
    url_prefix="/api",
)


@api_bp.route("/job/<job_id>", methods=["GET"], endpoint="job_data")
def job_data(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    job_dir = jobs.job_dir(job_id)
    json_dir = job_dir / "ocr_json"
    if not json_dir.exists():
        abort(404)

    edits_map = jobs.load_edits_map(job_dir)
    json_paths = sorted(json_dir.glob("*_res_with_pdf_coords.json"))
    pages = []
    for path in json_paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        page_idx_guess = int(data.get("page_index_0based", 0))
        edits_boxes = edits_map.get(page_idx_guess) if page_idx_guess in edits_map else None
        page = ocr.load_page_data(path, edits_boxes=edits_boxes, data=data)
        if not page["input_image"]:
            continue
        page["image_url"] = url_for(
            "jobs.job_file", job_id=job_id, filename=f"images/{page['input_image']}"
        )
        pages.append(page)

    edited_pdf_path = job_dir / "edited.pdf"
    config = jobs.load_batch_config(job_dir) or {}
    job_name = jobs.get_job_name(job_dir)
    download_name = jobs.build_download_name(job_id, job_name)
    target_lang = str(config.get("target_lang") or "en")
    system_prompt = config.get("system_prompt") or batch.resolve_batch_prompt(target_lang)
    payload = {
        "job_id": job_id,
        "job_name": job_name,
        "download_name": download_name,
        "pdf_url": url_for("jobs.job_file", job_id=job_id, filename=f"{job_id}.pdf"),
        "debug_pdf_url": url_for(
            "jobs.job_file", job_id=job_id, filename="overlay_debug.pdf"
        ),
        "edited_pdf_url": url_for("jobs.job_file", job_id=job_id, filename="edited.pdf")
        if edited_pdf_path.exists()
        else None,
        "batch_status": jobs.load_batch_status(job_dir),
        "glossary": glossary.load_global_glossary(),
        "system_prompt": system_prompt,
        "pages": pages,
    }
    return jsonify(payload)


@api_bp.route("/job/<job_id>/batch-translate", methods=["POST"], endpoint="batch_translate")
def batch_translate(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)
    status = jobs.load_batch_status(job_dir)
    if status and status.get("status") in {"running", "queued"}:
        return jsonify({"ok": True, "status": status})
    config = jobs.load_batch_config(job_dir) or {}
    threading.Thread(
        target=batch.run_batch_translate_job, args=(job_id, job_dir, config), daemon=True
    ).start()
    return jsonify({"ok": True, "status": {"status": "running"}})


@api_bp.route("/job/<job_id>/batch-status", methods=["GET"], endpoint="batch_status")
def batch_status(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)
    status = jobs.load_batch_status(job_dir) or {"status": "not_started"}
    return jsonify({"ok": True, "status": status})


@api_bp.route("/job/<job_id>/batch-restore", methods=["POST"], endpoint="batch_restore")
def batch_restore(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)
    try:
        alias_map = jobs.load_batch_alias_map(job_dir)
        prefilled = jobs.load_batch_prefill_map(job_dir)
        output_path = job_dir / state.BATCH_OUTPUT_NAME
        if output_path.exists():
            raw_text = output_path.read_text(encoding="utf-8")
        else:
            raw_text = ""
            if not prefilled:
                return jsonify({"ok": False, "error": "Batch output not found."}), 400
        translations = batch.build_translations_from_jsonl_text(
            raw_text, alias_map=alias_map, prefilled=prefilled
        )
        ocr_pages = ocr.load_ocr_pages(job_dir)
        pp_pages = ocr.load_pp_pages(job_dir)
        edits_payload = batch.build_edits_payload_from_translations(
            ocr_pages, translations, pp_pages=pp_pages
        )
        edits_path = job_dir / "edits.json"
        edits_path.write_text(
            json.dumps(edits_payload, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        ocr.apply_edits_to_pdf(job_id, job_dir, edits_payload)
        logger.info("Batch translate restored edits.json job_id=%s", job_id)
        jobs.notify_jobs_update()
    except Exception as exc:
        logger.exception("Batch translate restore failed job_id=%s error=%s", job_id, exc)
        return jsonify({"ok": False, "error": str(exc)}), 500

    return jsonify({"ok": True})


@api_bp.route("/job/<job_id>/system-prompt", methods=["POST"], endpoint="save_system_prompt")
def save_system_prompt(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)
    payload = request.get_json(force=True) or {}
    system_prompt = str(payload.get("system_prompt") or "").strip()
    config = jobs.load_batch_config(job_dir) or {}
    if system_prompt:
        config["system_prompt"] = system_prompt
    else:
        config.pop("system_prompt", None)
    jobs.write_batch_config(job_dir, config)
    jobs.notify_jobs_update()
    return jsonify({"ok": True, "system_prompt": config.get("system_prompt")})


@api_bp.route("/glossary", methods=["GET", "POST"], endpoint="global_glossary")
def global_glossary():
    if request.method == "GET":
        return jsonify({"ok": True, "glossary": glossary.load_global_glossary()})
    payload = request.get_json(force=True) or {}
    items = payload.get("glossary", [])
    if not isinstance(items, list):
        return jsonify({"ok": False, "error": "Invalid glossary payload."}), 400
    glossary.write_global_glossary(items)
    jobs.notify_jobs_update()
    return jsonify({"ok": True, "glossary": glossary.load_global_glossary()})


@api_bp.route("/jobs", methods=["GET"], endpoint="list_jobs")
def list_jobs():
    jobs_list = jobs.build_jobs_list(job_type="ocr_overlay")
    return jsonify({"jobs": jobs_list})


@api_bp.route("/doc-jobs", methods=["GET"], endpoint="list_doc_jobs")
def list_doc_jobs():
    jobs_list = jobs.build_jobs_list(job_type="doc_workspace")
    return jsonify({"jobs": jobs_list})


@api_bp.route("/word-jobs", methods=["GET"], endpoint="list_word_jobs")
def list_word_jobs():
    jobs_list = jobs.build_jobs_list(job_type="word_translate")
    return jsonify({"jobs": jobs_list})


@api_bp.route("/job/<job_id>/cancel-word", methods=["POST"], endpoint="cancel_word_job")
def cancel_word_job(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists() or jobs.get_job_type(job_dir) != "word_translate":
        abort(404)
    cancelled = word_translate.cancel_word_job(job_id)
    if cancelled:
        jobs.update_job_meta(job_dir, word_stage="cancelled")
        jobs.notify_jobs_update()
    return jsonify({"ok": True, "cancelled": cancelled})


@api_bp.route("/doc-job/<job_id>", methods=["GET"], endpoint="doc_job_data")
def doc_job_data(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists() or jobs.get_job_type(job_dir) != "doc_workspace":
        abort(404)
    job_name = jobs.get_job_name(job_dir)
    payload = {
        "job_id": job_id,
        "job_name": job_name,
        "status": doc_workspace.load_doc_status(job_dir),
        "source_pdf_url": url_for("jobs.job_file", job_id=job_id, filename="source.pdf")
        if (job_dir / "source.pdf").exists()
        else None,
        "structure_md_url": url_for("jobs.job_file", job_id=job_id, filename="structure/doc.md")
        if (job_dir / "structure" / "doc.md").exists()
        else None,
        "translated_md_url": url_for(
            "jobs.job_file", job_id=job_id, filename="translated/doc.translated.md"
        )
        if (job_dir / "translated" / "doc.translated.md").exists()
        else None,
        "docx_url": url_for("jobs.job_file", job_id=job_id, filename="output/output.docx")
        if (job_dir / "output" / "output.docx").exists()
        else None,
        "docx_download_name": jobs.build_docx_name(job_id, job_name),
        "structure_download_name": jobs.build_doc_markdown_name(job_id, job_name, translated=False),
        "translated_download_name": jobs.build_doc_markdown_name(job_id, job_name, translated=True),
    }
    return jsonify(payload)


@api_bp.route("/jobs/download-translated", methods=["GET", "POST"], endpoint="download_translated_batch")
def download_translated_batch():
    job_ids: set[str] | None = None
    if request.method == "POST":
        payload = request.get_json(force=True, silent=True) or {}
        raw_ids = payload.get("job_ids")
        if not isinstance(raw_ids, list):
            return jsonify({"ok": False, "error": "Invalid job_ids payload."}), 400
        job_ids = {str(item) for item in raw_ids if isinstance(item, str) and jobs.safe_job_id(item)}
        if not job_ids:
            return jsonify({"ok": False, "error": "No valid job IDs selected."}), 400

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


@api_bp.route("/jobs/stream", methods=["GET"], endpoint="jobs_stream")
def jobs_stream():
    @stream_with_context
    def generate():
        last_version = -1
        while True:
            with state.JOBS_EVENT:
                if last_version == state.JOBS_VERSION:
                    state.JOBS_EVENT.wait(timeout=15)
                current_version = state.JOBS_VERSION
            if current_version == last_version:
                yield ": ping\n\n"
                continue
            last_version = current_version
            payload = {"jobs": jobs.build_jobs_list(job_type="ocr_overlay")}
            data = json.dumps(payload, ensure_ascii=False)
            yield f"event: jobs\ndata: {data}\n\n"

    resp = Response(generate(), mimetype="text/event-stream")
    resp.headers["Cache-Control"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    return resp


@api_bp.route("/job/<job_id>", methods=["DELETE"], endpoint="delete_job")
def delete_job(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        return jsonify({"ok": True, "deleted": False})
    deleted, error = jobs.delete_job_dir(job_id)
    if not deleted:
        return jsonify({"ok": False, "error": error}), 500
    return jsonify({"ok": True, "deleted": True})


@api_bp.route("/job/<job_id>/save", methods=["POST"], endpoint="save_job")
def save_job(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)

    payload = request.get_json(force=True)
    edits_path = job_dir / "edits.json"
    edits_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        edited_pdf = ocr.apply_edits_to_pdf(job_id, job_dir, payload)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    jobs.notify_jobs_update()
    return jsonify(
        {
            "ok": True,
            "edited_pdf_url": url_for(
                "jobs.job_file", job_id=job_id, filename=edited_pdf.name
            ),
        }
    )


@api_bp.route("/upload-cancel", methods=["POST"], endpoint="cancel_upload")
def cancel_upload():
    active = jobs.get_active_upload()
    if not active:
        return jsonify({"ok": False, "status": "idle"})
    event = active.get("event")
    if event is not None:
        event.set()
    jobs.notify_jobs_update()
    return jsonify({"ok": True, "job_id": active.get("job_id")})
