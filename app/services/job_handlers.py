from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

from . import batch, doc_workspace, jobs, pipeline, realtime_translate, state, word_translate


class JobRecordView(Protocol):
    job_type: str
    status: str
    stage: str | None
    target_lang: str | None
    cancel_requested: bool


@dataclass(frozen=True)
class JobContext:
    job_id: str
    record: JobRecordView
    job_dir: Path
    payload: dict[str, Any]


class JobHandler(Protocol):
    job_type: str

    def handle(self, context: JobContext) -> None:
        ...


def start_cancel_monitor(job_id: str, cancel_event: threading.Event) -> threading.Thread:
    from . import job_store

    def _watch() -> None:
        while not cancel_event.is_set():
            record = job_store.get_job(job_id)
            if record is None or record.cancel_requested:
                cancel_event.set()
                return
            time.sleep(1)

    thread = threading.Thread(target=_watch, daemon=True)
    thread.start()
    return thread


class OcrOverlayJobHandler:
    job_type = "ocr_overlay"

    def handle(self, context: JobContext) -> None:
        payload = context.payload
        if bool(payload.get("resume_translate_only")) or str(context.record.stage or "").lower() == "translate":
            config = jobs.load_batch_config(context.job_dir) or {}
            translate_mode = jobs.normalize_translate_mode(
                config.get("translate_mode")
                or payload.get("translate_mode")
                or (jobs.load_job_meta(context.job_dir) or {}).get("translate_mode")
            )
            if translate_mode == "realtime":
                realtime_translate.run_realtime_translate_job(context.job_id, context.job_dir, config)
            else:
                batch.run_batch_translate_job(context.job_id, context.job_dir, config)
            return

        cancel_event = threading.Event()
        start_cancel_monitor(context.job_id, cancel_event)
        pipeline.run_ocr_pipeline_job(
            job_id=context.job_id,
            job_dir=context.job_dir,
            pdf_path=context.job_dir / f"{context.job_id}.pdf",
            dpi=int(payload.get("dpi") or 200),
            start_page=int(payload.get("start_page") or 1),
            end_page=payload.get("end_page"),
            page_numbers=list(payload.get("page_numbers") or []),
            translate_source_lang=str(payload.get("translate_source_lang") or "auto"),
            translate_target_lang=str(payload.get("translate_target_lang") or "en"),
            translate_model=str(payload.get("translate_model") or state.AZURE_BATCH_MODEL),
            translate_mode=str(payload.get("translate_mode") or "batch"),
            keep_lang=str(payload.get("keep_lang") or "all"),
            enable_translate=bool(payload.get("enable_translate")),
            document_mode=str(payload.get("document_mode") or "form"),
            cancel_event=cancel_event,
        )


class DocWorkspaceJobHandler:
    job_type = "doc_workspace"

    def handle(self, context: JobContext) -> None:
        payload = context.payload
        doc_workspace.run_doc_workspace_job(
            job_id=context.job_id,
            job_dir=context.job_dir,
            pdf_path=context.job_dir / "source.pdf",
            source_lang=str(payload.get("source_lang") or "auto"),
            target_lang=str(payload.get("target_lang") or context.record.target_lang or "en"),
            system_prompt=str(payload.get("system_prompt") or ""),
        )


class WordTranslateJobHandler:
    job_type = "word_translate"

    def handle(self, context: JobContext) -> None:
        payload = context.payload
        source_name = str((jobs.load_job_meta(context.job_dir) or {}).get("source_filename") or "source.docx")
        source_path = context.job_dir / source_name
        processing_source_path = (
            source_path
            if source_path.suffix.lower() == ".docx"
            else context.job_dir / f"{source_path.stem}.converted.docx"
        )
        word_translate.run_word_translate_job(
            job_id=context.job_id,
            job_dir=context.job_dir,
            source_path=source_path,
            processing_source_path=processing_source_path,
            output_path=context.job_dir / "output" / "output.docx",
            source_lang=str(payload.get("source_lang") or "auto"),
            target_lang=str(payload.get("target_lang") or context.record.target_lang or "en"),
            retain_terms=list(payload.get("retain_terms") or []),
            system_prompt=str(payload.get("system_prompt") or ""),
            layout_mode=word_translate.normalize_word_layout_mode(payload.get("layout_mode")),
        )


class JobHandlerRegistry:
    def __init__(self, handlers: list[JobHandler], aliases: dict[str, str] | None = None) -> None:
        self._handlers = {handler.job_type: handler for handler in handlers}
        for alias, target in (aliases or {}).items():
            if target in self._handlers:
                self._handlers[alias] = self._handlers[target]

    def resolve(self, job_type: str | None) -> JobHandler | None:
        return self._handlers.get(str(job_type or "").strip())


def default_job_handler_registry() -> JobHandlerRegistry:
    return JobHandlerRegistry(
        [
            OcrOverlayJobHandler(),
            DocWorkspaceJobHandler(),
            WordTranslateJobHandler(),
        ],
        aliases={"template_source": "ocr_overlay"},
    )
