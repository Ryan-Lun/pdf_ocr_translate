from __future__ import annotations

import argparse
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services import job_store, state, word_batch_runner, word_layout


def _init_database() -> None:
    if not state.DATABASE_URL:
        raise RuntimeError("DATABASE_URL is empty.")
    job_store.init_app(
        SimpleNamespace(
            config={
                "DATABASE_URL": state.DATABASE_URL,
                "DATABASE_SCHEMA": state.DATABASE_SCHEMA,
                "AUTO_SCHEMA_MANAGEMENT": True,
            }
        )
    )


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid positive integer value: {value}") from exc
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"invalid positive integer value: {value}")
    return parsed


def _parse_bool(value: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean value: {value}")


def _positive_float(value: str) -> float:
    try:
        parsed = float(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid positive number value: {value}") from exc
    if parsed <= 0:
        raise argparse.ArgumentTypeError(f"invalid positive number value: {value}")
    return parsed


def _header_footer_term(value: str) -> tuple[str, str]:
    if "=" not in value:
        raise argparse.ArgumentTypeError("header/footer term must use SOURCE=TARGET format")
    source, target = value.split("=", 1)
    source = source.strip()
    target = target.strip()
    if not source or not target:
        raise argparse.ArgumentTypeError("header/footer term source and target cannot be empty")
    return source, target


def main(
    argv: list[str] | None = None,
    *,
    init_database: bool = True,
    smoke_tester: word_batch_runner.WordBatchSmokeTester | None = None,
    executor: word_batch_runner.WordBatchExecutor | None = None,
) -> int:
    parser = argparse.ArgumentParser(
        description="Execute a one-time local-model Word batch translation run."
    )
    parser.add_argument("input_dir", type=Path)
    parser.add_argument("output_dir", type=Path)
    parser.add_argument("--report-dir", type=Path, default=None)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--glossary-library-id", required=True)
    parser.add_argument("--translate-tables", type=_parse_bool, default=True)
    parser.add_argument("--stage-2-enabled", type=_parse_bool, default=True)
    parser.add_argument(
        "--header-footer-exclude-pattern",
        action="append",
        default=[],
        help="Regex pattern for header/footer text to skip. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--header-footer-font-size",
        type=_positive_float,
        default=None,
        help="Font size in points for translated header/footer text only.",
    )
    parser.add_argument(
        "--header-footer-term",
        type=_header_footer_term,
        action="append",
        default=[],
        help="Fixed header/footer field translation in SOURCE=TARGET format. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--exclude-table-index",
        type=_positive_int,
        action="append",
        default=[],
        help="1-based body table index to skip. Can be supplied multiple times.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Regenerate files even when the target output already exists.",
    )
    parser.add_argument(
        "--file-concurrency",
        type=_positive_int,
        default=word_batch_runner.DEFAULT_FILE_CONCURRENCY,
        help="Number of Word files to process at once. Default: 1.",
    )
    parser.add_argument(
        "--word-request-concurrency",
        type=_positive_int,
        default=word_batch_runner.DEFAULT_WORD_REQUEST_CONCURRENCY,
        help="Word translation request concurrency for this run. Default: 1.",
    )
    parser.add_argument(
        "--word-requests-per-minute",
        type=_positive_int,
        default=word_batch_runner.DEFAULT_WORD_REQUESTS_PER_MINUTE,
        help="Word translation request pacing for this run. Default: 60.",
    )
    parser.add_argument(
        "--disable-stage-2",
        action="store_true",
        help="Disable Stage 2 post-edit smoke testing and later post-edit work.",
    )
    args = parser.parse_args(argv)

    try:
        if init_database:
            _init_database()
        summary = word_batch_runner.run_word_batch(
            input_dir=args.input_dir,
            output_dir=args.output_dir,
            report_dir=args.report_dir,
            source_lang=word_batch_runner.WORD_BATCH_SOURCE_LANG,
            target_lang=word_batch_runner.WORD_BATCH_TARGET_LANG,
            model=args.model,
            local_model_base_url=args.base_url,
            local_model_api_key=args.api_key,
            glossary_library_id=args.glossary_library_id,
            layout_mode=word_batch_runner.WORD_BATCH_LAYOUT_MODE,
            translate_tables=args.translate_tables,
            stage_2_enabled=False if args.disable_stage_2 else args.stage_2_enabled,
            header_footer_exclude_patterns=tuple(args.header_footer_exclude_pattern or ()),
            header_footer_font_size_pt=args.header_footer_font_size,
            excluded_table_indices=tuple(args.exclude_table_index or ()),
            header_footer_fixed_terms=tuple(args.header_footer_term or ()),
            overwrite_existing=args.overwrite,
            file_concurrency=args.file_concurrency,
            word_request_concurrency=args.word_request_concurrency,
            word_requests_per_minute=args.word_requests_per_minute,
            smoke_tester=smoke_tester,
            executor=executor,
        )
    except Exception as exc:
        print(f"word_batch_error error={exc}", file=sys.stderr)
        return 1

    print(
        "word_batch "
        f"scanned={summary.scanned} "
        f"planned={summary.planned} "
        f"skipped={summary.skipped} "
        f"failed={summary.failed} "
        f"glossary_library_id={summary.glossary.library_id} "
        f"glossary_code={summary.glossary.code} "
        f"glossary_name={summary.glossary.name} "
        f"glossary_department_code={summary.glossary.department_code} "
        f"glossary_is_active={'1' if summary.glossary.is_active else '0'} "
        f"glossary_entry_count={summary.glossary.entry_count} "
        f"smoke_stage_1={'1' if summary.smoke_test.stage_1_checked else '0'} "
        f"smoke_stage_2={'1' if summary.smoke_test.stage_2_checked else '0'} "
        f"report_json={summary.report_json_path} "
        f"report_csv={summary.report_csv_path}"
    )
    return 1 if summary.failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
