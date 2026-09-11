from __future__ import annotations

import csv
import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Protocol
from uuid import uuid4

from openai import OpenAI

from . import glossary, jobs, word_layout, word_translate


DEFAULT_WORD_BATCH_REPORT_JSON = "word_batch_report.json"
DEFAULT_WORD_BATCH_REPORT_CSV = "word_batch_report.csv"
WORD_BATCH_SOURCE_LANG = "auto"
WORD_BATCH_TARGET_LANG = "en"
WORD_BATCH_LAYOUT_MODE = word_layout.BILINGUAL_BELOW
LOCAL_MODEL_DISABLE_THINKING_EXTRA_BODY = {"chat_template_kwargs": {"enable_thinking": False}}
DEFAULT_FILE_CONCURRENCY = 1
DEFAULT_WORD_REQUEST_CONCURRENCY = 1
DEFAULT_WORD_REQUESTS_PER_MINUTE = 60


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _target_suffix(target_lang: str) -> str:
    suffix = "".join(ch.lower() if ch.isalnum() else "_" for ch in target_lang.strip())
    suffix = "_".join(part for part in suffix.split("_") if part)
    return suffix or "target"


def discover_doc_files(input_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in input_dir.rglob("*")
        if path.is_file() and path.suffix.lower() in {".doc", ".docx"}
    )


def output_path_for_doc(
    source_path: Path,
    *,
    input_dir: Path,
    output_dir: Path,
    target_lang: str,
) -> Path:
    relative_path = source_path.relative_to(input_dir)
    filename = f"{source_path.stem}_{_target_suffix(target_lang)}.docx"
    return output_dir / relative_path.with_name(filename)


@dataclass(frozen=True)
class WordBatchGlossaryMetadata:
    library_id: int
    code: str
    name: str
    department_code: str
    is_active: bool
    entry_count: int


GlossaryResolver = Callable[..., glossary.SelectedDepartmentGlossary]


@dataclass(frozen=True)
class LocalModelConfig:
    base_url: str
    api_key: str
    model: str


@dataclass(frozen=True)
class WordBatchSmokeResult:
    ok: bool
    stage_1_checked: bool = False
    stage_2_checked: bool = False
    error: str = ""


class WordBatchSmokeTester(Protocol):
    def __call__(
        self,
        config: LocalModelConfig,
        *,
        stage_2_enabled: bool,
    ) -> WordBatchSmokeResult:
        ...


@dataclass(frozen=True)
class WordBatchItem:
    input_path: Path
    output_path: Path
    source_lang: str
    target_lang: str
    model: str
    local_model_base_url: str
    local_model_api_key: str
    glossary_library_id: str
    glossary_code: str
    glossary_name: str
    glossary_department_code: str
    glossary_is_active: bool
    glossary_entry_count: int
    layout_mode: str
    translate_tables: bool
    stage_2_enabled: bool
    header_footer_exclude_patterns: tuple[str, ...]
    header_footer_font_size_pt: float | None
    excluded_table_indices: tuple[int, ...]
    header_footer_fixed_terms: tuple[tuple[str, str], ...]
    word_request_concurrency: int
    word_requests_per_minute: int


@dataclass(frozen=True)
class WordBatchExecutionResult:
    status: str
    job_id: str = ""
    error: str = ""
    started_at: str = ""
    finished_at: str = ""


class WordBatchExecutor(Protocol):
    def __call__(self, item: WordBatchItem) -> WordBatchExecutionResult:
        ...


