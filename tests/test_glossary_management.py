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
    assert "詞彙庫管理" in resp.get_data(as_text=True)


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
    client.application.config["AUTH_ENABLED"] = True
    client.application.config["AUTH_STUB_ENABLED"] = True
    client.post("/auth/login", data={"username": "editor1", "display_name": "Editor One"})
    monkeypatch.setattr("app.blueprints.api.glossary_routes.authz_service.user_is_admin", lambda _user: False)

    save_resp = client.post("/api/glossary", json={"glossary": [{"cn": "外觀", "en": "Appearance"}]})
    apply_resp = client.post(
        "/api/glossary/system-import-apply",
        json={"items": [{"cn": "外觀", "en": "Appearance"}], "duplicates": [], "invalid_rows": []},
    )

    assert save_resp.status_code == 403
    assert apply_resp.status_code == 403
    assert glossary.list_department_glossary_libraries() == []



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

    assert save_resp.status_code == 200
    assert apply_resp.status_code == 200
    library = glossary.list_department_glossary_libraries()[0]
    entries = glossary.list_department_glossary_entries(library.library_id, active_only=True)
    assert {entry.source_term: entry.target_term for entry in entries} == {
        "外觀": "Appearance",
        "製程規範": "Process Specification",
    }
