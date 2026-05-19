from app.services import realtime_translate


def test_extract_batch_item_payload_reuses_batch_messages():
    custom_id, system_prompt, user_text = realtime_translate._extract_batch_item_payload(
        {
            "custom_id": "p0000-l0001",
            "body": {
                "messages": [
                    {"role": "system", "content": "base prompt"},
                    {"role": "user", "content": "source text"},
                ]
            },
        }
    )

    assert custom_id == "p0000-l0001"
    assert system_prompt == "base prompt"
    assert user_text == "source text"


def test_chunk_roundtrip_serializes_and_parses_delimited_items():
    items = [
        {
            "custom_id": "p0000-l0001",
            "body": {
                "messages": [
                    {"role": "system", "content": "base prompt"},
                    {"role": "user", "content": "第一段"},
                ]
            },
        },
        {
            "custom_id": "p0000-l0002",
            "body": {
                "messages": [
                    {"role": "system", "content": "base prompt"},
                    {"role": "user", "content": "第二段"},
                ]
            },
        },
    ]

    serialized = realtime_translate._serialize_translation_chunk(items)
    assert "<<<p0000-l0001>>>" in serialized
    assert "<<<p0000-l0002>>>" in serialized

    parsed = realtime_translate._parse_translation_chunk_output(
        "<<<p0000-l0001>>>\nFirst section\n\n<<<p0000-l0002>>>\nSecond section",
        ["p0000-l0001", "p0000-l0002"],
    )
    assert parsed == {
        "p0000-l0001": "First section",
        "p0000-l0002": "Second section",
    }


def test_chunk_batch_items_respects_segment_limit():
    items = []
    for idx in range(3):
        items.append(
            {
                "custom_id": f"p0000-l000{idx}",
                "body": {
                    "messages": [
                        {"role": "system", "content": "base prompt"},
                        {"role": "user", "content": f"文字 {idx}"},
                    ]
                },
            }
        )

    chunks = realtime_translate._chunk_batch_items(items, max_segments=2, max_chars=100)
    assert [len(chunk) for chunk in chunks] == [2, 1]


def test_normalize_numbered_item_breaks_splits_later_items_on_same_line():
    text = "1. First step 2. Second step 3. Third step"

    assert realtime_translate._normalize_numbered_item_breaks(text) == (
        "1. First step\n2. Second step\n3. Third step"
    )


def test_normalize_numbered_item_breaks_preserves_single_item_line():
    text = "Section 2. Scope"

    assert realtime_translate._normalize_numbered_item_breaks(text) == text


def test_normalize_numbered_item_breaks_splits_first_item_after_colon():
    text = "Steps: 1. First step 2. Second step"

    assert realtime_translate._normalize_numbered_item_breaks(text) == (
        "Steps:\n1. First step\n2. Second step"
    )


def test_glossary_protection_wraps_and_restores_terms():
    protected = realtime_translate.batch.glossary.apply_glossary_with_protection(
        "本產品符合品質系統規範。",
        [("品質系統規範", "Quality System Regulation")],
    )

    assert "Quality System Regulation" in protected
    assert "[[[GLOSSARY_TERM_" in protected
    assert (
        realtime_translate.batch.glossary.restore_protected_glossary_terms(protected)
        == "本產品符合Quality System Regulation。"
    )


def test_normalize_realtime_translation_restores_terms_and_numbered_items():
    text = (
        "1. First step [[[GLOSSARY_TERM_0001::Quality System Regulation]]] "
        "2. Second step"
    )

    assert realtime_translate._normalize_realtime_translation(text) == (
        "1. First step Quality System Regulation\n2. Second step"
    )


def test_extract_merge_notice_candidates_from_missing_delimiter():
    items = [
        {
            "custom_id": "p0009-b0007",
            "body": {
                "messages": [
                    {"role": "system", "content": "base prompt"},
                    {"role": "user", "content": "第一段原文"},
                ]
            },
        },
        {
            "custom_id": "p0010-b0002",
            "body": {
                "messages": [
                    {"role": "system", "content": "base prompt"},
                    {"role": "user", "content": "第二段原文"},
                ]
            },
        },
    ]

    candidates = realtime_translate._extract_merge_notice_candidates(
        "<<<p0009-b0007>>>\nMerged translation spanning both pages",
        items,
    )

    assert candidates == [
        {
            "notice_id": "p0009-b0007__p0010-b0002",
            "status": "pending",
            "primary_custom_id": "p0009-b0007",
            "secondary_custom_id": "p0010-b0002",
            "primary_page_index_0based": 9,
            "secondary_page_index_0based": 10,
            "primary_box_id": 200007,
            "secondary_box_id": 200002,
            "primary_kind": "b",
            "secondary_kind": "b",
            "source_text": "第一段原文\n第二段原文",
            "suggested_translation": "Merged translation spanning both pages",
        }
    ]


def test_finalize_translation_job_writes_realtime_restore_snapshot(tmp_path, monkeypatch):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    monkeypatch.setattr(
        realtime_translate.batch.ocr,
        "apply_edits_to_pdf",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        realtime_translate.batch.jobs,
        "write_batch_status",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        realtime_translate.batch.jobs,
        "set_job_state",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        realtime_translate.batch.translation_memory,
        "load_translation_memory",
        lambda: {},
    )
    monkeypatch.setattr(
        realtime_translate.batch.translation_memory,
        "write_translation_memory",
        lambda memory: None,
    )

    realtime_translate.batch.finalize_translation_job(
        job_id="a" * 32,
        job_dir=job_dir,
        ocr_pages=[{"page_index_0based": 0, "rec_texts": [], "rec_polys": []}],
        pp_pages={},
        document_mode="general_force",
        target_lang="en",
        key_map={},
        translations={"p0000-b0001": "Header", "p0000-c0000": "Cell"},
        status_meta={},
        backend_id="realtime",
    )

    raw_text = (job_dir / realtime_translate.state.BATCH_OUTPUT_NAME).read_text(encoding="utf-8")
    assert '"custom_id": "p0000-b0001"' in raw_text
    assert '"output_text": "Header"' in raw_text


def test_finalize_translation_job_skips_tm_write_when_overlay_tm_disabled(tmp_path, monkeypatch):
    job_dir = tmp_path / "job"
    job_dir.mkdir()
    monkeypatch.setattr(realtime_translate.state, "PDF_OVERLAY_ENABLE_TRANSLATION_MEMORY", False)
    monkeypatch.setattr(
        realtime_translate.batch.ocr,
        "apply_edits_to_pdf",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        realtime_translate.batch.jobs,
        "write_batch_status",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        realtime_translate.batch.jobs,
        "set_job_state",
        lambda *args, **kwargs: None,
    )

    called = {"load": 0, "write": 0}
    monkeypatch.setattr(
        realtime_translate.batch.translation_memory,
        "load_translation_memory",
        lambda: called.__setitem__("load", called["load"] + 1) or {},
    )
    monkeypatch.setattr(
        realtime_translate.batch.translation_memory,
        "write_translation_memory",
        lambda memory: called.__setitem__("write", called["write"] + 1),
    )

    realtime_translate.batch.finalize_translation_job(
        job_id="b" * 32,
        job_dir=job_dir,
        ocr_pages=[{"page_index_0based": 0, "rec_texts": [], "rec_polys": []}],
        pp_pages={},
        document_mode="general_force",
        target_lang="en",
        key_map={
            "p0000-b0001": {
                "source_text": "標題",
                "source_normalized": "標題",
            }
        },
        translations={"p0000-b0001": "Header"},
        status_meta={},
        backend_id="realtime",
    )

    assert called == {"load": 0, "write": 0}
