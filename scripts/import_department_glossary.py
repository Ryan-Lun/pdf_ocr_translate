from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services import glossary, job_store, state


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


def _print_summary(summary: glossary.DepartmentGlossaryImportSummary) -> None:
    print(
        "department_glossary_import "
        f"dry_run={'1' if summary.dry_run else '0'} "
        f"library_id={summary.library_id or ''} "
        f"scanned={summary.scanned} "
        f"created={summary.created} "
        f"updated={summary.updated} "
        f"unchanged={summary.unchanged} "
        f"would_create={summary.would_create} "
        f"would_update={summary.would_update} "
        f"invalid={summary.invalid} "
        f"duplicates={summary.duplicates}"
    )
    for detail in summary.details:
        payload = {
            "row": detail.row_number,
            "action": detail.action,
            "reason": detail.reason,
        }
        if detail.source_term:
            payload["source_term"] = detail.source_term
        if detail.target_term:
            payload["target_term"] = detail.target_term
        if detail.entry_id is not None:
            payload["entry_id"] = detail.entry_id
        print(
            "department_glossary_import_detail "
            + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Import JSON glossary entries into the default Department Glossary."
    )
    parser.add_argument("json_path", type=Path)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write valid entries to SQL. Defaults to dry-run.",
    )
    parser.add_argument("--source-lang", default="zh")
    parser.add_argument("--target-lang", default="en")
    parser.add_argument("--work-id", default=None)
    args = parser.parse_args(argv)

    try:
        _init_database()
        summary = glossary.import_department_glossary_json(
            args.json_path,
            apply=args.apply,
            source_lang=args.source_lang,
            target_lang=args.target_lang,
            created_by_work_id=args.work_id,
            updated_by_work_id=args.work_id,
        )
    except (OSError, json.JSONDecodeError, RuntimeError, ValueError) as exc:
        print(f"department_glossary_import_error error={exc}", file=sys.stderr)
        return 1
    _print_summary(summary)
    return 1 if summary.invalid or summary.duplicates else 0


if __name__ == "__main__":
    raise SystemExit(main())
