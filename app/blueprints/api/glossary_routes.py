from __future__ import annotations

from .shared import (
    _forbidden_json,
    authz_service,
    current_app,
    current_user,
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


def _require_glossary_admin_for_write() -> object | None:
    if current_app.config.get("AUTH_ENABLED", False) and not authz_service.user_is_admin(current_user):
        return _forbidden_json()
    return None


def _parse_bool_param(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _request_library_id() -> int | None:
    raw_value = request.args.get("library_id") or request.form.get("library_id")
    if raw_value is None:
        payload = request.get_json(silent=True) or {}
        raw_value = payload.get("library_id") if isinstance(payload, dict) else None
    if raw_value is None or str(raw_value).strip() == "":
        return None
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        raise glossary.DepartmentGlossarySelectionError(
            "invalid_department_glossary",
            "選擇的部門詞彙庫格式不正確",
        ) from None


def _selected_glossary_payload(*, fallback_to_default: bool = True) -> dict[str, object]:
    library_id = _request_library_id()
    if library_id is None and not fallback_to_default:
        raise glossary.DepartmentGlossarySelectionError(
            "missing_department_glossary",
            "請選擇部門詞彙庫",
        )
    return glossary.build_glossary_management_payload(
        library_id=library_id,
        include_inactive_entries=_parse_bool_param(request.args.get("include_inactive")),
    )


def _glossary_selection_error_response(exc: glossary.DepartmentGlossarySelectionError):
    status_code = 404 if exc.code == "department_glossary_not_found" else 400
    return jsonify({"ok": False, "error": exc.user_message, "code": exc.code}), status_code


@api_bp.route("/glossary", methods=["GET", "POST"], endpoint="global_glossary")
def global_glossary():
    if request.method == "GET":
        return jsonify({"ok": True, "glossary": glossary.load_default_department_glossary_items()})
    forbidden = _require_glossary_admin_for_write()
    if forbidden is not None:
        return forbidden
    payload = request.get_json(force=True) or {}
    items = payload.get("glossary", [])
    if not isinstance(items, list):
        return jsonify({"ok": False, "error": "Invalid glossary payload."}), 400
    synced_items = glossary.sync_default_department_glossary_items(items)
    jobs.notify_jobs_update()
    return jsonify({"ok": True, "glossary": synced_items})


@api_bp.route("/glossary/library", methods=["GET"], endpoint="glossary_library")
def glossary_library():
    try:
        return jsonify({"ok": True, **_selected_glossary_payload()})
    except glossary.DepartmentGlossarySelectionError as exc:
        return _glossary_selection_error_response(exc)


def _glossary_library_error_response(exc: glossary.DepartmentGlossaryLibraryError):
    status_code = 409 if exc.code == "department_glossary_library_has_active_jobs" else 400
    if exc.code == "department_glossary_library_not_found":
        status_code = 404
    return jsonify({"ok": False, "error": exc.user_message, "code": exc.code}), status_code


@api_bp.route("/glossary/libraries", methods=["POST"], endpoint="glossary_libraries_create")
def glossary_libraries_create():
    forbidden = _require_glossary_admin_for_write()
    if forbidden is not None:
        return forbidden
    payload = request.get_json(force=True) or {}
    try:
        library = glossary.create_department_glossary_library(
            name=payload.get("name"),
            department_code=payload.get("department_code"),
        )
    except glossary.DepartmentGlossaryLibraryError as exc:
        return _glossary_library_error_response(exc)
    jobs.notify_jobs_update()
    return jsonify(
        {
            "ok": True,
            "library": glossary.department_glossary_library_to_payload(library),
            **glossary.build_glossary_management_payload(library_id=library.library_id),
        }
    )


@api_bp.route(
    "/glossary/libraries/<int:library_id>",
    methods=["PATCH"],
    endpoint="glossary_libraries_update",
)
def glossary_libraries_update(library_id: int):
    forbidden = _require_glossary_admin_for_write()
    if forbidden is not None:
        return forbidden
    payload = request.get_json(force=True) or {}
    try:
        library = glossary.update_department_glossary_library(
            library_id,
            name=payload.get("name"),
            department_code=payload.get("department_code"),
        )
    except glossary.DepartmentGlossaryLibraryError as exc:
        return _glossary_library_error_response(exc)
    jobs.notify_jobs_update()
    return jsonify(
        {
            "ok": True,
            "library": glossary.department_glossary_library_to_payload(library),
            **glossary.build_glossary_management_payload(library_id=library.library_id),
        }
    )


@api_bp.route(
    "/glossary/libraries/<int:library_id>/disable",
    methods=["POST"],
    endpoint="glossary_libraries_disable",
)
def glossary_libraries_disable(library_id: int):
    forbidden = _require_glossary_admin_for_write()
    if forbidden is not None:
        return forbidden
    try:
        library = glossary.disable_department_glossary_library(library_id)
    except glossary.DepartmentGlossaryLibraryError as exc:
        return _glossary_library_error_response(exc)
    jobs.notify_jobs_update()
    return jsonify(
        {
            "ok": True,
            "library": glossary.department_glossary_library_to_payload(library),
            **glossary.build_glossary_management_payload(library_id=library.library_id),
        }
    )


@api_bp.route(
    "/glossary/libraries/<int:library_id>/activate",
    methods=["POST"],
    endpoint="glossary_libraries_activate",
)
def glossary_libraries_activate(library_id: int):
    forbidden = _require_glossary_admin_for_write()
    if forbidden is not None:
        return forbidden
    try:
        library = glossary.activate_department_glossary_library(library_id)
    except glossary.DepartmentGlossaryLibraryError as exc:
        return _glossary_library_error_response(exc)
    jobs.notify_jobs_update()
    return jsonify(
        {
            "ok": True,
            "library": glossary.department_glossary_library_to_payload(library),
            **glossary.build_glossary_management_payload(library_id=library.library_id),
        }
    )


@api_bp.route(
    "/glossary/libraries/<int:library_id>/entries",
    methods=["POST"],
    endpoint="glossary_library_entries_upsert",
)
def glossary_library_entries_upsert(library_id: int):
    forbidden = _require_glossary_admin_for_write()
    if forbidden is not None:
        return forbidden
    payload = request.get_json(force=True) or {}
    cn = str(payload.get("cn") or payload.get("source_term") or "").strip()
    en = str(payload.get("en") or payload.get("target_term") or "").strip()
    if not cn or not en:
        return jsonify({"ok": False, "error": "請輸入完整的中文與英文詞彙"}), 400
    try:
        selected = glossary.resolve_selected_department_glossary(
            library_id,
            require_active=False,
        )
        entry_id = glossary.upsert_department_glossary_entry(
            library_id=selected.library_id,
            source_lang="zh",
            target_lang="en",
            source_term=cn,
            target_term=en,
        )
        entries = glossary.list_department_glossary_entries(
            selected.library_id,
            active_only=False,
        )
        entry = next((item for item in entries if item.entry_id == entry_id), None)
        response_payload = glossary.build_glossary_management_payload(library_id=selected.library_id)
    except glossary.DepartmentGlossarySelectionError as exc:
        return _glossary_selection_error_response(exc)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    jobs.notify_jobs_update()
    return jsonify(
        {
            "ok": True,
            "entry": glossary.department_glossary_entry_to_payload(entry) if entry is not None else None,
            **response_payload,
        }
    )


@api_bp.route(
    "/glossary/libraries/<int:library_id>/entries/<int:entry_id>",
    methods=["PATCH"],
    endpoint="glossary_library_entries_update",
)
def glossary_library_entries_update(library_id: int, entry_id: int):
    forbidden = _require_glossary_admin_for_write()
    if forbidden is not None:
        return forbidden
    payload = request.get_json(force=True) or {}
    cn = str(payload.get("cn") or payload.get("source_term") or "").strip()
    en = str(payload.get("en") or payload.get("target_term") or "").strip()
    if not cn or not en:
        return jsonify({"ok": False, "error": "請輸入完整的中文與英文詞彙"}), 400
    try:
        selected = glossary.resolve_selected_department_glossary(
            library_id,
            require_active=False,
        )
        entry = glossary.update_department_glossary_entry(
            entry_id,
            library_id=selected.library_id,
            source_term=cn,
            target_term=en,
        )
        response_payload = glossary.build_glossary_management_payload(library_id=selected.library_id)
    except glossary.DepartmentGlossarySelectionError as exc:
        return _glossary_selection_error_response(exc)
    except ValueError as exc:
        message = str(exc)
        status_code = 404 if "not found" in message.lower() else 400
        return jsonify({"ok": False, "error": message}), status_code
    jobs.notify_jobs_update()
    return jsonify(
        {
            "ok": True,
            "entry": glossary.department_glossary_entry_to_payload(entry),
            **response_payload,
        }
    )


@api_bp.route(
    "/glossary/libraries/<int:library_id>/entries/<int:entry_id>/disable",
    methods=["POST"],
    endpoint="glossary_library_entries_disable",
)
def glossary_library_entries_disable(library_id: int, entry_id: int):
    forbidden = _require_glossary_admin_for_write()
    if forbidden is not None:
        return forbidden
    try:
        selected = glossary.resolve_selected_department_glossary(
            library_id,
            require_active=False,
        )
        entries = glossary.list_department_glossary_entries(
            selected.library_id,
            active_only=False,
        )
        if not any(entry.entry_id == entry_id for entry in entries):
            return jsonify({"ok": False, "error": "詞彙不存在"}), 404
        glossary.disable_department_glossary_entry(entry_id)
        response_payload = glossary.build_glossary_management_payload(library_id=selected.library_id)
    except glossary.DepartmentGlossarySelectionError as exc:
        return _glossary_selection_error_response(exc)
    jobs.notify_jobs_update()
    return jsonify({"ok": True, **response_payload})


@api_bp.route("/glossary/system-export", methods=["GET"], endpoint="glossary_system_export")
def glossary_system_export():
    try:
        library_id = _request_library_id()
        workbook = glossary.export_system_glossary_excel(library_id=library_id)
    except glossary.DepartmentGlossarySelectionError as exc:
        return _glossary_selection_error_response(exc)
    return send_file(
        io.BytesIO(workbook),
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        as_attachment=True,
        download_name="department_glossary.xlsx" if library_id is not None else "system_glossary.xlsx",
    )


@api_bp.route("/glossary/export-json", methods=["GET"], endpoint="glossary_export_json")
def glossary_export_json():
    try:
        library_id = _request_library_id()
        items = glossary.load_department_glossary_items(library_id)
    except glossary.DepartmentGlossarySelectionError as exc:
        return _glossary_selection_error_response(exc)
    return jsonify({"ok": True, "glossary": items})


@api_bp.route("/glossary/import-json", methods=["POST"], endpoint="glossary_import_json")
def glossary_import_json():
    forbidden = _require_glossary_admin_for_write()
    if forbidden is not None:
        return forbidden
    payload = request.get_json(force=True) or {}
    items = payload.get("glossary", payload.get("items", []))
    if not isinstance(items, list):
        return jsonify({"ok": False, "error": "Invalid glossary payload."}), 400
    try:
        library_id = _request_library_id()
        if library_id is None:
            library_id = glossary.get_or_create_default_department_glossary().library_id
        merged_items = glossary.apply_system_glossary_import(items, library_id=library_id)
        response_payload = glossary.build_glossary_management_payload(library_id=library_id)
    except glossary.DepartmentGlossarySelectionError as exc:
        return _glossary_selection_error_response(exc)
    jobs.notify_jobs_update()
    return jsonify({"ok": True, "system_glossary": merged_items, **response_payload})


@api_bp.route("/glossary/system-import-preview", methods=["POST"], endpoint="glossary_system_import_preview")
def glossary_system_import_preview():
    upload = request.files.get("file")
    if upload is None or not str(upload.filename or "").strip():
        return jsonify({"ok": False, "error": "Missing Excel file."}), 400
    filename = str(upload.filename or "").strip().lower()
    if not (filename.endswith(".xlsx") or filename.endswith(".json")):
        return jsonify({"ok": False, "error": "Only .xlsx and .json files are supported."}), 400
    try:
        library_id = _request_library_id()
        file_bytes = upload.read()
        parsed = (
            glossary.parse_system_glossary_json(file_bytes)
            if filename.endswith(".json")
            else glossary.parse_system_glossary_excel(file_bytes)
        )
        preview = glossary.build_system_glossary_import_preview(parsed["items"], library_id=library_id)
    except glossary.DepartmentGlossarySelectionError as exc:
        return _glossary_selection_error_response(exc)
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, **parsed, **preview})


@api_bp.route("/glossary/system-import-apply", methods=["POST"], endpoint="glossary_system_import_apply")
def glossary_system_import_apply():
    forbidden = _require_glossary_admin_for_write()
    if forbidden is not None:
        return forbidden
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
    try:
        library_id = _request_library_id()
        if library_id is None:
            library_id = glossary.get_or_create_default_department_glossary().library_id
        merged_items = glossary.apply_system_glossary_import(items, library_id=library_id)
        response_payload = glossary.build_glossary_management_payload(library_id=library_id)
    except glossary.DepartmentGlossarySelectionError as exc:
        return _glossary_selection_error_response(exc)
    jobs.notify_jobs_update()
    return jsonify(
        {
            "ok": True,
            "system_glossary": merged_items,
            **response_payload,
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
