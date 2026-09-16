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


def _print_summary(summary: glossary.DepartmentGlossaryValidationReviewApplySummary) -> None:
    print(
        "department_glossary_validation_review_apply "
        f"dry_run={'1' if summary.dry_run else '0'} "
        f"library_id={summary.library_id} "
        f"scanned={summary.scanned} "
        f"would_update={summary.would_update} "
        f"updated={summary.updated} "
        f"skipped={summary.skipped} "
        f"invalid={summary.invalid} "
        f"unchanged={summary.unchanged}"
    )
    for detail in summary.details:
        payload = {
            "row": detail.row_number,
            "action": detail.action,
            "reason": detail.reason,
        }
        if detail.entry_id is not None:
            payload["entry_id"] = detail.entry_id
        if detail.reviewed_validation_type:
            payload["reviewed_validation_type"] = detail.reviewed_validation_type
        print(
            "department_glossary_validation_review_apply_detail "
            + json.dumps(payload, ensure_ascii=False, sort_keys=True)
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Apply a reviewed Department Glossary validation CSV."
    )
    parser.add_argument("csv_path", type=Path)
    parser.add_argument(
        "--library-id",
        type=int,
        required=True,
        help="Selected Department Glossary library id to update.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Write reviewed validation types to SQL. Defaults to dry-run.",
    )
    parser.add_argument("--work-id", default=None)
    args = parser.parse_args(argv)

    try:
        _init_database()
        summary = glossary.apply_department_glossary_validation_review_csv(
            args.csv_path,
            library_id=args.library_id,
            apply=args.apply,
            updated_by_work_id=args.work_id,
        )
    except glossary.DepartmentGlossarySelectionError as exc:
        print(
            "department_glossary_validation_review_apply_error "
            f"code={exc.code} error={exc}",
            file=sys.stderr,
        )
        return 1
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"department_glossary_validation_review_apply_error error={exc}", file=sys.stderr)
        return 1
    _print_summary(summary)
    return 1 if summary.invalid else 0


if __name__ == "__main__":
    raise SystemExit(main())
