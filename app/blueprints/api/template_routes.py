from __future__ import annotations

from .shared import (
    Any,
    _can_delete_template,
    _can_edit_template,
    _current_owner_work_id,
    _forbidden_json,
    _get_accessible_template,
    _job_access_denied,
    _template_response_payload,
    _templates_response_payload,
    abort,
    api_bp,
    batch,
    document_templates,
    jobs,
    json,
    jsonify,
    ocr,
    request,
    state,
    url_for,
)


@api_bp.route("/document-templates", methods=["GET", "POST"], endpoint="document_templates")
def manage_document_templates():
    owner_work_id = _current_owner_work_id()
    if request.method == "GET":
        return jsonify(
            {
                "ok": True,
                "templates": _templates_response_payload(
                    document_templates.load_document_templates(include_all=True)
                ),
            }
        )

    payload = request.get_json(force=True) or {}
    template_id = str(payload.get("id") or "").strip()
    source_job_id = str(payload.get("source_job_id") or "").strip()
    existing = document_templates.get_document_template(template_id, include_all=True) if template_id else None
    existing_source_job_id = str((existing or {}).get("source_job_id") or "").strip()
    if existing is not None and not _can_edit_template(existing):
        return _forbidden_json()
    source_job_id = source_job_id or existing_source_job_id
    if source_job_id and _job_access_denied(source_job_id):
        return _forbidden_json()
    try:
        template = document_templates.save_document_template(
            payload,
            owner_work_id=owner_work_id,
        )
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    return jsonify({"ok": True, "template": _template_response_payload(template)})


@api_bp.route(
    "/document-templates/<template_id>",
    methods=["DELETE"],
    endpoint="delete_document_template",
)
def delete_document_template(template_id: str):
    template = _get_accessible_template(template_id)
    if template is None:
        return jsonify({"ok": False, "error": "Template not found."}), 404
    if not _can_delete_template(template):
        return _forbidden_json()
    source_job_id = str(template.get("source_job_id") or "").strip()
    if source_job_id:
        if _job_access_denied(source_job_id):
            return _forbidden_json()
        deleted_job, error = jobs.delete_job_dir(source_job_id)
        if not deleted_job and error:
            return jsonify({"ok": False, "error": error}), 500
    deleted = document_templates.delete_document_template(template_id)
    if not deleted:
        return jsonify({"ok": False, "error": "Template not found."}), 404
    return jsonify({"ok": True, "deleted": True})


