from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def debug_dir(job_dir: Path) -> Path:
    return job_dir / "realtime_debug" / "chunks"


def output_debug_dir(job_dir: Path) -> Path:
    return job_dir / "output" / "realtime_debug" / "chunks"


def debug_roots(job_dir: Path) -> tuple[Path, ...]:
    return (debug_dir(job_dir), output_debug_dir(job_dir))


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(content or ""), encoding="utf-8")


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def chunk_paths(job_dir: Path, chunk_label: str) -> tuple[Path, ...]:
    return tuple(root / chunk_label for root in debug_roots(job_dir))


def record_request(
    *,
    job_dir: Path,
    chunk_label: str,
    mode: str,
    system_prompt: str,
    payload: str,
    expected_ids: list[str],
    extra_meta: dict[str, Any] | None = None,
) -> None:
    meta = {
        "mode": mode,
        "expected_ids": expected_ids,
    }
    if extra_meta:
        meta.update(extra_meta)
    for chunk_dir in chunk_paths(job_dir, chunk_label):
        write_json(chunk_dir / "request_meta.json", meta)
        write_text(chunk_dir / "system_prompt.txt", system_prompt)
        write_text(chunk_dir / "payload.txt", payload)


def record_response(
    *,
    job_dir: Path,
    chunk_label: str,
    attempt: int,
    content: str,
) -> None:
    for chunk_dir in chunk_paths(job_dir, chunk_label):
        write_text(chunk_dir / f"response_attempt_{attempt}.txt", content)


def record_error(
    *,
    job_dir: Path,
    chunk_label: str,
    attempt: int,
    error: str,
) -> None:
    for chunk_dir in chunk_paths(job_dir, chunk_label):
        write_text(chunk_dir / f"error_attempt_{attempt}.txt", error)


def record_parsed(
    *,
    job_dir: Path,
    chunk_label: str,
    translations: dict[str, str],
) -> None:
    for chunk_dir in chunk_paths(job_dir, chunk_label):
        write_json(chunk_dir / "parsed_translations.json", translations)


def record_plan(job_dir: Path, items: list[dict[str, Any]]) -> None:
    write_json(job_dir / "realtime_debug" / "chunk_plan.json", items)
    write_json(job_dir / "output" / "realtime_debug" / "chunk_plan.json", items)
