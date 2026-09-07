from __future__ import annotations

import zipfile
from io import BytesIO

from app.services import glossary, job_store



def _clear_department_glossary():
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


def _build_xlsx(rows):
    shared_strings = []
    shared_index = {}
    sheet_rows = []
    for row_idx, row in enumerate(rows, start=1):
        cells = []
        for col_idx, value in enumerate(row, start=1):
            text = str(value)
            if text not in shared_index:
                shared_index[text] = len(shared_strings)
                shared_strings.append(text)
            cell_ref = f"{chr(64 + col_idx)}{row_idx}"
            cells.append(f'<c r="{cell_ref}" t="s"><v>{shared_index[text]}</v></c>')
        sheet_rows.append(f'<row r="{row_idx}">{"".join(cells)}</row>')
    shared_xml = "".join(f"<si><t>{text}</t></si>" for text in shared_strings)
    sheet_xml = "".join(sheet_rows)
    stream = BytesIO()
    with zipfile.ZipFile(stream, "w") as zf:
        zf.writestr(
            "[Content_Types].xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/sharedStrings.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sharedStrings+xml"/>
</Types>""",
        )
        zf.writestr(
            "_rels/.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>""",
        )
        zf.writestr(
            "xl/workbook.xml",
            """<?xml version="1.0" encoding="UTF-8"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
 xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets>
    <sheet name="Sheet1" sheetId="1" r:id="rId1"/>
  </sheets>
</workbook>""",
        )
        zf.writestr(
            "xl/_rels/workbook.xml.rels",
            """<?xml version="1.0" encoding="UTF-8"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
</Relationships>""",
        )
        zf.writestr(
            "xl/sharedStrings.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" count="{len(shared_strings)}" uniqueCount="{len(shared_strings)}">
  {shared_xml}
</sst>""",
        )
        zf.writestr(
            "xl/worksheets/sheet1.xml",
            f"""<?xml version="1.0" encoding="UTF-8"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <sheetData>
    {sheet_xml}
  </sheetData>
</worksheet>""",
        )
    return stream.getvalue()


def test_glossary_page_ok(client):
    resp = client.get("/workspace/glossary")
    assert resp.status_code == 200
    html = resp.get_data(as_text=True)
    assert "詞彙庫管理" in html
    assert 'id="libraryNewBtn"' in html
    assert 'id="libraryList"' in html
    assert 'id="disableLibraryBtn"' in html


def test_glossary_library_payload_maps_to_default_department_glossary(client):
    _clear_department_glossary()
    _seed_department_glossary([("批號", "Lot No."), ("製造日期", "Manufacturing Date")])

    resp = client.get("/api/glossary/library")
    assert resp.status_code == 200
    payload = resp.get_json()

    assert payload["ok"] is True
    assert payload["system_glossary"] == [
        {"cn": "批號", "en": "Lot No."},
        {"cn": "製造日期", "en": "Manufacturing Date"},
    ]
    assert payload["user_glossary"] == []
    assert payload["effective_glossary"] == [
        {
            "cn": "批號",
            "en": "Lot No.",
            "source": "system",
            "overridden": False,
            "system_en": "Lot No.",
            "user_en": None,
        },
        {
            "cn": "製造日期",
            "en": "Manufacturing Date",
            "source": "system",
            "overridden": False,
            "system_en": "Manufacturing Date",
            "user_en": None,
        },
    ]
    assert payload["libraries"][0]["code"] == glossary.DEFAULT_DEPARTMENT_GLOSSARY_CODE
    assert payload["selected_library"] == payload["libraries"][0]
    assert [entry["cn"] for entry in payload["entries"]] == ["批號", "製造日期"]


def test_glossary_post_updates_default_department_glossary(client):
    _clear_department_glossary()

    save_resp = client.post(
        "/api/glossary",
        json={"glossary": [{"cn": "批號", "en": "Batch No."}]},
    )
    assert save_resp.status_code == 200

    payload = client.get("/api/glossary/library").get_json()
    effective = payload["effective_glossary"]
    assert effective[0]["cn"] == "批號"
    assert effective[0]["source"] == "system"
    assert effective[0]["overridden"] is False
    assert effective[0]["en"] == "Batch No."


def test_system_glossary_excel_preview_and_apply(client):
    _clear_department_glossary()
    _seed_department_glossary([("批號", "Lot No."), ("製造日期", "Manufacturing Date")])

    workbook = _build_xlsx(
        [
            ["cn", "en"],
            ["批號", "Batch No."],
            ["新詞", "New Term"],
            ["新詞", "New Term 2"],
            ["缺英文", ""],
        ]
    )
    preview_resp = client.post(
        "/api/glossary/system-import-preview",
        data={"file": (BytesIO(workbook), "system.xlsx")},
        content_type="multipart/form-data",
    )
    assert preview_resp.status_code == 200
    preview = preview_resp.get_json()
    assert preview["ok"] is True
    assert preview["summary"] == {
        "incoming": 2,
        "additions": 1,
        "updates": 1,
        "unchanged": 0,
    }
    assert len(preview["duplicates"]) == 1
    assert len(preview["invalid_rows"]) == 1

    apply_resp = client.post(
        "/api/glossary/system-import-apply",
        json={
            "items": preview["items"],
            "duplicates": preview["duplicates"],
            "invalid_rows": preview["invalid_rows"],
        },
    )
    assert apply_resp.status_code == 400
    payload = apply_resp.get_json()
    assert payload["ok"] is False
    assert "重複詞彙列" in payload["error"]


def test_system_glossary_excel_apply_succeeds_without_blocking_issues(client):
    _clear_department_glossary()
    _seed_department_glossary([("批號", "Lot No.")])

    workbook = _build_xlsx(
        [
            ["cn", "en"],
            ["批號", "Batch No."],
            ["新詞", "New Term"],
        ]
    )
    preview_resp = client.post(
        "/api/glossary/system-import-preview",
        data={"file": (BytesIO(workbook), "system.xlsx")},
        content_type="multipart/form-data",
    )
    preview = preview_resp.get_json()
    assert preview["duplicates"] == []
    assert preview["invalid_rows"] == []

    apply_resp = client.post(
        "/api/glossary/system-import-apply",
        json={
            "items": preview["items"],
            "duplicates": preview["duplicates"],
            "invalid_rows": preview["invalid_rows"],
        },
    )
    assert apply_resp.status_code == 200
    payload = apply_resp.get_json()
    assert payload["ok"] is True
    assert payload["system_glossary"] == [
        {"cn": "批號", "en": "Batch No."},
        {"cn": "新詞", "en": "New Term"},
    ]


def test_system_glossary_excel_preview_requires_cn_en_header(client):
    workbook = _build_xlsx(
        [
            ["source", "target"],
            ["批號", "Batch No."],
        ]
    )
    resp = client.post(
        "/api/glossary/system-import-preview",
        data={"file": (BytesIO(workbook), "bad.xlsx")},
        content_type="multipart/form-data",
    )
    assert resp.status_code == 400
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "cn" in payload["error"]


def test_system_glossary_export_returns_xlsx(client):
    _clear_department_glossary()
    _seed_department_glossary([("批號", "Lot No.")])

    resp = client.get("/api/glossary/system-export")
    assert resp.status_code == 200
    assert resp.mimetype == "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    assert "system_glossary.xlsx" in resp.headers.get("Content-Disposition", "")
    parsed = glossary.parse_system_glossary_excel(resp.data)
    assert parsed["items"] == [{"cn": "批號", "en": "Lot No."}]


def test_glossary_post_syncs_default_department_library_without_changing_request_shape(client):
    _clear_department_glossary()

    resp = client.post(
        "/api/glossary",
        json={"glossary": [{"cn": "外觀", "en": "Appearance"}]},
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["ok"] is True
    assert payload["glossary"] == [{"cn": "外觀", "en": "Appearance"}]
    library_payload = client.get("/api/glossary/library").get_json()
    assert library_payload["system_glossary"] == [{"cn": "外觀", "en": "Appearance"}]
    library = glossary.list_department_glossary_libraries()[0]
    entries = glossary.list_department_glossary_entries(library.library_id, active_only=True)
    assert [(entry.source_term, entry.target_term) for entry in entries] == [("外觀", "Appearance")]


def test_glossary_post_sync_disables_removed_department_entries(client):
    _clear_department_glossary()
    library = _seed_department_glossary([("外觀", "Appearance"), ("製程規範", "Process Specification")])

    resp = client.post(
        "/api/glossary",
        json={"glossary": [{"cn": "外觀", "en": "Appearance"}]},
    )

    assert resp.status_code == 200
    active = glossary.list_department_glossary_entries(library.library_id, active_only=True)
    all_entries = glossary.list_department_glossary_entries(library.library_id)
    assert [entry.source_term for entry in active] == ["外觀"]
    assert {entry.source_term: entry.status for entry in all_entries} == {
        "外觀": "active",
        "製程規範": "disabled",
    }


def test_system_glossary_import_apply_writes_department_glossary_sql(client):
    _clear_department_glossary()

    resp = client.post(
        "/api/glossary/system-import-apply",
        json={
            "items": [{"cn": "製程規範", "en": "Process Specification"}],
            "duplicates": [],
            "invalid_rows": [],
        },
    )

    assert resp.status_code == 200
    payload = resp.get_json()
    assert payload["system_glossary"] == [{"cn": "製程規範", "en": "Process Specification"}]
    assert payload["entries"][0]["cn"] == "製程規範"
    library = glossary.list_department_glossary_libraries()[0]
    entries = glossary.list_department_glossary_entries(library.library_id, active_only=True)
    assert [(entry.source_term, entry.target_term) for entry in entries] == [("製程規範", "Process Specification")]


def test_glossary_write_paths_require_admin_when_auth_enabled(client, monkeypatch):
    _clear_department_glossary()
    library = glossary.create_department_glossary_library(name="品保部", department_code="QA")
    client.application.config["AUTH_ENABLED"] = True
    client.application.config["AUTH_STUB_ENABLED"] = True
    client.post("/auth/login", data={"username": "editor1", "display_name": "Editor One"})
    monkeypatch.setattr("app.blueprints.api.glossary_routes.authz_service.user_is_admin", lambda _user: False)

    save_resp = client.post("/api/glossary", json={"glossary": [{"cn": "外觀", "en": "Appearance"}]})
    apply_resp = client.post(
        "/api/glossary/system-import-apply",
        json={"items": [{"cn": "外觀", "en": "Appearance"}], "duplicates": [], "invalid_rows": []},
    )
    create_library_resp = client.post(
        "/api/glossary/libraries",
        json={"name": "品保二部", "department_code": "QA2"},
    )
    update_library_resp = client.patch(
        f"/api/glossary/libraries/{library.library_id}",
        json={"name": "品保部更新", "department_code": "QAD"},
    )
    disable_library_resp = client.post(f"/api/glossary/libraries/{library.library_id}/disable")

    assert save_resp.status_code == 403
    assert apply_resp.status_code == 403
    assert create_library_resp.status_code == 403
    assert update_library_resp.status_code == 403
    assert disable_library_resp.status_code == 403
    assert glossary.resolve_selected_department_glossary(library.library_id).is_active is True


def test_glossary_write_paths_allow_admin_when_auth_enabled(client, monkeypatch):
    _clear_department_glossary()
    client.application.config["AUTH_ENABLED"] = True
    client.application.config["AUTH_STUB_ENABLED"] = True
    client.post("/auth/login", data={"username": "admin1", "display_name": "Admin One"})
    monkeypatch.setattr("app.blueprints.api.glossary_routes.authz_service.user_is_admin", lambda _user: True)

    save_resp = client.post("/api/glossary", json={"glossary": [{"cn": "外觀", "en": "Appearance"}]})
    apply_resp = client.post(
        "/api/glossary/system-import-apply",
        json={"items": [{"cn": "製程規範", "en": "Process Specification"}], "duplicates": [], "invalid_rows": []},
    )
    create_library_resp = client.post(
        "/api/glossary/libraries",
        json={"name": "品保部", "department_code": "QA"},
    )

    assert save_resp.status_code == 200
    assert apply_resp.status_code == 200
    assert create_library_resp.status_code == 200
    library = glossary.list_department_glossary_libraries()[0]
    entries = glossary.list_department_glossary_entries(library.library_id, active_only=True)
    assert {entry.source_term: entry.target_term for entry in entries} == {
        "外觀": "Appearance",
        "製程規範": "Process Specification",
    }


def test_department_glossary_library_lifecycle_api_create_update_disable(client):
    _clear_department_glossary()

    create_resp = client.post(
        "/api/glossary/libraries",
        json={"name": "品保部詞彙", "department_code": "QA"},
    )

    assert create_resp.status_code == 200
    created = create_resp.get_json()["library"]
    assert created["name"] == "品保部詞彙"
    assert created["department_code"] == "QA"
    assert created["is_active"] is True
    assert created["is_default"] is False
    assert created["code"]

    update_resp = client.patch(
        f"/api/glossary/libraries/{created['id']}",
        json={
            "name": "品質保證部詞彙",
            "department_code": "QAD",
            "code": "attempted-code-change",
        },
    )

    assert update_resp.status_code == 200
    updated = update_resp.get_json()["library"]
    assert updated["id"] == created["id"]
    assert updated["code"] == created["code"]
    assert updated["name"] == "品質保證部詞彙"
    assert updated["department_code"] == "QAD"

    disable_resp = client.post(f"/api/glossary/libraries/{created['id']}/disable")

    assert disable_resp.status_code == 200
    disabled = disable_resp.get_json()["library"]
    assert disabled["is_active"] is False
    assert disabled["code"] == created["code"]
    active_library_ids = [
        item.library_id
        for item in glossary.list_department_glossary_libraries(active_only=True)
    ]
    assert created["id"] not in active_library_ids


def test_department_glossary_library_create_requires_name_and_department_code(client):
    _clear_department_glossary()

    missing_name = client.post(
        "/api/glossary/libraries",
        json={"name": "", "department_code": "QA"},
    )
    missing_department = client.post(
        "/api/glossary/libraries",
        json={"name": "品保部詞彙", "department_code": ""},
    )

    assert missing_name.status_code == 400
    assert "名稱" in missing_name.get_json()["error"]
    assert missing_department.status_code == 400
    assert "部門代碼" in missing_department.get_json()["error"]


def test_department_glossary_library_management_payload_includes_inactive_libraries(client):
    _clear_department_glossary()
    active = glossary.create_department_glossary_library(name="品保部", department_code="QA")
    inactive = glossary.create_department_glossary_library(name="停用部門", department_code="OFF")
    glossary.disable_department_glossary_library(inactive.library_id)

    payload = client.get("/api/glossary/library").get_json()

    library_ids = [item["id"] for item in payload["libraries"]]
    assert active.library_id in library_ids
    assert inactive.library_id in library_ids
    inactive_payload = next(item for item in payload["libraries"] if item["id"] == inactive.library_id)
    assert inactive_payload["is_active"] is False


def test_inactive_department_glossary_libraries_are_hidden_from_new_job_selectors(client):
    _clear_department_glossary()
    active = glossary.create_department_glossary_library(name="品保部", department_code="QA")
    inactive = glossary.create_department_glossary_library(name="停用部門", department_code="OFF")
    glossary.disable_department_glossary_library(inactive.library_id)

    for path in ("/workspace/pdf-overlay", "/workspace/pdf-doc", "/workspace/word"):
        html = client.get(path).get_data(as_text=True)
        assert f'<option value="{active.library_id}">品保部 (QA)</option>' in html
        assert f'<option value="{inactive.library_id}">停用部門 (OFF)</option>' not in html


def test_department_glossary_library_disable_is_blocked_for_queued_or_running_jobs(client):
    _clear_department_glossary()
    library = glossary.create_department_glossary_library(name="品保部", department_code="QA")
    job_store.create_job(
        job_id="1" * 32,
        job_type="ocr_overlay",
        stage="queued",
        status="queued",
        job_name="queued glossary job",
        payload={"department_glossary_library_id": library.library_id},
    )

    resp = client.post(f"/api/glossary/libraries/{library.library_id}/disable")

    assert resp.status_code == 409
    payload = resp.get_json()
    assert payload["ok"] is False
    assert "執行中或佇列中" in payload["error"]
    assert glossary.resolve_selected_department_glossary(library.library_id).is_active is True
    job_store.delete_job("1" * 32)


def test_department_glossary_library_disable_allows_completed_job_trace(client):
    _clear_department_glossary()
    library = glossary.create_department_glossary_library(name="品保部", department_code="QA")
    job_store.create_job(
        job_id="2" * 32,
        job_type="ocr_overlay",
        stage="completed",
        status="completed",
        job_name="completed glossary job",
        payload={"department_glossary_library_id": library.library_id},
    )

    resp = client.post(f"/api/glossary/libraries/{library.library_id}/disable")

    assert resp.status_code == 200
    selected = glossary.resolve_selected_department_glossary(
        library.library_id,
        require_active=False,
    )
    assert selected.name == "品保部"
    assert selected.department_code == "QA"
    assert selected.is_active is False
    job_store.delete_job("2" * 32)


def test_department_glossary_library_hard_delete_route_is_not_exposed(client):
    _clear_department_glossary()
    library = glossary.create_department_glossary_library(name="品保部", department_code="QA")

    resp = client.delete(f"/api/glossary/libraries/{library.library_id}")

    assert resp.status_code == 405
    assert glossary.resolve_selected_department_glossary(library.library_id).is_active is True


def test_default_department_glossary_library_update_survives_management_payload_refresh(client):
    _clear_department_glossary()
    default = glossary.get_or_create_default_department_glossary()

    update_resp = client.patch(
        f"/api/glossary/libraries/{default.library_id}",
        json={"name": "法規文件管理部", "department_code": "DOC"},
    )

    assert update_resp.status_code == 200
    payload = client.get("/api/glossary/library").get_json()
    selected = payload["selected_library"]
    assert selected["id"] == default.library_id
    assert selected["name"] == "法規文件管理部"
    assert selected["department_code"] == "DOC"


def test_default_department_glossary_library_disable_survives_management_payload_refresh(client):
    _clear_department_glossary()
    default = glossary.get_or_create_default_department_glossary()

    disable_resp = client.post(f"/api/glossary/libraries/{default.library_id}/disable")

    assert disable_resp.status_code == 200
    payload = client.get("/api/glossary/library").get_json()
    selected = payload["selected_library"]
    assert selected["id"] == default.library_id
    assert selected["is_active"] is False
    assert glossary.resolve_selected_department_glossary(
        default.library_id,
        require_active=False,
    ).is_active is False
