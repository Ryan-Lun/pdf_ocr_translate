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


def _parse_bool(value: str) -> bool:
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean value: {value}")


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