class OpenAICompatibleSmokeTester:
    def __call__(
        self,
        config: LocalModelConfig,
        *,
        stage_2_enabled: bool,
    ) -> WordBatchSmokeResult:
        try:
            client = OpenAI(
                api_key=config.api_key,
                base_url=_normalize_local_model_base_url(config.base_url),
            )
            _smoke_chat_completion(
                client,
                model=config.model,
                messages=[
                    {"role": "system", "content": "You are a translator."},
                    {"role": "user", "content": "Translate this to English: 測試"},
                ],
            )
        except Exception as exc:
            return WordBatchSmokeResult(
                ok=False,
                stage_1_checked=True,
                stage_2_checked=False,
                error=str(exc),
            )

        if not stage_2_enabled:
            return WordBatchSmokeResult(ok=True, stage_1_checked=True, stage_2_checked=False)

        try:
            _smoke_chat_completion(
                client,
                model=config.model,
                messages=[
                    {"role": "system", "content": "You are a translation editor."},
                    {
                        "role": "user",
                        "content": "Revise this English translation only if needed: Test.",
                    },
                ],
            )
        except Exception as exc:
            return WordBatchSmokeResult(
                ok=False,
                stage_1_checked=True,
                stage_2_checked=True,
                error=str(exc),
            )
        return WordBatchSmokeResult(ok=True, stage_1_checked=True, stage_2_checked=True)


class PlanningWordBatchExecutor:
    def __call__(self, item: WordBatchItem) -> WordBatchExecutionResult:
        del item
        now = _utc_now_iso()
        return WordBatchExecutionResult(
            status="planned",
            job_id=uuid4().hex,
            started_at=now,
            finished_at=now,
        )


class SynchronousWordPipelineExecutor:
    def __call__(self, item: WordBatchItem) -> WordBatchExecutionResult:
        started_at = _utc_now_iso()
        job_id = word_translate.enqueue_word_job_from_upload(
            item.input_path,
            item.input_path.stem,
            "auto",
            "en",
            retain_terms_raw="",
            system_prompt="",
            layout_mode=word_layout.BILINGUAL_BELOW,
            translate_tables=item.translate_tables,
            department_glossary_context=_department_glossary_context_from_item(item),
        )
        job_dir = jobs.job_dir(job_id, job_root=jobs.job_root_for_type("word_translate"))
        source_name = str((jobs.load_job_meta(job_dir) or {}).get("source_filename") or item.input_path.name)
        source_path = job_dir / source_name
        processing_source_path = (
            source_path
            if source_path.suffix.lower() == ".docx"
            else job_dir / f"{source_path.stem}.converted.docx"
        )
        pipeline_output_path = job_dir / "output" / "output.docx"
        word_translate.run_word_translate_job(
            job_id=job_id,
            job_dir=job_dir,
            source_path=source_path,
            processing_source_path=processing_source_path,
            output_path=pipeline_output_path,
            source_lang="auto",
            target_lang="en",
            retain_terms=[],
            system_prompt="",
            layout_mode=word_layout.BILINGUAL_BELOW,
            translate_tables=item.translate_tables,
            header_footer_layout_mode=word_layout.BILINGUAL_BELOW,
            header_footer_exclude_patterns=item.header_footer_exclude_patterns,
            header_footer_font_size_pt=item.header_footer_font_size_pt,
            excluded_table_indices=item.excluded_table_indices,
            header_footer_fixed_terms=item.header_footer_fixed_terms,
            translation_model=item.model,
            local_model_base_url=item.local_model_base_url,
            local_model_api_key=item.local_model_api_key,
            stage_2_enabled=item.stage_2_enabled,
            request_concurrency_limit=item.word_request_concurrency,
            requests_per_minute=item.word_requests_per_minute,
            request_extra_body=LOCAL_MODEL_DISABLE_THINKING_EXTRA_BODY,
        )
        record = jobs.job_store.get_job(job_id)
        status = str(getattr(record, "status", "") or "failed")
        if status != "completed" or not pipeline_output_path.exists():
            error = str(getattr(record, "error_message", "") or "Word pipeline did not produce output.docx")
            return WordBatchExecutionResult(
                status=status if status in {"failed", "cancelled"} else "failed",
                job_id=job_id,
                error=error,
                started_at=started_at,
                finished_at=_utc_now_iso(),
            )
        item.output_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(pipeline_output_path, item.output_path)
        return WordBatchExecutionResult(
            status="completed",
            job_id=job_id,
            started_at=started_at,
            finished_at=_utc_now_iso(),
        )


