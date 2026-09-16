from __future__ import annotations

import argparse
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Export one Department Glossary into a validation review CSV."
    )
    parser.add_argument("output_csv", type=Path)
    parser.add_argument(
        "--library-id",
        type=int,
        default=None,
        help="Department Glossary library id to export.",
    )
    parser.add_argument(
        "--library-code",
        default=None,
        help="Department Glossary library code to export.",
    )
    args = parser.parse_args(argv)

    try:
        _init_database()
        summary = glossary.export_department_glossary_validation_review_csv(
            args.output_csv,
            library_id=args.library_id,
            library_code=args.library_code,
        )
    except glossary.DepartmentGlossarySelectionError as exc:
        print(
            "department_glossary_validation_review_export_error "
            f"code={exc.code} error={exc}",
            file=sys.stderr,
        )
        return 1
    except (OSError, RuntimeError, ValueError) as exc:
        print(f"department_glossary_validation_review_export_error error={exc}", file=sys.stderr)
        return 1
    print(
        "department_glossary_validation_review_export "
        f"library_id={summary.library_id} "
        f"library_code={summary.library_code} "
        f"exported={summary.exported} "
        f"output_path={summary.output_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
