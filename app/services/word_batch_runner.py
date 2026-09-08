from __future__ import annotations

import csv
import json
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from . import word_layout


DEFAULT_WORD_BATCH_REPORT_JSON = "word_batch_report.json"
DEFAULT_WORD_BATCH_REPORT_CSV = "word_batch_report.csv"


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
        if path.is_file() and path.suffix.lower() == ".doc"
    )


def output_path_for_doc(
    source_path: Path,
    *,
    input_dir: Path,
    output_dir: Path,
    target_lang: str,
) -> Path:
    relative_path = source_path.relative_to(input_dir)
    filename = f"{source_path.stem}_bilingual_{_target_suffix(target_lang)}.docx"
    return output_dir / relative_path.with_name(filename)


@dataclass(frozen=True)
class WordBatchItem:
    input_path: Path
    output_path: Path
    source_lang: str
    target_lang: str
    model: str
    glossary_library_id: str
    layout_mode: str
    translate_tables: bool
    stage_2_enabled: bool


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


@dataclass(frozen=True)
class WordBatchReportRow:
    input_path: str
    output_path: str
    status: str
    job_id: str
    error: str
    model: str
    glossary_library_id: str
    layout_mode: str
    translate_tables: bool
    stage_2_enabled: bool
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


def run_word_batch(
    *,
    input_dir: Path,
    output_dir: Path,
    report_dir: Path | None = None,
    source_lang: str = "zh",
    target_lang: str = "en",
    model: str = "",
    glossary_library_id: str | int | None = "",
    layout_mode: str = word_layout.BILINGUAL_BELOW,
    translate_tables: bool = True,
    stage_2_enabled: bool = False,
    executor: WordBatchExecutor | None = None,
) -> WordBatchRunSummary:
    input_dir = input_dir.resolve()
    if not input_dir.is_dir():
        raise NotADirectoryError(f"input directory does not exist: {input_dir}")
    output_dir = output_dir.resolve()
    report_dir = (report_dir or output_dir).resolve()
    executor = executor or PlanningWordBatchExecutor()
    rows: list[WordBatchReportRow] = []

    for source_path in discover_doc_files(input_dir):
        output_path = output_path_for_doc(
            source_path,
            input_dir=input_dir,
            output_dir=output_dir,
            target_lang=target_lang,
        )
        item = WordBatchItem(
            input_path=source_path,
            output_path=output_path,
            source_lang=source_lang,
            target_lang=target_lang,
            model=model,
            glossary_library_id=str(glossary_library_id or ""),
            layout_mode=word_layout.normalize(layout_mode),
            translate_tables=bool(translate_tables),
            stage_2_enabled=bool(stage_2_enabled),
        )
        if output_path.exists():
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
        try:
            result = executor(item)
        except Exception as exc:  # pragma: no cover
            result = WordBatchExecutionResult(
                status="failed",
                error=str(exc),
                finished_at=_utc_now_iso(),
            )
        rows.append(_report_row(item, result))

    report_json_path = report_dir / DEFAULT_WORD_BATCH_REPORT_JSON
    report_csv_path = report_dir / DEFAULT_WORD_BATCH_REPORT_CSV
    write_word_batch_reports(rows, json_path=report_json_path, csv_path=report_csv_path)
    return WordBatchRunSummary(
        scanned=len(rows),
        planned=sum(1 for row in rows if row.status == "planned"),
        skipped=sum(1 for row in rows if row.status.startswith("skipped")),
        failed=sum(1 for row in rows if row.status == "failed"),
        report_json_path=report_json_path,
        report_csv_path=report_csv_path,
        rows=rows,
    )


def _report_row(item: WordBatchItem, result: WordBatchExecutionResult) -> WordBatchReportRow:
    return WordBatchReportRow(
        input_path=str(item.input_path),
        output_path=str(item.output_path),
        status=result.status,
        job_id=result.job_id,
        error=result.error,
        model=item.model,
        glossary_library_id=item.glossary_library_id,
        layout_mode=item.layout_mode,
        translate_tables=item.translate_tables,
        stage_2_enabled=item.stage_2_enabled,
        started_at=result.started_at,
        finished_at=result.finished_at,
    )


def write_word_batch_reports(
    rows: list[WordBatchReportRow],
    *,
    json_path: Path,
    csv_path: Path,
) -> None:
    json_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    payload = [asdict(row) for row in rows]
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    with csv_path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.DictWriter(
            csv_file,
            fieldnames=[field.name for field in fields(WordBatchReportRow)],
        )
        writer.writeheader()
        writer.writerows(payload)
