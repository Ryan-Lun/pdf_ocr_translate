from __future__ import annotations

import io
import json
import logging
import re
import time
from typing import Any

import fitz
from flask import Blueprint, Response, abort, current_app, jsonify, request, send_file, stream_with_context, url_for
from flask_login import current_user

from ...services import audit_service, auth_store, authz_service, batch, doc_workspace, document_templates, glossary, jobs, ocr, state, translation_memory, word_translate

logger = logging.getLogger(__name__)

api_bp = Blueprint(
    "api",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/static/api",
    url_prefix="/api",
)


def _current_owner_work_id() -> str:
    if getattr(current_user, "is_authenticated", False):
        return " ".join(str(getattr(current_user, "work_id", "") or "").split()).strip()
    return ""


def _current_editor_identity() -> tuple[str, str]:
    work_id = _current_owner_work_id()
    if not work_id and getattr(current_user, "is_authenticated", False):
        try:
            work_id = " ".join(str(current_user.get_id() or "").split()).strip()
        except Exception:
            work_id = ""
    if not work_id:
        work_id = "anonymous"

    display_name = ""
    if getattr(current_user, "is_authenticated", False):
        display_name = " ".join(str(getattr(current_user, "display_name", "") or "").split()).strip()
    return work_id, display_name or work_id


def _current_access_scope() -> tuple[str, bool]:
    return _current_owner_work_id(), (
        not current_app.config.get("AUTH_ENABLED", False)
        or authz_service.user_is_admin(current_user)
        or not authz_service.owner_access_enabled()
    )


def _can_view_active_editors() -> bool:
    return authz_service.user_is_admin(current_user)


def _forbidden_json():
    return jsonify({"ok": False, "error": "Forbidden."}), 403


def _get_accessible_template(template_id: str) -> dict[str, Any] | None:
    return document_templates.get_document_template(
        template_id,
        include_all=True,
    )


def _document_template_source_jobs() -> list[dict[str, Any]]:
    templates = document_templates.load_document_templates(include_all=True)
    source_job_ids = {
        str(template.get("source_job_id") or "").strip()
        for template in templates
        if jobs.safe_job_id(str(template.get("source_job_id") or "").strip())
    }
    if not source_job_ids:
        return []
    items = []
    for item in jobs.build_jobs_list(job_type="template_source", include_all=True):
        if item.get("job_id") not in source_job_ids:
            continue
        items.append(
            {
                "job_id": item.get("job_id"),
                "status_code": item.get("status_code"),
                "status_label": item.get("status_label"),
                "status": item.get("status"),
                "can_open_editor": True,
            }
        )
    return items


def _is_global_template_source_job(job_id: str) -> bool:
    cleaned_job_id = str(job_id or "").strip()
    if not jobs.safe_job_id(cleaned_job_id):
        return False
    return document_templates.get_document_template_by_job(cleaned_job_id, include_all=True) is not None


def _can_edit_template(template: dict[str, Any]) -> bool:
    return template is not None


def _can_delete_template(template: dict[str, Any]) -> bool:
    if not current_app.config.get("AUTH_ENABLED", False):
        return True
    if not authz_service.owner_access_enabled():
        return True
    source_job_id = str(template.get("source_job_id") or "").strip()
    if source_job_id:
        return not _job_access_denied(source_job_id, allow_global_template_source=False)
    if authz_service.user_is_admin(current_user):
        return True
    owner_work_id = authz_service.normalize_work_id(template.get("owner_work_id"))
    return bool(owner_work_id and owner_work_id == authz_service.current_work_id(current_user))


def _template_creator_payload(template: dict[str, Any]) -> dict[str, str]:
    owner_work_id = authz_service.normalize_work_id(template.get("owner_work_id"))
    if not owner_work_id:
        return {"creator_work_id": "", "creator_label": ""}
    creator_label = owner_work_id
    try:
        snapshot = auth_store.get_local_user_snapshot(owner_work_id)
    except Exception:
        snapshot = None
    if snapshot is not None and getattr(snapshot, "display_name", ""):
        creator_label = str(snapshot.display_name)
    return {"creator_work_id": owner_work_id, "creator_label": creator_label}