@api_bp.route(
    "/document-templates/<template_id>/name",
    methods=["PATCH"],
    endpoint="rename_document_template",
)
def rename_document_template(template_id: str):
    template = _get_accessible_template(template_id)
    if template is None:
        return jsonify({"ok": False, "error": "Template not found."}), 404
    if not _can_edit_template(template):
        return _forbidden_json()
    payload = request.get_json(force=True) or {}
    name = str(payload.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Template name is required."}), 400
    renamed = document_templates.rename_document_template(template_id, name)
    if renamed is None:
        return jsonify({"ok": False, "error": "Template not found."}), 404
    return jsonify({"ok": True, "template": _template_response_payload(renamed)})


def _build_page_boxes_for_save(
    page_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    def _item(values: Any, index: int, default: Any) -> Any:
        if isinstance(values, list) and index < len(values):
            return values[index]
        return default

    boxes: list[dict[str, Any]] = []
    rec_polys = page_payload.get("rec_polys") or []
    count = len(rec_polys)
    for index in range(count):
        bbox = batch.poly_to_bbox(rec_polys[index])
        if not bbox:
            continue
        boxes.append(
            {
                "id": int(_item(page_payload.get("box_ids"), index, index) or index),
                "deleted": False,
                "bbox": bbox,
                "text": str(_item(page_payload.get("edit_texts"), index, "") or ""),
                "font_size": float(_item(page_payload.get("font_sizes"), index, 0.0) or 0.0),
                "no_clip": bool(_item(page_payload.get("no_clips"), index, False)),
                "color": str(_item(page_payload.get("colors"), index, state.DEFAULT_TEXT_COLOR) or state.DEFAULT_TEXT_COLOR),
                "text_align": str(_item(page_payload.get("alignments"), index, "left") or "left"),
                "rotation": int(_item(page_payload.get("rotations"), index, 0) or 0),
                "auto_generated": bool(_item(page_payload.get("auto_generated_flags"), index, True)),
                "tm_source_text": str(_item(page_payload.get("tm_source_texts"), index, "") or ""),
                "tm_source_normalized": str(_item(page_payload.get("tm_source_normalizeds"), index, "") or ""),
                "tm_target_lang": str(_item(page_payload.get("tm_target_langs"), index, "") or ""),
                "tm_document_mode": str(_item(page_payload.get("tm_document_modes"), index, "") or ""),
            }
        )
    return boxes


@api_bp.route(
    "/document-templates/<template_id>/apply",
    methods=["POST"],
    endpoint="apply_document_template",
)
def apply_document_template(template_id: str):
    template = _get_accessible_template(template_id)
    if template is None:
        return jsonify({"ok": False, "error": "Template not found."}), 404

    payload = request.get_json(force=True) or {}
    job_id = str(payload.get("job_id") or "").strip()
    if not jobs.safe_job_id(job_id):
        return jsonify({"ok": False, "error": "Invalid job id."}), 400
    if _job_access_denied(job_id, allow_global_template_source=False):
        return _forbidden_json()
    job_dir = jobs.job_dir(job_id)
    if not job_dir.exists():
        abort(404)

    json_dir = job_dir / "ocr_json"
    if not json_dir.exists():
        abort(404)

    edits_map = jobs.load_edits_map(job_dir)
    json_paths = sorted(json_dir.glob("*_res_with_pdf_coords.json"))
    pages_payload: list[dict[str, Any]] = []
    all_boxes: list[dict[str, Any]] = []
    template_pages = {
        int(page.get("page_index_0based") or 0): page
        for page in template.get("pages", [])
        if isinstance(page, dict)
    }

    next_id = 1
    for path in json_paths:
        data = json.loads(path.read_text(encoding="utf-8"))
        page_idx = int(data.get("page_index_0based", 0))
        edits_boxes = edits_map.get(page_idx) if page_idx in edits_map else None
        page_payload = ocr.load_page_data(path, edits_boxes=edits_boxes, data=data)
        boxes = _build_page_boxes_for_save(page_payload)
        all_boxes.extend(boxes)
        pages_payload.append(
            {
                "page_index_0based": page_idx,
                "image_size_px": page_payload.get("image_size_px"),
                "boxes": boxes,
            }
        )
        page_max = max((int(box.get("id") or 0) for box in boxes), default=0)
        next_id = max(next_id, page_max + 1)

    created_count = 0
    for page in pages_payload:
        page_idx = int(page["page_index_0based"])
        template_page = template_pages.get(page_idx)
        image_size = page.get("image_size_px") or []
        if not template_page or not isinstance(image_size, list) or len(image_size) != 2:
            continue
        width = float(image_size[0] or 0.0)
        height = float(image_size[1] or 0.0)
        if width <= 0 or height <= 0:
            continue
        for template_box in template_page.get("boxes", []):
            if not isinstance(template_box, dict):
                continue
            box_w = max(1.0, float(template_box.get("w_ratio") or 0.0) * width)
            box_h = max(1.0, float(template_box.get("h_ratio") or 0.0) * height)
            box_x = max(0.0, min(float(template_box.get("x_ratio") or 0.0) * width, max(0.0, width - box_w)))
            box_y = max(0.0, min(float(template_box.get("y_ratio") or 0.0) * height, max(0.0, height - box_h)))
            page["boxes"].append(
                {
                    "id": next_id,
                    "deleted": False,
                    "bbox": {"x": box_x, "y": box_y, "w": box_w, "h": box_h},
                    "text": str(template_box.get("text") or ""),
                    "font_size": float(template_box.get("font_size") or state.DEFAULT_FONT_SIZE_PX),
                    "no_clip": bool(template_box.get("no_clip")),
                    "color": str(template_box.get("color") or state.DEFAULT_TEXT_COLOR),
                    "text_align": str(template_box.get("text_align") or "left"),
                    "rotation": int(template_box.get("rotation") or 0),
                    "auto_generated": True,
                    "tm_source_text": "",
                    "tm_source_normalized": "",
                    "tm_target_lang": "",
                    "tm_document_mode": "",
                }
            )
            next_id += 1
            created_count += 1

    if not created_count:
        return jsonify({"ok": False, "error": "Template has no matching target pages."}), 400

    edits_payload = {
        "pages": [
            {
                "page_index_0based": page["page_index_0based"],
                "boxes": page["boxes"],
            }
            for page in pages_payload
        ]
    }
    (job_dir / "edits.json").write_text(
        json.dumps(edits_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    try:
        edited_pdf = ocr.apply_edits_to_pdf(job_id, job_dir, edits_payload)
    except Exception as exc:
        return jsonify({"ok": False, "error": str(exc)}), 500
    jobs.notify_jobs_update()
    return jsonify(
        {
            "ok": True,
            "job_id": job_id,
            "created_count": created_count,
            "edited_pdf_url": url_for("jobs.job_file", job_id=job_id, filename=edited_pdf.name),
        }
    )
