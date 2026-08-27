from __future__ import annotations

from .shared import (
    _forbidden_json,
    _job_access_denied,
    abort,
    api_bp,
    batch,
    glossary,
    io,
    jobs,
    json,
    jsonify,
    logger,
    ocr,
    request,
    send_file,
    state,
    translation_memory,
    url_for,
)


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


@api_bp.route("/glossary/library", methods=["GET"], endpoint="glossary_library")
def glossary_library():
    return jsonify({"ok": True, **glossary.build_glossary_management_payload()})


@api_bp.route("/glossary/system-export", methods=["GET"], endpoint="glossary_system_export")
def glossary_system_export():
    workbook = glossary.export_system_glossary_excel()
    return send_file(
        io.BytesIO(workbook),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="system_glossary.xlsx",
    )


@api_bp.route("/glossary/system-import-preview", methods=["POST"], endpoint="glossary_system_import_preview")
def glossary_system_import_preview():
    upload = request.files.get("file")
    if upload is None or not str(upload.filename or "").strip():
        return jsonify({"ok": False, "error": "Missing Excel file."}), 400
    filename = str(upload.filename or "").strip().lower()
    if not filename.endswith(".xlsx"):
        return jsonify({"ok": False, "error": "Only .xlsx files are supported."}), 400
    try:
        parsed = glossary.parse_system_glossary_excel(upload.read())
        preview = glossary.build_system_glossary_import_preview(parsed["items"])
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, **parsed, **preview})


@api_bp.route("/glossary/system-import-apply", methods=["POST"], endpoint="glossary_system_import_apply")
def glossary_system_import_apply():
    payload = request.get_json(force=True) or {}
    items = payload.get("items", [])
    duplicates = payload.get("duplicates", [])
    invalid_rows = payload.get("invalid_rows", [])
    if not isinstance(items, list):
        return jsonify({"ok": False, "error": "Invalid glossary payload."}), 400
    if isinstance(duplicates, list) and duplicates:
        return jsonify({"ok": False, "error": "請先排除重複詞彙列，再確認合併。"}), 400
    if isinstance(invalid_rows, list) and invalid_rows:
        return jsonify({"ok": False, "error": "請先排除無效列，再確認合併。"}), 400
    merged_items = glossary.apply_system_glossary_import(items)
    jobs.notify_jobs_update()
    return jsonify(
        {
            "ok": True,
            "system_glossary": merged_items,
            **glossary.build_glossary_management_payload(),
        }
    )


@api_bp.route(
    "/job/<job_id>/glossary-retranslate",
    methods=["POST"],
    endpoint="glossary_retranslate",
)
def glossary_retranslate(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)

    payload = request.get_json(force=True) or {}
    source_term = batch.normalize_text(str(payload.get("cn") or "")).strip()
    if not source_term:
        return jsonify({"ok": False, "error": "Missing glossary source term."}), 400

    config = jobs.load_batch_config(job_dir) or {}
    source_lang = str(config.get("source_lang") or "auto")
    target_lang = str(config.get("target_lang") or "en")
    model_name = str(config.get("model") or state.PDF_REALTIME_TRANSLATE_MODEL or state.DOC_TRANSLATE_MODEL)
    system_prompt = config.get("system_prompt") or batch.resolve_batch_prompt(target_lang)

    edits_map = jobs.load_edits_map(job_dir)
    matched_boxes: list[dict] = []
    source_buckets: dict[str, str] = {}
    for _, page_boxes in edits_map.items():
        for box in page_boxes:
            if not isinstance(box, dict) or box.get("deleted"):
                continue
            box_source_text = batch.normalize_text(str(box.get("tm_source_text") or "")).strip()
            if not box_source_text or source_term not in box_source_text:
                continue
            source_key = translation_memory.normalize_source_text(
                str(box.get("tm_source_normalized") or box_source_text)
            ) or box_source_text
            matched_boxes.append(box)
            source_buckets[source_key] = box_source_text

    if not matched_boxes:
        return jsonify({"ok": False, "error": "No matching boxes found for glossary term."}), 404

    glossary_entries = glossary.load_combined_glossary()
    translated_by_source: dict[str, str] = {}
    try:
        for source_key, source_text in source_buckets.items():
            translations = batch.translate_texts_for_region(
                [source_text],
                target_lang=target_lang,
                source_lang=source_lang,
                model_name=model_name,
                system_prompt=system_prompt,
                glossary_entries=glossary_entries,
            )
            translated_text = batch.normalize_text(translations[0] if translations else "")
            if not translated_text:
                raise RuntimeError(f"Empty translation result for glossary term match: {source_text}")
            translated_by_source[source_key] = translated_text
    except Exception as exc:
        logger.exception("Glossary retranslate failed job_id=%s term=%s error=%s", job_id, source_term, exc)
        return jsonify({"ok": False, "error": str(exc)}), 500

    updated_count = 0
    for box in matched_boxes:
        box_source_text = batch.normalize_text(str(box.get("tm_source_text") or "")).strip()
        source_key = translation_memory.normalize_source_text(
            str(box.get("tm_source_normalized") or box_source_text)
        ) or box_source_text
        translated_text = translated_by_source.get(source_key)
        if not translated_text:
            continue
        box["text"] = translated_text
        updated_count += 1

    edits_payload = {
        "pages": [
            {"page_index_0based": idx, "boxes": boxes}
            for idx, boxes in sorted(edits_map.items())
        ]
    }
    edits_path = job_dir / "edits.json"
    edits_path.write_text(
        json.dumps(edits_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    try:
        edited_pdf = ocr.apply_edits_to_pdf(job_id, job_dir, edits_payload)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    jobs.notify_jobs_update()
    return jsonify(
        {
            "ok": True,
            "updated_count": updated_count,
            "matched_source_count": len(source_buckets),
            "edited_pdf_url": url_for(
                "jobs.job_file", job_id=job_id, filename=edited_pdf.name
            ),
        }
    )
