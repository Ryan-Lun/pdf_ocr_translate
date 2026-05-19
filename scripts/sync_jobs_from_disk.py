from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services import job_store, jobs, state


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _timestamp(path: Path) -> float:
    try:
        return float(path.stat().st_mtime)
    except FileNotFoundError:
        return 0.0


def _collect_relevant_paths(job_dir: Path, job_type: str, meta: dict[str, Any]) -> list[Path]:
    paths = [job_dir, jobs.job_meta_path(job_dir)]
    if job_type in {"ocr_overlay", "template_source"}:
        paths.extend(
            [
                job_dir / f"{job_dir.name}.pdf",
                job_dir / "source.pdf",
                job_dir / "overlay_debug.pdf",
                job_dir / "edited.pdf",
                jobs.batch_config_path(job_dir),
                jobs.batch_status_path(job_dir),
            ]
        )
    elif job_type == "doc_workspace":
        paths.extend(
            [
                job_dir / "source.pdf",
                job_dir / "structure" / "doc.md",
                job_dir / "structure" / "doc.html",
                job_dir / "translated" / "doc.translated.html",
                job_dir / "output" / "output.docx",
                job_dir / state.DOC_STATUS_NAME,
            ]
        )
    elif job_type == "word_translate":
        source_name = str(meta.get("source_filename") or "").strip()
        if source_name:
            paths.append(job_dir / source_name)
        paths.append(job_dir / "output" / "output.docx")
    return paths


def _infer_timestamps(job_dir: Path, job_type: str, meta: dict[str, Any], status: str) -> tuple[Any, Any, Any]:
    paths = _collect_relevant_paths(job_dir, job_type, meta)
    existing_ts = [_timestamp(path) for path in paths if path.exists()]
    fallback_created = existing_ts[0] if existing_ts else 0.0
    created_ts = 0.0

    if job_type in {"ocr_overlay", "template_source"}:
        created_ts = _timestamp(job_dir / f"{job_dir.name}.pdf") or _timestamp(job_dir / "source.pdf")
    elif job_type == "doc_workspace":
        created_ts = _timestamp(job_dir / "source.pdf")
    elif job_type == "word_translate":
        source_name = str(meta.get("source_filename") or "").strip()
        if source_name:
            created_ts = _timestamp(job_dir / source_name)

    if not created_ts:
        created_ts = fallback_created or _timestamp(job_dir)

    updated_ts = max(existing_ts) if existing_ts else created_ts
    completed_ts = _safe_float(meta.get("processing_completed_at"), 0.0)
    if not completed_ts and status in {"completed", "failed", "cancelled"}:
        completed_ts = updated_ts

    return (
        jobs.datetime_from_timestamp(created_ts),
        jobs.datetime_from_timestamp(updated_ts),
        jobs.datetime_from_timestamp(completed_ts),
    )


def _build_payload(job_dir: Path, job_type: str, meta: dict[str, Any]) -> dict[str, Any] | None:
    if job_type in {"ocr_overlay", "template_source"}:
        batch_config = jobs.load_batch_config(job_dir) or {}
        payload = {
            "dpi": int(meta.get("dpi") or 200),
            "start_page": int(meta.get("start_page") or 1),
            "end_page": meta.get("end_page"),
            "translate_source_lang": str(
                batch_config.get("source_lang") or meta.get("source_lang") or "auto"
            ),
            "translate_target_lang": str(
                batch_config.get("target_lang") or meta.get("target_lang") or "en"
            ),
            "translate_model": str(batch_config.get("model") or meta.get("translate_model") or ""),
            "translate_mode": jobs.normalize_translate_mode(
                batch_config.get("translate_mode") or meta.get("translate_mode")
            ),
            "keep_lang": str(meta.get("keep_lang") or "all"),
            "enable_translate": bool(batch_config),
            "document_mode": jobs.normalize_document_mode(
                batch_config.get("document_mode") or meta.get("document_mode")
            ),
        }
        if payload["translate_model"]:
            return payload
        payload.pop("translate_model")
        return payload

    if job_type == "doc_workspace":
        return {
            "source_lang": str(meta.get("source_lang") or "auto"),
            "target_lang": str(meta.get("target_lang") or "en"),
        }

    if job_type == "word_translate":
        retain_terms = meta.get("retain_terms")
        if not isinstance(retain_terms, list):
            retain_terms = []
        return {
            "source_lang": str(meta.get("source_lang") or "auto"),
            "target_lang": str(meta.get("target_lang") or "en"),
            "retain_terms": [str(item) for item in retain_terms if str(item).strip()],
        }

    return None


def _upsert_job(job_dir: Path) -> str:
    meta = jobs.load_job_meta(job_dir) or {}
    job_id = job_dir.name
    job_type = str(meta.get("job_type") or jobs.get_job_type(job_dir))
    status, stage = jobs.infer_job_store_status(job_dir, meta)
    batch_config = jobs.load_batch_config(job_dir) or {}
    batch_status = jobs.load_batch_status(job_dir) or {}
    progress = _safe_float(meta.get("progress"), 100.0 if status == "completed" else 0.0)
    created_at, updated_at, completed_at = _infer_timestamps(job_dir, job_type, meta, status)
    started_at = jobs.datetime_from_timestamp(
        _safe_float(meta.get("processing_started_at"), 0.0)
    )
    error_message = str(meta.get("error") or batch_status.get("error") or "").strip() or None
    target_lang = str(batch_config.get("target_lang") or meta.get("target_lang") or "").strip() or None
    document_mode = (
        jobs.normalize_document_mode(batch_config.get("document_mode") or meta.get("document_mode"))
        if job_type in {"ocr_overlay", "template_source"}
        else None
    )
    payload = _build_payload(job_dir, job_type, meta)

    existing = job_store.get_job(job_id)
    if existing is None:
        job_store.create_job(
            job_id=job_id,
            job_type=job_type,
            stage=stage,
            status=status,
            progress=progress,
            job_name=jobs.normalize_job_name(meta.get("job_name")),
            target_lang=target_lang,
            document_mode=document_mode,
            payload=payload,
            started_at=started_at,
            completed_at=completed_at,
        )
        action = "created"
    else:
        action = "updated"

    job_store.update_job(
        job_id,
        job_type=job_type,
        status=status,
        stage=stage,
        progress=progress,
        job_name=jobs.normalize_job_name(meta.get("job_name")),
        target_lang=target_lang,
        document_mode=document_mode,
        payload_json=json.dumps(payload, ensure_ascii=False) if payload is not None else None,
        error_message=error_message,
        started_at=started_at,
        completed_at=completed_at,
        created_at=created_at,
        updated_at=updated_at,
    )
    return action


def main() -> int:
    if not state.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is empty.")
    job_store.init_app(SimpleNamespace(config={"DATABASE_URL": state.DATABASE_URL}))

    actions = {"created": 0, "updated": 0}
    scanned = 0
    for root in (state.JOB_ROOT, state.TEMPLATE_JOB_ROOT):
        if not root.exists():
            continue
        for job_dir in sorted(root.iterdir()):
            if not job_dir.is_dir() or not jobs.safe_job_id(job_dir.name):
                continue
            scanned += 1
            action = _upsert_job(job_dir)
            actions[action] += 1

    print(
        f"Scanned {scanned} job directories. "
        f"Created {actions['created']} records, updated {actions['updated']} records."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