@dataclass(frozen=True)
class WordBatchReportRow:
    input_path: str
    output_path: str
    status: str
    job_id: str
    error: str
    model: str
    glossary_library_id: str
    glossary_code: str
    glossary_name: str
    glossary_department_code: str
    glossary_is_active: bool
    glossary_entry_count: int
    layout_mode: str
    translate_tables: bool
    stage_2_enabled: bool
    word_request_concurrency: int
    word_requests_per_minute: int
    started_at: str
    finished_at: str


@dataclass(frozen=True)
class WordBatchRunSummary:
    scanned: int
    planned: int
    skipped: int
    failed: int
    report_json_path: Path
    report_csv_path: Path
    rows: list[WordBatchReportRow]
    glossary: WordBatchGlossaryMetadata
    smoke_test: WordBatchSmokeResult


def run_word_batch(
    *,
    input_dir: Path,
    output_dir: Path,
    report_dir: Path | None = None,
    source_lang: str = WORD_BATCH_SOURCE_LANG,
    target_lang: str = WORD_BATCH_TARGET_LANG,
    model: str = "",
    local_model_base_url: str = "",
    local_model_api_key: str = "",
    glossary_library_id: str | int | None = "",
    layout_mode: str = WORD_BATCH_LAYOUT_MODE,
    translate_tables: bool = True,
    stage_2_enabled: bool = True,
    header_footer_exclude_patterns: tuple[str, ...] | list[str] | None = None,
    header_footer_font_size_pt: float | None = None,
    excluded_table_indices: tuple[int, ...] | list[int] | None = None,
    header_footer_fixed_terms: tuple[tuple[str, str], ...] | list[tuple[str, str]] | None = None,
    overwrite_existing: bool = False,
    file_concurrency: int = DEFAULT_FILE_CONCURRENCY,
    word_request_concurrency: int = DEFAULT_WORD_REQUEST_CONCURRENCY,
    word_requests_per_minute: int = DEFAULT_WORD_REQUESTS_PER_MINUTE,
    executor: WordBatchExecutor | None = None,
    glossary_resolver: GlossaryResolver | None = None,
    smoke_tester: WordBatchSmokeTester | None = None,
) -> WordBatchRunSummary:
    del source_lang, target_lang, layout_mode
    execution_source_lang = WORD_BATCH_SOURCE_LANG
    execution_target_lang = WORD_BATCH_TARGET_LANG
    execution_layout_mode = WORD_BATCH_LAYOUT_MODE
    glossary_metadata = resolve_word_batch_glossary(
        glossary_library_id,
        source_lang=execution_source_lang,
        target_lang=execution_target_lang,
        resolver=glossary_resolver,
    )
    input_dir = input_dir.resolve()
    if not input_dir.is_dir():
        raise NotADirectoryError(f"input directory does not exist: {input_dir}")
    output_dir = output_dir.resolve()
    report_dir = (report_dir or output_dir).resolve()
    local_model_config = resolve_local_model_config(
        base_url=local_model_base_url,
        api_key=local_model_api_key,
        model=model,
    )
    smoke_result = run_local_model_smoke_test(
        local_model_config,
        stage_2_enabled=stage_2_enabled,
        smoke_tester=smoke_tester,
    )
    file_concurrency = _require_positive_int(file_concurrency, "file_concurrency")
    word_request_concurrency = _require_positive_int(
        word_request_concurrency,
        "word_request_concurrency",
    )
    word_requests_per_minute = _require_positive_int(
        word_requests_per_minute,
        "word_requests_per_minute",
    )
    header_footer_exclude_patterns = tuple(str(pattern) for pattern in (header_footer_exclude_patterns or ()))
    excluded_table_indices = tuple(_require_positive_int(index, "excluded_table_indices") for index in (excluded_table_indices or ()))
    header_footer_fixed_terms = _normalize_header_footer_fixed_terms(header_footer_fixed_terms)
    executor = executor or SynchronousWordPipelineExecutor()
    source_paths = discover_doc_files(input_dir)
    rows: list[WordBatchReportRow | None] = []
    items_by_index: dict[int, WordBatchItem] = {}

    for index, source_path in enumerate(source_paths):
        output_path = output_path_for_doc(
            source_path,
            input_dir=input_dir,
            output_dir=output_dir,
            target_lang=execution_target_lang,
        )
        item = WordBatchItem(
            input_path=source_path,
            output_path=output_path,
            source_lang=execution_source_lang,
            target_lang=execution_target_lang,
            model=local_model_config.model,
            local_model_base_url=local_model_config.base_url,
            local_model_api_key=local_model_config.api_key,
            glossary_library_id=str(glossary_metadata.library_id),
            glossary_code=glossary_metadata.code,
            glossary_name=glossary_metadata.name,
            glossary_department_code=glossary_metadata.department_code,
            glossary_is_active=glossary_metadata.is_active,
            glossary_entry_count=glossary_metadata.entry_count,
            layout_mode=execution_layout_mode,
            translate_tables=bool(translate_tables),
            stage_2_enabled=bool(stage_2_enabled),
            header_footer_exclude_patterns=header_footer_exclude_patterns,
            header_footer_font_size_pt=header_footer_font_size_pt,
            excluded_table_indices=excluded_table_indices,
            header_footer_fixed_terms=header_footer_fixed_terms,
            word_request_concurrency=word_request_concurrency,
            word_requests_per_minute=word_requests_per_minute,
        )
        if output_path.exists() and not overwrite_existing:
            rows.append(
                _report_row(
                    item,
                    WordBatchExecutionResult(
                        status="skipped_existing",
                        started_at="",
                        finished_at=_utc_now_iso(),
                    ),
                )
            )
            continue
        rows.append(None)
        items_by_index[index] = item

    if file_concurrency == 1:
        for index, item in items_by_index.items():
            rows[index] = _execute_report_row(item, executor)
    else:
        with ThreadPoolExecutor(max_workers=file_concurrency) as pool:
            future_by_index = {
                pool.submit(_execute_report_row, item, executor): index
                for index, item in items_by_index.items()
            }
            for future in as_completed(future_by_index):
                rows[future_by_index[future]] = future.result()

    report_rows = [row for row in rows if row is not None]
    report_json_path = report_dir / DEFAULT_WORD_BATCH_REPORT_JSON
    report_csv_path = report_dir / DEFAULT_WORD_BATCH_REPORT_CSV
    write_word_batch_reports(
        report_rows,
        glossary_metadata=glossary_metadata,
        smoke_result=smoke_result,
        json_path=report_json_path,
        csv_path=report_csv_path,
    )
    return WordBatchRunSummary(
        scanned=len(report_rows),
        planned=sum(1 for row in report_rows if row.status == "planned"),
        skipped=sum(1 for row in report_rows if row.status.startswith("skipped")),
        failed=sum(1 for row in report_rows if row.status == "failed"),
        report_json_path=report_json_path,
        report_csv_path=report_csv_path,
        rows=report_rows,
        glossary=glossary_metadata,
        smoke_test=smoke_result,
    )


