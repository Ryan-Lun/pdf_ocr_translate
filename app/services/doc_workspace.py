from __future__ import annotations

import json
import logging
import shutil
import time
import uuid
from pathlib import Path

from werkzeug.utils import secure_filename

from . import docx_export, jobs, markdown_translate, pp_structure, state

logger = logging.getLogger(__name__)


def doc_status_path(job_dir: Path) -> Path:
    return job_dir / state.DOC_STATUS_NAME


def write_doc_status(job_dir: Path, status: str, **meta: object) -> None:
    payload = {"status": status, "updated_at": time.time(), **meta}
    doc_status_path(job_dir).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    jobs.notify_jobs_update()


def load_doc_status(job_dir: Path) -> dict | None:
    path = doc_status_path(job_dir)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def run_doc_workspace_job(
    job_id: str,
    job_dir: Path,
    pdf_path: Path,
    target_lang: str,
) -> None:
    structure_dir = job_dir / "structure"
    translated_dir = job_dir / "translated"
    output_dir = job_dir / "output"
    try:
        jobs.update_job_meta(job_dir, doc_stage="structure_running")
        write_doc_status(job_dir, "structure_running", target_lang=target_lang)
        markdown_path, _ = pp_structure.extract_pdf_to_markdown(pdf_path, structure_dir)

        jobs.update_job_meta(job_dir, doc_stage="structure_completed")
        write_doc_status(job_dir, "structure_completed", markdown_path=str(markdown_path.name))

        jobs.update_job_meta(job_dir, doc_stage="html_running")
        write_doc_status(job_dir, "html_running")
        structure_html_path = structure_dir / "doc.html"
        docx_export.export_markdown_to_html(markdown_path, structure_html_path)

        jobs.update_job_meta(job_dir, doc_stage="translate_running", translate_started_at=time.time())
        write_doc_status(job_dir, "translate_running", target_lang=target_lang)
        translated_html_path = translated_dir / "doc.translated.html"
        source_images_dir = structure_dir / "images"
        translated_images_dir = translated_dir / "images"
        if source_images_dir.exists():
            shutil.copytree(source_images_dir, translated_images_dir, dirs_exist_ok=True)
        markdown_translate.translate_html_file(
            structure_html_path,
            translated_html_path,
            target_lang=target_lang,
        )

        jobs.update_job_meta(job_dir, doc_stage="translate_completed", translate_completed_at=time.time())
        write_doc_status(
            job_dir,
            "translate_completed",
            html_path=str(translated_html_path.name),
        )

        jobs.update_job_meta(job_dir, doc_stage="docx_running")
        write_doc_status(job_dir, "docx_running", html_path=str(translated_html_path.name))
        docx_path = output_dir / "output.docx"
        docx_export.export_html_to_docx(translated_html_path, docx_path)

        now_ts = time.time()
        jobs.update_job_meta(
            job_dir,
            doc_stage="completed",
            processing_completed_at=now_ts,
        )
        write_doc_status(
            job_dir,
            "completed",
            html_path=str(translated_html_path.name),
            docx_path=str(docx_path.name),
        )
    except Exception as exc:
        logger.exception("Document workspace failed job_id=%s error=%s", job_id, exc)
        jobs.update_job_meta(
            job_dir,
            doc_stage="failed",
            processing_completed_at=time.time(),
        )
        write_doc_status(job_dir, "failed", error=str(exc))


def enqueue_doc_job_from_upload(
    source_pdf: Path,
    display_name: str,
    target_lang: str,
) -> str:
    job_id = uuid.uuid4().hex
    job_dir = jobs.job_dir(job_id)
    job_dir.mkdir(parents=True, exist_ok=True)
    now_ts = time.time()
    jobs.write_job_meta(
        job_dir,
        {
            "job_name": display_name,
            "job_type": "doc_workspace",
            "processing_started_at": now_ts,
            "doc_stage": "uploaded",
            "target_lang": target_lang,
        },
    )
    jobs.job_store.create_job(
        job_id=job_id,
        job_type="doc_workspace",
        stage="uploaded",
        job_name=display_name,
        target_lang=target_lang,
        payload={"target_lang": target_lang},
    )

    pdf_path = job_dir / "source.pdf"
    if source_pdf.exists():
        shutil.copy2(source_pdf, pdf_path)
    else:
        raise FileNotFoundError(f"Missing PDF: {source_pdf}")

    write_doc_status(job_dir, "uploaded", target_lang=target_lang)
    jobs.notify_jobs_update()
    return job_id