def _template_response_payload(template: dict[str, Any]) -> dict[str, Any]:
    item = dict(template)
    item["can_delete"] = _can_delete_template(item)
    item["can_edit_source"] = _can_edit_template(item)
    item.update(_template_creator_payload(item))
    return item


def _templates_response_payload(templates: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_template_response_payload(template) for template in templates]


def _job_access_denied(job_id: str, *, allow_global_template_source: bool = True) -> bool:
    if allow_global_template_source and _is_global_template_source_job(job_id):
        return False
    if not current_app.config.get("AUTH_ENABLED", False):
        return False
    if not authz_service.owner_access_enabled():
        return False
    return not authz_service.can_access_job(current_user, job_id)


def _load_job_translation_context(job_dir, payload: dict[str, Any] | None = None) -> tuple[str, str]:
    config = jobs.load_batch_config(job_dir) or {}
    document_mode = batch.resolve_document_mode(
        config.get("document_mode") or (jobs.load_job_meta(job_dir) or {}).get("document_mode")
    )
    target_lang = str(config.get("target_lang") or "en")
    if isinstance(payload, dict):
        for page in payload.get("pages", []):
            if not isinstance(page, dict):
                continue
            for box in page.get("boxes", []):
                if not isinstance(box, dict):
                    continue
                box_mode = str(box.get("tm_document_mode") or "").strip()
                box_lang = str(box.get("tm_target_lang") or "").strip()
                if box_mode:
                    document_mode = box_mode
                if box_lang:
                    target_lang = box_lang
                if box_mode or box_lang:
                    return document_mode, target_lang
    return document_mode, target_lang


def _empty_editor_page(
    page_index_0based: int,
    *,
    image_url: str | None = None,
    image_size_px: list[int] | None = None,
) -> dict[str, Any]:
    return {
        "page_index_0based": page_index_0based,
        "input_image": "",
        "image_url": image_url,
        "image_size_px": image_size_px,
        "rec_polys": [],
        "rec_texts": [],
        "edit_texts": [],
        "rec_scores": [],
        "font_sizes": [],
        "colors": [],
        "alignments": [],
        "rotations": [],
        "box_ids": [],
        "no_clips": [],
        "auto_generated_flags": [],
        "tm_source_texts": [],
        "tm_source_normalizeds": [],
        "tm_target_langs": [],
        "tm_document_modes": [],
    }


def _pdf_page_count(pdf_path) -> int:
    try:
        doc = fitz.open(pdf_path)
        try:
            return int(doc.page_count)
        finally:
            doc.close()
    except Exception:
        return 0


def _ensure_editor_page_image(pdf_path, images_dir, page_index_0based: int, dpi: int = 200) -> tuple[str, list[int]] | None:
    out_name = f"editor_page_{page_index_0based + 1:04d}.png"
    out_path = images_dir / out_name
    if out_path.exists():
        try:
            pix = fitz.Pixmap(out_path.as_posix())
            try:
                return out_name, [int(pix.width), int(pix.height)]
            finally:
                pix = None
        except Exception:
            pass
    try:
        images_dir.mkdir(parents=True, exist_ok=True)
        doc = fitz.open(pdf_path)
        try:
            page = doc.load_page(page_index_0based)
            mat = fitz.Matrix(dpi / 72.0, dpi / 72.0)
            pix = page.get_pixmap(matrix=mat, alpha=False)
            pix.save(out_path.as_posix())
            return out_name, [int(pix.width), int(pix.height)]
        finally:
            doc.close()
    except Exception:
        return None




__all__ = [
    name
    for name in globals()
    if name != "__builtins__" and not (name.startswith("__") and name.endswith("__"))
]
