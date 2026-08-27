from __future__ import annotations

from .shared import (
    _can_view_active_editors,
    _current_access_scope,
    _current_editor_identity,
    _empty_editor_page,
    _ensure_editor_page_image,
    _forbidden_json,
    _job_access_denied,
    _load_job_translation_context,
    _pdf_page_count,
    abort,
    api_bp,
    batch,
    glossary,
    jobs,
    json,
    jsonify,
    logger,
    ocr,
    re,
    request,
    state,
    translation_memory,
    url_for,
)


@api_bp.route("/job/<job_id>/editor-presence", methods=["POST"], endpoint="editor_presence")
def editor_presence(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)
    work_id, display_name = _current_editor_identity()
    jobs.job_store.upsert_editor_presence(
        job_id=job_id,
        work_id=work_id,
        display_name=display_name,
        remote_addr=request.headers.get("X-Forwarded-For", request.remote_addr or "").split(",")[0].strip(),
        user_agent=request.headers.get("User-Agent", ""),
    )
    return jsonify({"ok": True})

@api_bp.route("/editor-presence", methods=["GET"], endpoint="editor_presence_index")
def editor_presence_index():
    if not _can_view_active_editors():
        return _forbidden_json()
    owner_work_id, include_all = _current_access_scope()
    job_ids = jobs.list_accessible_job_ids(
        job_type="ocr_overlay",
        owner_work_id=owner_work_id,
        include_all=include_all,
    )
    presence = jobs.job_store.list_active_editor_presence(job_ids)
    return jsonify(
        {
            "ok": True,
            "can_view_active_editors": True,
            "presence": presence,
        }
    )

@api_bp.route("/job/<job_id>", methods=["GET"], endpoint="job_data")
def job_data(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    json_dir = job_dir / "ocr_json"
    if not json_dir.exists():
        abort(404)

    edits_map = jobs.load_edits_map(job_dir)
    json_paths = sorted(json_dir.glob("*_res_with_pdf_coords.json"))
    pages_by_index: dict[int, dict[str, Any]] = {}
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
        pages_by_index[int(page["page_index_0based"])] = page

    source_pdf_path = job_dir / f"{job_id}.pdf"
    job_type = jobs.get_job_type(job_dir)
    page_count = _pdf_page_count(source_pdf_path)
    if job_type == "template_source":
        pages = [pages_by_index[page_idx] for page_idx in sorted(pages_by_index)]
    elif page_count > 0:
        pages = []
        images_dir = job_dir / "images"
        for page_idx in range(page_count):
            if page_idx in pages_by_index:
                pages.append(pages_by_index[page_idx])
                continue
            image_info = _ensure_editor_page_image(source_pdf_path, images_dir, page_idx)
            image_url = None
            image_size_px = None
            if image_info:
                image_name, image_size_px = image_info
                image_url = url_for("jobs.job_file", job_id=job_id, filename=f"images/{image_name}")
            pages.append(_empty_editor_page(page_idx, image_url=image_url, image_size_px=image_size_px))
    else:
        pages = [pages_by_index[page_idx] for page_idx in sorted(pages_by_index)]

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
        "batch_status": jobs.build_batch_status(job_dir),
        "document_mode": document_mode,
        "translate_mode": jobs.normalize_translate_mode(config.get("translate_mode")),
        "glossary": glossary.load_global_glossary(),
        "system_prompt": system_prompt,
        "merge_notices": jobs.load_merge_notices(job_dir),
        "pages": pages,
    }
    return jsonify(payload)


@api_bp.route(
    "/job/<job_id>/merge-notices/<notice_id>",
    methods=["POST"],
    endpoint="update_merge_notice",
)
def update_merge_notice(job_id: str, notice_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)
    payload = request.get_json(force=True) or {}
    status = str(payload.get("status") or "").strip().lower()
    updated = jobs.update_merge_notice_status(job_dir, notice_id, status)
    if updated is None:
        return jsonify({"ok": False, "error": "Merge notice not found or invalid status."}), 400
    return jsonify({"ok": True, "notice": updated})


