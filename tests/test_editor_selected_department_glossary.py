from __future__ import annotations

import json

from app.services import glossary, state


def _clear_department_glossary() -> None:
    from app.services import job_store

    with job_store.session_scope() as session:
        session.query(job_store.DepartmentGlossaryEntryRecord).delete()
        session.query(job_store.DepartmentGlossaryLibraryRecord).delete()


def _create_library(
    *,
    code: str,
    name: str,
    department_code: str,
    entries: list[tuple[str, str]],
) -> glossary.DepartmentGlossaryLibrary:
    library = glossary.get_or_create_department_glossary_library(
        code=code,
        name=name,
        department_code=department_code,
        is_active=True,
    )
    for source_term, target_term in entries:
        glossary.upsert_department_glossary_entry(
            library_id=library.library_id,
            source_lang="zh",
            target_lang="en",
            source_term=source_term,
            target_term=target_term,
        )
    return library


def _selected_context(library: glossary.DepartmentGlossaryLibrary) -> dict[str, object]:
    return glossary.add_department_glossary_context_to_config(
        {},
        {
            "source": "sql",
            "library_id": library.library_id,
            "library_code": library.code,
            "library_name": library.name,
            "department_code": library.department_code,
            "entry_count": 0,
        },
    )


def _write_editor_job(job_dir, selected: glossary.DepartmentGlossaryLibrary) -> None:
    job_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "document_mode": "general_force",
        "source_lang": "zh",
        "target_lang": "en",
        "model": "fake-model",
        "system_prompt": "translate",
        **_selected_context(selected),
    }
    (job_dir / "batch_config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    (job_dir / "job_meta.json").write_text(
        json.dumps({"job_type": "ocr_overlay", **config}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _write_edits(job_dir, boxes: list[dict[str, object]]) -> None:
    (job_dir / "edits.json").write_text(
        json.dumps(
            {"pages": [{"page_index_0based": 0, "boxes": boxes}]},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def _setup_job_with_libraries(tmp_path, monkeypatch):
    _clear_department_glossary()
    selected = _create_library(
        code="selected-editor",
        name="選定部門",
        department_code="SEL",
        entries=[("外觀", "Selected Appearance")],
    )
    override = _create_library(
        code="override-editor",
        name="請求覆寫部門",
        department_code="OVR",
        entries=[("外觀", "Override Appearance")],
    )
    job_id = "e" * 32
    job_dir = tmp_path / "jobs" / job_id
    monkeypatch.setattr(state, "JOB_ROOT", tmp_path / "jobs")
    _write_editor_job(job_dir, selected)
    return job_id, job_dir, selected, override


def test_single_box_retranslation_uses_job_selected_glossary_and_ignores_request_override(
    client,
    tmp_path,
    monkeypatch,
):
    job_id, job_dir, selected, override = _setup_job_with_libraries(tmp_path, monkeypatch)
    _write_edits(
        job_dir,
        [
            {
                "id": 200001,
                "deleted": False,
                "bbox": {"x": 10, "y": 10, "w": 80, "h": 20},
                "text": "Old translation",
                "auto_generated": True,
            }
        ],
    )
    captured: dict[str, object] = {}

    def fake_translate(texts, **kwargs):
        captured["texts"] = texts
        captured["glossary_entries"] = kwargs.get("glossary_entries")
        return ["Updated translation"]

    monkeypatch.setattr("app.blueprints.api.routes.batch.translate_texts_for_region", fake_translate)
    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.apply_edits_to_pdf",
        lambda current_job_id, current_job_dir, edits: job_dir / "edited.pdf",
    )

    resp = client.post(
        f"/api/job/{job_id}/retranslate-box",
        json={
            "page_index_0based": 0,
            "box_id": 200001,
            "source_text": "外觀",
            "department_glossary_library_id": override.library_id,
        },
    )

    assert resp.status_code == 200
    assert captured["texts"] == ["外觀"]
    assert captured["glossary_entries"] == [("外觀", "Selected Appearance")]
    hits = json.loads((job_dir / "glossary_hits.json").read_text(encoding="utf-8"))
    assert hits == [
        {
            "source_term": "外觀",
            "approved_term": "Selected Appearance",
            "count": 1,
            "locations": ["editor_box:p0-b200001"],
        }
    ]
    saved_config = json.loads((job_dir / "batch_config.json").read_text(encoding="utf-8"))
    assert saved_config["department_glossary_library_id"] == selected.library_id
    assert saved_config["department_glossary_library_id"] != override.library_id
    assert selected.library_id != override.library_id


def test_region_retranslation_uses_job_selected_glossary_and_ignores_request_override(
    client,
    tmp_path,
    monkeypatch,
):
    job_id, job_dir, selected, override = _setup_job_with_libraries(tmp_path, monkeypatch)
    _write_edits(job_dir, [])
    captured: dict[str, object] = {}

    def fake_translate(texts, **kwargs):
        captured["texts"] = texts
        captured["glossary_entries"] = kwargs.get("glossary_entries")
        return ["Region translation"]

    monkeypatch.setattr("app.blueprints.api.routes.batch.translate_texts_for_region", fake_translate)
    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.apply_edits_to_pdf",
        lambda current_job_id, current_job_dir, edits: job_dir / "edited.pdf",
    )

    resp = client.post(
        f"/api/job/{job_id}/retranslate-region",
        json={
            "page_index_0based": 0,
            "bbox": {"x": 0, "y": 0, "w": 120, "h": 60},
            "merged_bbox": {"x": 10, "y": 10, "w": 80, "h": 20},
            "source_text": "外觀",
            "replace_existing": False,
            "department_glossary_library_id": override.library_id,
        },
    )

    assert resp.status_code == 200
    assert captured["texts"] == ["外觀"]
    assert captured["glossary_entries"] == [("外觀", "Selected Appearance")]
    hits = json.loads((job_dir / "glossary_hits.json").read_text(encoding="utf-8"))
    assert hits[0]["approved_term"] == "Selected Appearance"
    assert hits[0]["locations"] == ["editor_region:p0"]
    saved_config = json.loads((job_dir / "batch_config.json").read_text(encoding="utf-8"))
    assert saved_config["department_glossary_library_id"] == selected.library_id
    assert saved_config["department_glossary_library_id"] != override.library_id


def test_supplemental_region_translation_uses_job_selected_glossary_and_ignores_request_override(
    client,
    tmp_path,
    monkeypatch,
):
    job_id, job_dir, selected, override = _setup_job_with_libraries(tmp_path, monkeypatch)
    _write_edits(job_dir, [])
    captured: dict[str, object] = {}

    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.run_region_ocr",
        lambda current_job_dir, page_idx, bbox: {
            "page_index_0based": page_idx,
            "region_bbox": bbox,
            "rec_polys": [[[15, 15], [65, 15], [65, 25], [15, 25]]],
            "rec_texts": ["外觀"],
            "rec_scores": [0.99],
        },
    )

    def fake_translate(texts, **kwargs):
        captured["texts"] = texts
        captured["glossary_entries"] = kwargs.get("glossary_entries")
        return ["Supplemental translation"]

    monkeypatch.setattr("app.blueprints.api.routes.batch.translate_texts_for_region", fake_translate)
    monkeypatch.setattr(
        "app.blueprints.api.routes.ocr.apply_edits_to_pdf",
        lambda current_job_id, current_job_dir, edits: job_dir / "edited.pdf",
    )

    resp = client.post(
        f"/api/job/{job_id}/retranslate-region",
        json={
            "page_index_0based": 0,
            "bbox": {"x": 0, "y": 0, "w": 120, "h": 60},
            "replace_existing": False,
            "department_glossary_library_id": override.library_id,
        },
    )

    assert resp.status_code == 200
    assert captured["texts"] == ["外觀"]
    assert captured["glossary_entries"] == [("外觀", "Selected Appearance")]
