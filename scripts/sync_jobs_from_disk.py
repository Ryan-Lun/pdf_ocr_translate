from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services import job_store, jobs, state


def main() -> int:
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
    result = jobs.sync_legacy_jobs_from_disk()
    print(
        "job_state_sync "
        f"dry_run=0 scanned={result['scanned']} "
        f"created={result['created']} "
        f"updated={result['updated']} "
        f"would_create={result['would_create']} "
        f"skipped={result['skipped']} "
        f"errors={len(result['errors'])}"
    )
    for detail in result.get("details", []):
        print(
            "job_state_sync_detail "
            f"job_id={detail.get('job_id')} "
            f"action={detail.get('action')} "
            f"reason={detail.get('reason')}"
        )
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
