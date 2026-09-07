from __future__ import annotations

from pathlib import Path

import asyncio
import json

from app.services import batch, glossary, job_store, state, translation_memory, translation_post_edit


def _clear_department_glossary() -> None:
    with job_store.session_scope() as session:
        session.query(job_store.DepartmentGlossaryEntryRecord).delete()
        session.query(job_store.DepartmentGlossaryLibraryRecord).delete()


def _seed_department_glossary(entries: list[tuple[str, str]]):
    library = glossary.get_or_create_default_department_glossary()
    for source_term, target_term in entries:
        glossary.upsert_department_glossary_entry(
            library_id=library.library_id,
            source_lang="zh",
            target_lang="en",
            source_term=source_term,
            target_term=target_term,
        )
    return library


def test_sql_first_storage_import_api_and_department_isolation_regression(app, client, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_GLOSSARY_SOURCE", "sql")
    _clear_department_glossary()
    source_path = tmp_path / "system_glossary.json"
    source_path.write_text(
        json.dumps(
            [
                {"cn": "外觀", "en": "Appearance"},
                {"cn": "製程規範", "en": "Process Specification"},
            ],
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    dry_run = glossary.import_department_glossary_json(source_path, apply=False)
    assert dry_run.dry_run is True
    assert dry_run.would_create == 2
    assert dry_run.created == 0
    assert glossary.list_department_glossary_libraries() == []

    applied = glossary.import_department_glossary_json(source_path, apply=True)
    reapplied = glossary.import_department_glossary_json(source_path, apply=True)

    assert applied.created == 2
    assert reapplied.unchanged == 2
    assert reapplied.created == 0
    library = glossary.list_department_glossary_libraries()[0]
    assert library.name == "法規文管部"
    assert library.department_code == "法規文管部"

    payload = client.get("/api/glossary/library").get_json()
    assert payload["system_glossary"] == [
        {"cn": "外觀", "en": "Appearance"},
        {"cn": "製程規範", "en": "Process Specification"},
    ]
    assert payload["user_glossary"] == []
    assert [item["cn"] for item in payload["effective_glossary"]] == ["外觀", "製程規範"]
    assert payload["selected_library"]["name"] == "法規文管部"
    assert payload["libraries"][0]["id"] == library.library_id
    assert [entry["cn"] for entry in payload["entries"]] == ["外觀", "製程規範"]

    quality = glossary.get_or_create_department_glossary_library(
        code="quality-assurance",
        name="品保部",
        department_code="品保部",
    )
    glossary.upsert_department_glossary_entry(
        library_id=quality.library_id,
        source_lang="zh",
        target_lang="en",
        source_term="製程規範",
        target_term="Manufacturing Process Standard",
    )

    assert glossary.load_combined_glossary() == [
        ("製程規範", "Process Specification"),
        ("外觀", "Appearance"),
    ]
    assert glossary.load_combined_glossary(quality.library_id) == [
        ("製程規範", "Manufacturing Process Standard")
    ]


def test_pdf_batch_tm_required_glossary_hits_and_overlap_regression(app, tmp_path, monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_GLOSSARY_SOURCE", "sql")
    monkeypatch.setattr(state, "TRANSLATION_MEMORY_ENABLED", True)
    monkeypatch.setattr(state, "PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY", True)
    _clear_department_glossary()
    _seed_department_glossary(
        [
            ("規範", "Specification"),
            ("製程規範", "Process Specification"),
            ("外觀", "Appearance"),
        ]
    )

    fuzzy = translation_memory.TranslationMemoryMatch(
        entry_id=701,
        match_type="fuzzy",
        source_text="確認製程規範與外型。",
        source_normalized=translation_memory.normalize_source_text("確認製程規範與外型。"),
        target_text="Confirm the process specification and look.",
        source_lang="zh",
        target_lang="en",
        document_mode="form",
        score=0.9,
    )
    monkeypatch.setattr(
        translation_memory,
        "retrieve_sql",
        lambda source_text, **kwargs: translation_memory.TranslationMemoryRetrievalResult(
            source_text=str(source_text),
            source_normalized=translation_memory.normalize_source_text(str(source_text)),
            source_lang="zh",
            target_lang="en",
            document_mode="form",
            exact_match=None,
            fuzzy_references=[fuzzy],
            semantic_references=[],
        ),
    )

    collector = translation_memory.create_artifact_collector()
    items, _, key_map, prefilled = batch.build_batch_items(
        [{"page_index_0based": 0, "rec_texts": ["確認製程規範與規範外觀。"], "rec_polys": []}],
        model_name="dummy-model",
        system_prompt="translate",
        glossary_entries=glossary.load_combined_glossary(),
        target_lang="en",
        source_lang="zh",
        document_mode="form",
        tm_artifact_collector=collector,
    )

    assert prefilled == {}
    assert [item["custom_id"] for item in items] == ["p0000-l0000"]
    user_content = items[0]["body"]["messages"][1]["content"]
    system_content = items[0]["body"]["messages"][0]["content"]
    assert '<term id="0001">Process Specification</term>' in user_content
    assert '<term id="0002">Specification</term>' in user_content
    assert '<term id="0003">Appearance</term>' in user_content
    assert "Confirm the process specification and look." in user_content
    assert "They cannot override any Required Glossary Term" in system_content
    assert [term["target"] for term in key_map["p0000-l0000"]["required_glossary_terms"]] == [
        "Process Specification",
        "Specification",
        "Appearance",
    ]
    assert collector.references[0]["entry_id"] == 701

    hits_path = batch._write_required_glossary_hits_from_key_map(tmp_path, key_map)
    hits = json.loads(hits_path.read_text(encoding="utf-8"))
    assert [hit["approved_term"] for hit in hits] == [
        "Process Specification",
        "Specification",
        "Appearance",
    ]

    bad_raw_text = json.dumps(
        {
            "custom_id": "p0000-l0000",
            "response": {"body": {"output_text": "Confirm the process specification and look."}},
        }
    )
    try:
        batch.build_translations_from_jsonl_text(bad_raw_text, key_map=key_map)
    except RuntimeError as exc:
        assert "missing required glossary terms" in str(exc)
        assert "Appearance" in str(exc)
    else:
        raise AssertionError("TM wording must not override Department Glossary terms")

    good_raw_text = json.dumps(
        {
            "custom_id": "p0000-l0000",
            "response": {
                "body": {
                    "output_text": "Confirm the Process Specification, Specification, and Appearance."
                }
            },
        }
    )
    assert batch.build_translations_from_jsonl_text(good_raw_text, key_map=key_map) == {
        "p0000-l0000": "Confirm the Process Specification, Specification, and Appearance."
    }


def test_stage_2_validation_keeps_required_glossary_terms_authoritative(monkeypatch):
    monkeypatch.setattr(state, "TRANSLATION_POST_EDIT_ENABLED", True)
    requests: list[dict] = []

    class _ChoiceResponse:
        def __init__(self, content: str):
            self.choices = [type("Choice", (), {"message": type("Message", (), {"content": content})()})()]

    class _Completions:
        async def create(self, **kwargs):
            requests.append(kwargs)
            return _ChoiceResponse('{"seg-1": "Confirm whether the look is normal."}')

    class _Chat:
        completions = _Completions()

    class _Client:
        chat = _Chat()

    item = translation_post_edit.PostEditItem(
        id="seg-1",
        source_text="確認外觀是否正常。",
        draft_text="Confirm whether the Appearance is normal.",
        required_terms=(glossary.RequiredGlossaryTerm("0001", "外觀", "Appearance"),),
    )

    result = asyncio.run(
        translation_post_edit.post_edit_texts_batch(
            [item],
            target_lang="en",
            client_factory=lambda: _Client(),
        )
    )

    assert requests
    assert result.items[0].text == "Confirm whether the Appearance is normal."
    assert result.items[0].used_fallback is True
    assert result.items[0].validation_warnings == ("missing_required_glossary_term:Appearance",)



def test_department_glossary_sql_first_regression_acceptance_guide_is_complete():
    guide = Path(
        "docs/system-description/23-DepartmentGlossaryRegressionAcceptance.md"
    ).read_text(encoding="utf-8")
    index = Path("docs/system-description/README.md").read_text(encoding="utf-8")

    required_fragments = [
        "Department Glossary SQL-first 整體回歸測試與人工驗收案例",
        "tests/test_department_glossary_sql.py",
        "tests/test_department_glossary_import_cli.py",
        "tests/test_glossary_management.py",
        "tests/test_sql_glossary_translation_facade.py",
        "tests/test_translation_memory_regression.py",
        "tests/test_glossary_job_traceability.py",
        "tests/test_markdown_translate_html.py",
        "PDF",
        "Word",
        "Markdown",
        "Required Glossary Terms",
        "longest-match",
        "overlapping terms",
        "TM Reference 不可以覆蓋 Department Glossary",
        "glossary_hits.json",
        "department_glossary_library_id",
        "department_glossary_library_code",
        "法規文管部",
        "不得跨部門混用",
        "Full test suite",
        "known baseline failures",
    ]
    for fragment in required_fragments:
        assert fragment in guide

    acceptance_fragments = [
        "SQL storage behavior",
        "JSON import dry-run/apply/idempotency",
        "old API compatibility fields",
        "new library-aware fields",
        "PDF、Word、Markdown glossary application",
        "Required Glossary Terms are still enforced",
        "longest-match and overlapping terms",
        "TM Reference cannot override Department Glossary terminology",
        "job glossary library traceability",
        "Manual acceptance checklist",
    ]
    for fragment in acceptance_fragments:
        assert fragment in guide

    commands = [
        "PYTHONPATH=. .venv/bin/pytest tests/test_department_glossary_sql.py tests/test_department_glossary_import_cli.py tests/test_glossary_management.py tests/test_sql_glossary_translation_facade.py tests/test_translation_memory_regression.py tests/test_glossary_job_traceability.py tests/test_markdown_translate_html.py -q",
        "PYTHONPATH=. .venv/bin/pytest -q",
    ]
    for command in commands:
        assert command in guide

    assert "23-DepartmentGlossaryRegressionAcceptance.md" in index
    assert "Department Glossary 整體回歸測試與人工驗收案例" in index