@api_bp.route("/job/<job_id>/batch-translate", methods=["POST"], endpoint="batch_translate")
def batch_translate(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)
    status = jobs.build_batch_status(job_dir)
    if jobs.batch_translation_active(job_dir):
        return jsonify({"ok": True, "status": status})
    config = jobs.load_batch_config(job_dir) or {}
    status_payload = jobs.queue_batch_translation(
        job_dir,
        model=config.get("model"),
        target_lang=config.get("target_lang"),
        translate_mode=config.get("translate_mode"),
    )
    return jsonify({"ok": True, "status": status_payload})


@api_bp.route(
    "/job/<job_id>/retranslate-document",
    methods=["POST"],
    endpoint="retranslate_document",
)
def retranslate_document(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)

    edits_map = jobs.load_edits_map(job_dir)
    targets: list[dict[str, object]] = []
    for page_idx, page_boxes in sorted(edits_map.items()):
        for box in page_boxes:
            if not isinstance(box, dict) or box.get("deleted"):
                continue
            source_text = batch.normalize_text(str(box.get("tm_source_text") or "")).strip()
            if not source_text:
                continue
            try:
                box_id = int(box.get("id"))
            except (TypeError, ValueError):
                continue
            targets.append(
                {
                    "page_index_0based": int(page_idx),
                    "box_id": box_id,
                    "source_text": source_text,
                }
            )

    if not targets:
        return jsonify({"ok": False, "error": "No translatable boxes found in this document."}), 400

    body, status_code = _retranslate_boxes(
        job_id=job_id,
        job_dir=job_dir,
        targets=targets,
    )
    return jsonify(body), status_code


@api_bp.route("/job/<job_id>/batch-status", methods=["GET"], endpoint="batch_status")
def batch_status(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)
    return jsonify({"ok": True, "status": jobs.build_batch_status(job_dir)})