def _normalize_header_footer_fixed_terms(
    terms: tuple[tuple[str, str], ...] | list[tuple[str, str]] | None,
) -> tuple[tuple[str, str], ...]:
    normalized: list[tuple[str, str]] = []
    for source, target in terms or ():
        source_text = str(source or "").strip()
        target_text = str(target or "").strip()
        if source_text and target_text:
            normalized.append((source_text, target_text))
    return tuple(normalized)


def _require_positive_int(value: int, name: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be a positive integer") from exc
    if parsed < 1:
        raise ValueError(f"{name} must be a positive integer")
    return parsed


def _execute_report_row(item: WordBatchItem, executor: WordBatchExecutor) -> WordBatchReportRow:
    try:
        result = executor(item)
    except Exception as exc:  # pragma: no cover
        result = WordBatchExecutionResult(
            status="failed",
            error=str(exc),
            finished_at=_utc_now_iso(),
        )
    return _report_row(item, result)


def _normalize_local_model_base_url(base_url: str) -> str:
    return str(base_url or "").strip().rstrip("/")


def _smoke_chat_completion(client: OpenAI, *, model: str, messages: list[dict[str, str]]) -> None:
    response = client.chat.completions.create(
        model=model,
        messages=messages,
        temperature=0,
        max_tokens=512,
        extra_body=LOCAL_MODEL_DISABLE_THINKING_EXTRA_BODY,
    )
    content = str(response.choices[0].message.content or "").strip()
    if not content:
        raise RuntimeError("local model smoke test returned an empty response")


def resolve_local_model_config(*, base_url: str, api_key: str, model: str) -> LocalModelConfig:
    cleaned_base_url = _normalize_local_model_base_url(base_url)
    cleaned_api_key = str(api_key or "").strip()
    cleaned_model = str(model or "").strip()
    missing = []
    if not cleaned_base_url:
        missing.append("base_url")
    if not cleaned_api_key:
        missing.append("api_key")
    if not cleaned_model:
        missing.append("model")
    if missing:
        raise RuntimeError(f"local model configuration is incomplete: {', '.join(missing)}")
    return LocalModelConfig(
        base_url=cleaned_base_url,
        api_key=cleaned_api_key,
        model=cleaned_model,
    )


def run_local_model_smoke_test(
    config: LocalModelConfig,
    *,
    stage_2_enabled: bool,
    smoke_tester: WordBatchSmokeTester | None = None,
) -> WordBatchSmokeResult:
    smoke_tester = smoke_tester or OpenAICompatibleSmokeTester()
    result = smoke_tester(config, stage_2_enabled=bool(stage_2_enabled))
    if not result.ok:
        raise RuntimeError(f"local model smoke test failed: {result.error}")
    return result


def resolve_word_batch_glossary(
    library_id: str | int | None,
    *,
    source_lang: str,
    target_lang: str,
    resolver: GlossaryResolver | None = None,
) -> WordBatchGlossaryMetadata:
    resolver = resolver or glossary.resolve_selected_department_glossary
    selected = resolver(
        library_id,
        source_lang=glossary.department_glossary_lookup_source_lang(source_lang),
        target_lang=target_lang,
        require_active=True,
        allow_default_fallback=False,
    )
    return WordBatchGlossaryMetadata(
        library_id=selected.library_id,
        code=selected.code,
        name=selected.name,
        department_code=selected.department_code,
        is_active=selected.is_active,
        entry_count=selected.entry_count,
    )


def _department_glossary_context_from_item(item: WordBatchItem) -> dict[str, object]:
    return {
        "source": "sql",
        "library_id": int(item.glossary_library_id),
        "library_code": item.glossary_code,
        "library_name": item.glossary_name,
        "department_code": item.glossary_department_code,
        "entry_count": item.glossary_entry_count,
    }


def _report_row(item: WordBatchItem, result: WordBatchExecutionResult) -> WordBatchReportRow:
    return WordBatchReportRow(
        input_path=str(item.input_path),
        output_path=str(item.output_path),
        status=result.status,
        job_id=result.job_id,
        error=result.error,
        model=item.model,
        glossary_library_id=item.glossary_library_id,
        glossary_code=item.glossary_code,
        glossary_name=item.glossary_name,
        glossary_department_code=item.glossary_department_code,
        glossary_is_active=item.glossary_is_active,
        glossary_entry_count=item.glossary_entry_count,
        layout_mode=item.layout_mode,
        translate_tables=item.translate_tables,
        stage_2_enabled=item.stage_2_enabled,
        word_request_concurrency=item.word_request_concurrency,
        word_requests_per_minute=item.word_requests_per_minute,
        started_at=result.started_at,
        finished_at=result.finished_at,
    )


def write_word_batch_reports(
    rows: list[WordBatchReportRow],
    *,
    glossary_metadata: WordBatchGlossaryMetadata,
    smoke_result: WordBatchSmokeResult,
    json_path: Path,
    csv_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    row_payload = [asdict(row) for row in rows]
    json_payload = {
        "preflight": {
            "glossary": asdict(glossary_metadata),
            "smoke_test": asdict(smoke_result),
        },
        "rows": row_payload,
    }
    json_path.write_text(
        json.dumps(json_payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[field.name for field in fields(WordBatchReportRow)],
        )
        writer.writeheader()
        writer.writerows(row_payload)
