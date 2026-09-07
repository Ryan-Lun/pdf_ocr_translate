from __future__ import annotations

from pathlib import Path
from typing import Any

from . import glossary, jobs


def load_and_trace_job_department_glossary_entries(
    *,
    job_id: str,
    job_dir: Path,
    config: dict[str, Any],
    meta: dict[str, Any] | None = None,
    source_lang: str = "auto",
    target_lang: str = "en",
) -> list[tuple[str, str]]:
    selected_library_id = glossary.selected_department_glossary_library_id_from_mappings(
        config,
        meta or jobs.load_job_meta(job_dir),
        jobs.job_store.deserialize_payload(jobs.job_store.get_job(job_id)),
    )
    entries, context = glossary.load_execution_department_glossary(
        selected_library_id,
        source_lang=source_lang,
        target_lang=target_lang,
    )
    glossary.add_department_glossary_context_to_config(config, context)
    jobs.write_batch_config(job_dir, config)
    glossary.write_department_glossary_context_artifact(job_dir, context)
    return entries


def write_editor_required_glossary_hits(
    *,
    job_dir: Path,
    glossary_entries: list[tuple[str, str]],
    source_items: list[tuple[str, str]],
    source_lang: str = "auto",
    target_lang: str = "en",
) -> None:
    hits_by_location = [
        (
            location,
            glossary.apply_required_glossary_terms(
                source_text,
                glossary_entries,
                source_lang=source_lang,
                target_lang=target_lang,
            ),
        )
        for location, source_text in source_items
    ]
    glossary.write_required_glossary_hits_artifact(job_dir, hits_by_location)
