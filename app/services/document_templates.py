from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select

from . import job_store, state


def _clamp_ratio(value: Any) -> float:
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return 0.0
    if numeric < 0:
        return 0.0
    if numeric > 1:
        return 1.0
    return numeric


def _normalize_box(box: Any) -> dict[str, Any] | None:
    if not isinstance(box, dict):
        return None
    text = str(box.get("text") or "").strip()
    if not text:
        return None
    try:
        font_size = float(box.get("font_size") or state.DEFAULT_FONT_SIZE_PX)
    except (TypeError, ValueError):
        font_size = float(state.DEFAULT_FONT_SIZE_PX)
    normalized = {
        "x_ratio": _clamp_ratio(box.get("x_ratio")),
        "y_ratio": _clamp_ratio(box.get("y_ratio")),
        "w_ratio": _clamp_ratio(box.get("w_ratio")),
        "h_ratio": _clamp_ratio(box.get("h_ratio")),
        "text": text,
        "font_size": max(1.0, font_size),
        "color": str(box.get("color") or state.DEFAULT_TEXT_COLOR),
        "text_align": str(box.get("text_align") or "").strip().lower(),
        "rotation": int(box.get("rotation") or 0) % 360,
        "no_clip": bool(box.get("no_clip", False)),
    }
    if normalized["text_align"] not in {"left", "center", "right"}:
        normalized["text_align"] = "left"
    return normalized


def _normalize_page(page: Any) -> dict[str, Any] | None:
    if not isinstance(page, dict):
        return None
    try:
        page_index = int(page.get("page_index_0based") or 0)
    except (TypeError, ValueError):
        page_index = 0
    boxes = []
    for raw_box in page.get("boxes", []):
        normalized_box = _normalize_box(raw_box)
        if normalized_box:
            boxes.append(normalized_box)
    return {
        "page_index_0based": max(0, page_index),
        "boxes": boxes,
    }


def _normalize_template(template: Any) -> dict[str, Any] | None:
    if not isinstance(template, dict):
        return None
    template_id = str(template.get("id") or "").strip() or uuid.uuid4().hex
    source_job_id = str(template.get("source_job_id") or "").strip()
    template_name = str(template.get("name") or "").strip()
    display_name = str(template.get("display_name") or template_name or source_job_id or template_id).strip()
    status = str(template.get("status") or "draft").strip().lower()
    if status not in {"draft", "saved"}:
        status = "draft"
    now_ts = float(time.time())
    try:
        created_at = float(template.get("created_at") or now_ts)
    except (TypeError, ValueError):
        created_at = now_ts
    try:
        updated_at = float(template.get("updated_at") or now_ts)
    except (TypeError, ValueError):
        updated_at = now_ts
    pages = []
    for raw_page in template.get("pages", []):
        normalized_page = _normalize_page(raw_page)
        if normalized_page:
            pages.append(normalized_page)
    pages.sort(key=lambda item: item["page_index_0based"])
    saved_name = template_name if template_name else ""
    if status == "saved" and not saved_name:
        return None
    return {
        "id": template_id,
        "name": saved_name,
        "display_name": display_name or saved_name or template_id,
        "status": status,
        "source_job_id": source_job_id,
        "created_at": created_at,
        "updated_at": updated_at,
        "pages": pages,
    }


def _to_timestamp(value: datetime | None) -> float:
    if value is None:
        return time.time()
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return float(value.timestamp())


def _to_datetime(timestamp: float | None) -> datetime:
    if timestamp is None:
        timestamp = time.time()
    return datetime.fromtimestamp(float(timestamp), tz=timezone.utc)


def _deserialize_template_payload(record: job_store.DocumentTemplateRecord) -> dict[str, Any]:
    raw_payload = str(record.payload_json or "").strip()
    if not raw_payload:
        pages: list[dict[str, Any]] = []
    else:
        try:
            decoded = json.loads(raw_payload)
        except json.JSONDecodeError:
            decoded = {}
        pages = decoded.get("pages", []) if isinstance(decoded, dict) else []
    return {
        "id": record.template_id,
        "name": str(record.name or ""),
        "display_name": str(record.display_name or record.name or record.template_id),
        "status": str(record.status or "draft"),
        "source_job_id": str(record.source_job_id or ""),
        "created_at": _to_timestamp(record.created_at),
        "updated_at": _to_timestamp(record.updated_at),
        "pages": pages if isinstance(pages, list) else [],
    }


def _record_to_template(record: job_store.DocumentTemplateRecord) -> dict[str, Any]:
    normalized = _normalize_template(_deserialize_template_payload(record))
    if normalized:
        return normalized
    return {
        "id": record.template_id,
        "name": str(record.name or ""),
        "display_name": str(record.display_name or record.name or record.template_id),
        "status": str(record.status or "draft"),
        "source_job_id": str(record.source_job_id or ""),
        "created_at": _to_timestamp(record.created_at),
        "updated_at": _to_timestamp(record.updated_at),
        "pages": [],
    }


