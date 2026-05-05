from __future__ import annotations

import json
import logging
import time

from flask import Blueprint, Response, abort, jsonify, request, send_file, stream_with_context, url_for

from ...services import batch, doc_workspace, glossary, jobs, ocr, state, translation_memory, word_translate

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
    document_mode = batch.resolve_document_mode(
        config.get("document_mode") or (jobs.load_job_meta(job_dir) or {}).get("document_mode")
    )
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
        "document_mode": document_mode,
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
    record = jobs.job_store.get_job(job_id)
    payload = jobs.job_store.deserialize_payload(record)
    payload["resume_translate_only"] = True
    jobs.job_store.update_job(
        job_id,
        status="queued",
        stage="translate",
        payload_json=json.dumps(payload, ensure_ascii=False),
        error_message=None,
        completed_at=None,
    )
    jobs.write_batch_status(job_dir, "queued", job_id=job_id, model=config.get("model"), target_lang=config.get("target_lang"))
    return jsonify({"ok": True, "status": {"status": "queued"}})


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
        document_mode = batch.resolve_document_mode(
            (jobs.load_batch_config(job_dir) or {}).get("document_mode")
            or (jobs.load_job_meta(job_dir) or {}).get("document_mode")
        )
        target_lang = str((jobs.load_batch_config(job_dir) or {}).get("target_lang") or "en")
        edits_payload = batch.build_edits_payload_from_translations(
            ocr_pages,
            translations,
            pp_pages=pp_pages,
            target_lang=target_lang,
            document_mode=document_mode,
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
    cancelled = word_translate.cancel_word_job(job_id) or jobs.job_store.request_cancel(job_id)
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
        last_payload = None
        while True:
            payload = {"jobs": jobs.build_jobs_list(job_type="ocr_overlay")}
            data = json.dumps(payload, ensure_ascii=False)
            if data != last_payload:
                last_payload = data
                yield f"event: jobs\ndata: {data}\n\n"
            else:
                yield ": ping\n\n"
            time.sleep(3)

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
    config = jobs.load_batch_config(job_dir) or {}
    document_mode = batch.resolve_document_mode(
        config.get("document_mode") or (jobs.load_job_meta(job_dir) or {}).get("document_mode")
    )
    target_lang = str(config.get("target_lang") or "en")
    edits_path = job_dir / "edits.json"
    edits_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    if document_mode == "form":
        tm_changed = False
        with state.TRANSLATION_MEMORY_LOCK:
            memory = translation_memory.load_translation_memory()
            now_ts = None
            for page in payload.get("pages", []):
                if not isinstance(page, dict):
                    continue
                for box in page.get("boxes", []):
                    if not isinstance(box, dict):
                        continue
                    if box.get("deleted") or not bool(box.get("auto_generated")):
                        continue
                    source_text = str(box.get("tm_source_text") or "").strip()
                    translated_text = str(box.get("text") or "").strip()
                    box_mode = str(box.get("tm_document_mode") or document_mode)
                    box_target_lang = str(box.get("tm_target_lang") or target_lang)
                    if not source_text or not translated_text:
                        continue
                    if translation_memory.normalize_document_mode(box_mode) != "form":
                        continue
                    translation_memory.upsert_entry(
                        memory,
                        source_text,
                        translated_text,
                        box_target_lang,
                        box_mode,
                        source_normalized=str(box.get("tm_source_normalized") or "") or None,
                        source="editor",
                        now_ts=now_ts,
                    )
                    tm_changed = True
            if tm_changed:
                translation_memory.write_translation_memory(memory)
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
        for item in jobs.job_store.list_jobs(job_type="ocr_overlay"):
            if item.status in {"queued", "running", "cancel_requested"}:
                cancelled = jobs.job_store.request_cancel(item.job_id)
                return jsonify({"ok": cancelled, "job_id": item.job_id, "status": "cancel_requested" if cancelled else "idle"})
        return jsonify({"ok": False, "status": "idle"})
    event = active.get("event")
    if event is not None:
        event.set()
    job_id = str(active.get("job_id") or "")
    if jobs.safe_job_id(job_id):
        jobs.job_store.request_cancel(job_id)
    jobs.notify_jobs_update()
    return jsonify({"ok": True, "job_id": active.get("job_id")})