@api_bp.route("/job/<job_id>/batch-restore", methods=["POST"], endpoint="batch_restore")
def batch_restore(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
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
            debug_translations = batch.load_realtime_debug_translations(job_dir)
            raw_text = batch.build_jsonl_text_from_translations(debug_translations)
            if not raw_text and not prefilled:
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
        source_lang = str((jobs.load_batch_config(job_dir) or {}).get("source_lang") or "auto")
        target_lang = str((jobs.load_batch_config(job_dir) or {}).get("target_lang") or "en")
        edits_payload = batch.build_edits_payload_from_translations(
            ocr_pages,
            translations,
            pp_pages=pp_pages,
            target_lang=target_lang,
            source_lang=source_lang,
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
    if _job_access_denied(job_id):
        return _forbidden_json()
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

@api_bp.route("/job/<job_id>/save", methods=["POST"], endpoint="save_job")
def save_job(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
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
    if document_mode == "form" and state.PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY:
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


@api_bp.route(
    "/job/<job_id>/consistency/apply",
    methods=["POST"],
    endpoint="apply_consistency",
)
def apply_consistency(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)

    payload = request.get_json(force=True) or {}
    pages = payload.get("pages")
    source_normalized = translation_memory.normalize_source_text(
        payload.get("source_normalized") or ""
    )
    target_text = str(payload.get("target_text") or "").strip()
    sync_to_tm = bool(payload.get("sync_to_tm"))
    if not isinstance(pages, list):
        return jsonify({"ok": False, "error": "Invalid pages payload."}), 400
    if not source_normalized:
        return jsonify({"ok": False, "error": "Missing source_normalized."}), 400
    if not target_text:
        return jsonify({"ok": False, "error": "Missing target_text."}), 400

    updated_count = 0
    representative_source_text = ""
    target_lang = "en"
    document_mode = "form"
    for page in pages:
        if not isinstance(page, dict):
            continue
        boxes = page.get("boxes", [])
        if not isinstance(boxes, list):
            continue
        for box in boxes:
            if not isinstance(box, dict) or box.get("deleted"):
                continue
            box_source_normalized = translation_memory.normalize_source_text(
                box.get("tm_source_normalized") or box.get("tm_source_text") or ""
            )
            if box_source_normalized != source_normalized:
                continue
            updated_count += 1
            box["text"] = target_text
            if not representative_source_text:
                representative_source_text = str(
                    box.get("tm_source_text") or box_source_normalized
                ).strip()
            if box.get("tm_target_lang"):
                target_lang = str(box.get("tm_target_lang"))
            if box.get("tm_document_mode"):
                document_mode = str(box.get("tm_document_mode"))

    edits_payload = {"pages": pages}
    edits_path = job_dir / "edits.json"
    edits_path.write_text(
        json.dumps(edits_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if sync_to_tm and state.PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY:
        document_mode, target_lang = _load_job_translation_context(job_dir, edits_payload)
        with state.TRANSLATION_MEMORY_LOCK:
            memory = translation_memory.load_translation_memory()
            translation_memory.upsert_entry(
                memory,
                representative_source_text or source_normalized,
                target_text,
                target_lang,
                document_mode,
                source_normalized=source_normalized,
                source="editor_consistency",
            )
            translation_memory.write_translation_memory(memory)

    try:
        edited_pdf = ocr.apply_edits_to_pdf(job_id, job_dir, edits_payload)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    jobs.notify_jobs_update()
    return jsonify(
        {
            "ok": True,
            "updated_count": updated_count,
            "edited_pdf_url": url_for(
                "jobs.job_file", job_id=job_id, filename=edited_pdf.name
            ),
        }
    )


@api_bp.route(
    "/job/<job_id>/paragraph-term/apply",
    methods=["POST"],
    endpoint="apply_paragraph_term",
)
def apply_paragraph_term(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)

    payload = request.get_json(force=True) or {}
    pages = payload.get("pages")
    source_term = str(payload.get("source_term") or "").strip()
    replace_from = str(payload.get("replace_from") or "").strip()
    replace_to = str(payload.get("replace_to") or "").strip()
    sync_to_tm = bool(payload.get("sync_to_tm"))
    if not isinstance(pages, list):
        return jsonify({"ok": False, "error": "Invalid pages payload."}), 400
    if not source_term:
        return jsonify({"ok": False, "error": "Missing source_term."}), 400
    if not replace_from:
        return jsonify({"ok": False, "error": "Missing replace_from."}), 400
    if not replace_to:
        return jsonify({"ok": False, "error": "Missing replace_to."}), 400

    normalized_source_term = translation_memory.normalize_source_text(source_term)
    replace_pattern = re.compile(re.escape(replace_from), re.IGNORECASE)
    updated_count = 0

    for page in pages:
        if not isinstance(page, dict):
            continue
        boxes = page.get("boxes", [])
        if not isinstance(boxes, list):
            continue
        for box in boxes:
            if not isinstance(box, dict) or box.get("deleted"):
                continue
            source_text = translation_memory.normalize_source_text(
                box.get("tm_source_text") or box.get("tm_source_normalized") or ""
            )
            if not source_text or normalized_source_term not in source_text:
                continue
            current_text = str(box.get("text") or "")
            next_text, replacements = replace_pattern.subn(replace_to, current_text)
            if replacements <= 0:
                continue
            box["text"] = next_text
            updated_count += 1

    edits_payload = {"pages": pages}
    edits_path = job_dir / "edits.json"
    edits_path.write_text(
        json.dumps(edits_payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    if sync_to_tm and state.PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY:
        document_mode, target_lang = _load_job_translation_context(job_dir, edits_payload)
        with state.TRANSLATION_MEMORY_LOCK:
            memory = translation_memory.load_translation_memory()
            translation_memory.upsert_entry(
                memory,
                source_term,
                replace_to,
                target_lang,
                document_mode,
                source_normalized=normalized_source_term,
                source="editor_paragraph_term",
            )
            translation_memory.write_translation_memory(memory)

    try:
        edited_pdf = ocr.apply_edits_to_pdf(job_id, job_dir, edits_payload)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    jobs.notify_jobs_update()
    return jsonify(
        {
            "ok": True,
            "updated_count": updated_count,
            "edited_pdf_url": url_for(
                "jobs.job_file", job_id=job_id, filename=edited_pdf.name
            ),
        }
    )


@api_bp.route(
    "/job/<job_id>/region-ocr-preview",
    methods=["POST"],
    endpoint="region_ocr_preview",
)
def region_ocr_preview(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)

    payload = request.get_json(force=True) or {}
    try:
        page_idx = int(payload.get("page_index_0based"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid page index."}), 400
    bbox = payload.get("bbox")
    if not isinstance(bbox, dict):
        return jsonify({"ok": False, "error": "Invalid region bbox."}), 400

    try:
        region_data = ocr.run_region_ocr(job_dir, page_idx, bbox)
        source_lines = [
            batch.normalize_text(str(item or ""))
            for item in ocr.build_region_rows(
                region_data.get("rec_polys", []) or [],
                region_data.get("rec_texts", []) or [],
            )
        ]
        source_lines = [item for item in source_lines if item]
        merged_source_text = "\n".join(source_lines).strip()
    except Exception as exc:
        logger.exception("Region OCR preview failed job_id=%s page=%s error=%s", job_id, page_idx, exc)
        return jsonify({"ok": False, "error": str(exc)}), 500

    region_bbox = region_data.get("region_bbox") or bbox
    merged_bbox = region_data.get("merged_bbox") or region_bbox
    ocr_items: list[dict[str, object]] = []
    for poly, text in zip(region_data.get("rec_polys", []) or [], region_data.get("rec_texts", []) or []):
        bbox_payload = batch.poly_to_bbox(poly)
        if not bbox_payload:
            continue
        ocr_items.append({"text": str(text or ""), "bbox": bbox_payload})
    return jsonify(
        {
            "ok": True,
            "page_index_0based": page_idx,
            "region_bbox": region_bbox,
            "merged_bbox": merged_bbox,
            "ocr_lines": source_lines,
            "ocr_items": ocr_items,
            "source_text": merged_source_text,
            "image_data_url": region_data.get("image_data_url"),
        }
    )


def _retranslate_boxes(
    *,
    job_id: str,
    job_dir: Path,
    targets: list[dict[str, object]],
) -> tuple[dict[str, object], int]:
    if not targets:
        return {"ok": False, "error": "No translation targets provided."}, 400

    config = jobs.load_batch_config(job_dir) or {}
    meta = jobs.load_job_meta(job_dir) or {}
    source_lang = str(config.get("source_lang") or "auto")
    target_lang = str(config.get("target_lang") or "en")
    model_name = str(config.get("model") or state.PDF_REALTIME_TRANSLATE_MODEL or state.DOC_TRANSLATE_MODEL)
    document_mode = batch.resolve_document_mode(
        config.get("document_mode") or meta.get("document_mode")
    )
    system_prompt = config.get("system_prompt") or batch.resolve_batch_prompt(target_lang)

    normalized_targets: list[dict[str, object]] = []
    source_texts: list[str] = []
    for item in targets:
        try:
            page_idx = int(item.get("page_index_0based"))
            box_id = int(item.get("box_id"))
        except (TypeError, ValueError):
            return {"ok": False, "error": "Invalid page index or box id."}, 400
        source_text = batch.normalize_text(str(item.get("source_text") or "")).strip()
        if not source_text:
            return {"ok": False, "error": "Missing source text."}, 400
        normalized_targets.append(
            {
                "page_index_0based": page_idx,
                "box_id": box_id,
                "source_text": source_text,
            }
        )
        source_texts.append(source_text)

    try:
        translations = batch.translate_texts_for_region(
            source_texts,
            target_lang=target_lang,
            source_lang=source_lang,
            model_name=model_name,
            system_prompt=system_prompt,
            glossary_entries=glossary.load_combined_glossary(),
        )
    except Exception as exc:
        logger.exception(
            "Box retranslate failed job_id=%s targets=%s error=%s",
            job_id,
            len(normalized_targets),
            exc,
        )
        return {"ok": False, "error": str(exc)}, 500

    if len(translations) != len(normalized_targets):
        return {"ok": False, "error": "Translation result count mismatch."}, 500

    edits_map = jobs.load_edits_map(job_dir)
    updated_items: list[dict[str, object]] = []

    for item, translated in zip(normalized_targets, translations):
        translated_text = batch.normalize_text(translated or "")
        if not translated_text:
            return {"ok": False, "error": "Empty translation result."}, 500

        page_idx = int(item["page_index_0based"])
        box_id = int(item["box_id"])
        source_text = str(item["source_text"])
        page_boxes = list(edits_map.get(page_idx) or [])
        target_box = None
        for box in page_boxes:
            try:
                current_id = int(box.get("id"))
            except (TypeError, ValueError):
                continue
            if current_id == box_id:
                target_box = box
                break
        if target_box is None:
            return {"ok": False, "error": f"Target box not found: {box_id}"}, 404

        normalized_source = batch.normalize_for_translation(source_text)
        target_box["text"] = translated_text
        target_box["tm_source_text"] = source_text
        target_box["tm_target_lang"] = target_lang
        target_box["tm_document_mode"] = document_mode
        if normalized_source:
            target_box["tm_source_normalized"] = normalized_source
        target_box["source"] = "manual_box_retranslate"
        edits_map[page_idx] = page_boxes
        updated_items.append(
            {
                "page_index_0based": page_idx,
                "box_id": box_id,
                "translated_text": translated_text,
            }
        )

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
        return {"ok": False, "error": str(exc)}, 500
    jobs.notify_jobs_update()
    return (
        {
            "ok": True,
            "updated_count": len(updated_items),
            "items": updated_items,
            "edited_pdf_url": url_for(
                "jobs.job_file", job_id=job_id, filename=edited_pdf.name
            ),
        },
        200,
    )


@api_bp.route(
    "/job/<job_id>/retranslate-box",
    methods=["POST"],
    endpoint="retranslate_box",
)
def retranslate_box(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)

    payload = request.get_json(force=True) or {}
    try:
        page_idx = int(payload.get("page_index_0based"))
        box_id = int(payload.get("box_id"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid page index or box id."}), 400

    body, status_code = _retranslate_boxes(
        job_id=job_id,
        job_dir=job_dir,
        targets=[
            {
                "page_index_0based": page_idx,
                "box_id": box_id,
                "source_text": payload.get("source_text"),
            }
        ],
    )
    if status_code != 200:
        return jsonify(body), status_code
    first_item = (body.get("items") or [{}])[0]
    return jsonify(
        {
            "ok": True,
            "page_index_0based": first_item.get("page_index_0based"),
            "box_id": first_item.get("box_id"),
            "translated_text": first_item.get("translated_text"),
            "edited_pdf_url": body.get("edited_pdf_url"),
        }
    )


@api_bp.route(
    "/job/<job_id>/retranslate-boxes",
    methods=["POST"],
    endpoint="retranslate_boxes",
)
def retranslate_boxes(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)

    payload = request.get_json(force=True) or {}
    targets = payload.get("targets")
    if not isinstance(targets, list):
        return jsonify({"ok": False, "error": "Invalid translation targets."}), 400
    body, status_code = _retranslate_boxes(
        job_id=job_id,
        job_dir=job_dir,
        targets=targets,
    )
    return jsonify(body), status_code


@api_bp.route(
    "/job/<job_id>/retranslate-region",
    methods=["POST"],
    endpoint="retranslate_region",
)
def retranslate_region(job_id: str):
    if not jobs.safe_job_id(job_id):
        abort(404)
    if _job_access_denied(job_id):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)

    payload = request.get_json(force=True) or {}
    try:
        page_idx = int(payload.get("page_index_0based"))
    except (TypeError, ValueError):
        return jsonify({"ok": False, "error": "Invalid page index."}), 400
    bbox = payload.get("bbox")
    if not isinstance(bbox, dict):
        return jsonify({"ok": False, "error": "Invalid region bbox."}), 400
    replace_existing = bool(payload.get("replace_existing", True))

    config = jobs.load_batch_config(job_dir) or {}
    meta = jobs.load_job_meta(job_dir) or {}
    source_lang = str(config.get("source_lang") or "auto")
    target_lang = str(config.get("target_lang") or "en")
    model_name = str(config.get("model") or state.PDF_REALTIME_TRANSLATE_MODEL or state.DOC_TRANSLATE_MODEL)
    document_mode = batch.resolve_document_mode(
        config.get("document_mode") or meta.get("document_mode")
    )
    system_prompt = config.get("system_prompt") or batch.resolve_batch_prompt(target_lang)

    try:
        merged_source_text = batch.normalize_text(str(payload.get("source_text") or "")).strip()
        merged_bbox = payload.get("merged_bbox")
        if merged_source_text:
            region_data = {"region_bbox": bbox, "merged_bbox": merged_bbox or bbox, "rec_polys": []}
        else:
            region_data = ocr.run_region_ocr(job_dir, page_idx, bbox)
            source_lines = [
                batch.normalize_text(str(item or ""))
                for item in ocr.build_region_rows(
                    region_data.get("rec_polys", []) or [],
                    region_data.get("rec_texts", []) or [],
                )
            ]
            source_lines = [item for item in source_lines if item]
            merged_source_text = "\n".join(source_lines).strip()
        translations = batch.translate_texts_for_region(
            [merged_source_text] if merged_source_text else [],
            target_lang=target_lang,
            source_lang=source_lang,
            model_name=model_name,
            system_prompt=system_prompt,
            glossary_entries=glossary.load_combined_glossary(),
        )
    except Exception as exc:
        logger.exception("Region retranslate failed job_id=%s page=%s error=%s", job_id, page_idx, exc)
        return jsonify({"ok": False, "error": str(exc)}), 500

    edits_map = jobs.load_edits_map(job_dir)
    page_boxes = list(edits_map.get(page_idx) or [])
    region_bbox = region_data.get("region_bbox") or bbox
    if replace_existing:
        for box in page_boxes:
            if box.get("deleted") or not bool(box.get("auto_generated", True)):
                continue
            if ocr.bbox_intersects(box.get("bbox"), region_bbox):
                box["deleted"] = True

    existing_ids = {
        int(box.get("id") or 0)
        for box in page_boxes
        if isinstance(box, dict) and str(box.get("id") or "").strip()
    }
    next_id = (max(existing_ids) + 1) if existing_ids else 300000

    def build_tm_meta(source_text: str) -> dict[str, str]:
        normalized_source = batch.normalize_for_translation(source_text)
        payload = {
            "tm_source_text": str(source_text or ""),
            "tm_target_lang": target_lang,
            "tm_document_mode": document_mode,
        }
        if normalized_source:
            payload["tm_source_normalized"] = normalized_source
        return payload

    merged_bbox = region_data.get("merged_bbox")
    region_polys = region_data.get("rec_polys", []) or []
    if not merged_bbox and region_polys:
        xs: list[float] = []
        ys: list[float] = []
        for poly in region_polys:
            for point in poly[:4]:
                if isinstance(point, (list, tuple)) and len(point) >= 2:
                    xs.append(float(point[0]))
                    ys.append(float(point[1]))
        if xs and ys:
            merged_bbox = {
                "x": min(xs),
                "y": min(ys),
                "w": max(xs) - min(xs),
                "h": max(ys) - min(ys),
            }
    if not merged_bbox:
        merged_bbox = region_bbox

    created = 0
    translated_text = batch.normalize_text(translations[0] if translations else "")
    if merged_source_text and translated_text and not batch.is_numeric_only(translated_text):
        page_boxes.append(
            {
                "id": next_id,
                "bbox": merged_bbox,
                "text": translated_text,
                "deleted": False,
                "auto_generated": True,
                "no_clip": True,
                "source": "manual_region_retranslate",
                "font_size": state.DEFAULT_FONT_SIZE_PX,
                "color": state.DEFAULT_TEXT_COLOR,
                "text_align": "left",
                "rotation": 0,
                **build_tm_meta(merged_source_text),
            }
        )
        created = 1

    edits_map[page_idx] = page_boxes
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
            "boxes_added": created,
            "edited_pdf_url": url_for(
                "jobs.job_file", job_id=job_id, filename=edited_pdf.name
            ),
        }
    )