def _load_legacy_templates() -> list[dict[str, Any]]:
    path = state.DOCUMENT_TEMPLATES_PATH
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return []
    if not isinstance(data, list):
        return []
    cleaned: list[dict[str, Any]] = []
    for item in data:
        normalized = _normalize_template(item)
        if normalized:
            cleaned.append(normalized)
    cleaned.sort(key=lambda item: (item["updated_at"], item["created_at"]), reverse=True)
    return cleaned


def _seed_from_legacy_if_needed() -> None:
    try:
        existing_count = job_store.count_document_templates()
    except Exception:
        return
    if existing_count > 0:
        return
    legacy_templates = _load_legacy_templates()
    if not legacy_templates:
        return
    for template in legacy_templates:
        _upsert_template(template)


def _upsert_template(normalized: dict[str, Any]) -> dict[str, Any]:
    with job_store.session_scope() as session:
        record = session.get(job_store.DocumentTemplateRecord, normalized["id"])
        if record is None and normalized.get("source_job_id"):
            record = session.scalar(
                select(job_store.DocumentTemplateRecord).where(
                    job_store.DocumentTemplateRecord.source_job_id == normalized["source_job_id"]
                )
            )
        created_at = _to_datetime(float(normalized.get("created_at") or time.time()))
        updated_at = _to_datetime(float(normalized.get("updated_at") or time.time()))
        payload_json = json.dumps({"pages": normalized.get("pages", [])}, ensure_ascii=False)
        if record is None:
            record = job_store.DocumentTemplateRecord(
                template_id=normalized["id"],
                name="",
                display_name="",
                source_job_id=None,
                status=str(normalized.get("status") or "draft"),
                payload_json=payload_json,
                created_at=created_at,
                updated_at=updated_at,
            )
            session.add(record)
        else:
            record.updated_at = updated_at
            record.payload_json = payload_json
        record.name = str(normalized.get("name") or "")
        record.display_name = str(normalized.get("display_name") or record.name or record.template_id)
        record.source_job_id = str(normalized.get("source_job_id") or "") or None
        record.status = str(normalized.get("status") or "draft")
        record.created_at = created_at
        session.flush()
        return _record_to_template(record)


def load_document_templates() -> list[dict[str, Any]]:
    _seed_from_legacy_if_needed()
    with job_store.session_scope() as session:
        records = list(
            session.scalars(
                select(job_store.DocumentTemplateRecord).order_by(
                    job_store.DocumentTemplateRecord.updated_at.desc(),
                    job_store.DocumentTemplateRecord.created_at.desc(),
                )
            ).all()
        )
        return [_record_to_template(record) for record in records]


def get_document_template(template_id: str) -> dict[str, Any] | None:
    cleaned_id = str(template_id or "").strip()
    if not cleaned_id:
        return None
    _seed_from_legacy_if_needed()
    with job_store.session_scope() as session:
        record = session.get(job_store.DocumentTemplateRecord, cleaned_id)
        if record is None:
            return None
        return _record_to_template(record)


def get_document_template_by_job(job_id: str) -> dict[str, Any] | None:
    cleaned_job_id = str(job_id or "").strip()
    if not cleaned_job_id:
        return None
    _seed_from_legacy_if_needed()
    with job_store.session_scope() as session:
        record = session.scalar(
            select(job_store.DocumentTemplateRecord).where(
                job_store.DocumentTemplateRecord.source_job_id == cleaned_job_id
            )
        )
        if record is None:
            return None
        return _record_to_template(record)


def create_template_draft(*, source_job_id: str, display_name: str) -> dict[str, Any]:
    existing = get_document_template_by_job(source_job_id)
    if existing:
        return existing
    now_ts = float(time.time())
    draft = {
        "id": uuid.uuid4().hex,
        "name": "",
        "display_name": str(display_name or source_job_id).strip() or source_job_id,
        "status": "draft",
        "source_job_id": str(source_job_id or "").strip(),
        "created_at": now_ts,
        "updated_at": now_ts,
        "pages": [],
    }
    return _upsert_template(draft)


def save_document_template(payload: dict[str, Any]) -> dict[str, Any]:
    template_id = str(payload.get("id") or "").strip()
    source_job_id = str(payload.get("source_job_id") or "").strip()
    existing = None
    if template_id:
        existing = get_document_template(template_id)
    if existing is None and source_job_id:
        existing = get_document_template_by_job(source_job_id)

    normalized = _normalize_template(
        {
            "id": template_id or (existing or {}).get("id"),
            "name": payload.get("name") or (existing or {}).get("name") or "",
            "display_name": payload.get("display_name")
            or (existing or {}).get("display_name")
            or payload.get("name")
            or "",
            "status": "saved",
            "source_job_id": source_job_id or (existing or {}).get("source_job_id") or "",
            "created_at": (existing or {}).get("created_at"),
            "updated_at": time.time(),
            "pages": payload.get("pages", []),
        }
    )
    if not normalized or not normalized["pages"]:
        raise ValueError("Invalid document template payload.")
    return _upsert_template(normalized)


def delete_document_template(template_id: str) -> bool:
    cleaned_id = str(template_id or "").strip()
    if not cleaned_id:
        return False
    with job_store.session_scope() as session:
        record = session.get(job_store.DocumentTemplateRecord, cleaned_id)
        if record is None:
            return False
        session.delete(record)
        return True
